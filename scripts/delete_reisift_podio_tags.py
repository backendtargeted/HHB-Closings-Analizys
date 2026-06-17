#!/usr/bin/env python3
"""
Delete REISift / DataSift property tags matching a search term (default: podio).

This is browser automation (Playwright), not Beautiful Soup — BS4 only reads HTML;
it cannot click menus, confirm dialogs, or drive a logged-in session.

Setup (one time) — use the SAME python that runs the script:
  python -m pip install playwright
  python -m playwright install chromium

Usage:
  python scripts/delete_reisift_podio_tags.py
  python scripts/delete_reisift_podio_tags.py --limit 5
  python scripts/delete_reisift_podio_tags.py --search podio --workers 2
  python scripts/delete_reisift_podio_tags.py --search podio --headless --workers 3

Coordination uses SQLite (.reisift-tag-coordinator.db). Default mode walks the
live paginated tag list in the folder (UI-first); use --catalog-probe for ID-range probing.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import Page, sync_playwright

BASE_URL = "https://app.reisift.io"
TAGS_PATH = "/tags/property"
TAGS_FOLDER_PATH_RE = re.compile(r"/tags/property/folder/([a-f0-9-]+)")
FOLDER_LINK_SELECTOR = 'a[href*="/tags/property/folder/"]'
DEFAULT_TAGS_FOLDER_NAME = "default"
SEARCH_PLACEHOLDER = "Search for tags..."
ROW_SELECTOR = '[class*="TableRowContainer"]'
_TAGS_FOLDER_NAME = DEFAULT_TAGS_FOLDER_NAME
_TAGS_FOLDER_URL = ""
# Records table: each property row is an <a> linking to /records/properties/{uuid}
RECORDS_ROW_LINK = 'a[class*="TableRowContainer"][href*="/records/properties/"]'
RECORDS_TABLE_CELL = '[class*="TableCellContainer"]'
PROPERTY_ADDRESS = '[class*="RecordsPropertiesAddressLine1"]'
# Address-like text in Records rows (empty owner column is OK).
STREET_IN_ADDRESS = re.compile(
    r"\b("
    r"Rd|Road|St|Street|Ave|Avenue|Dr|Drive|Ln|Lane|Blvd|Boulevard|"
    r"Place|Pl|Ct|Court|Way|Ter|Terrace|Cir|Circle|Loop|"
    r"Pkwy|Parkway|Hwy|Highway|Commack|Springtime"
    r")\b",
    re.I,
)
RECORDS_JUNK_LABEL = re.compile(
    r"^(dashboard|forgot|property records|owner records|records|never|\.\.\.)$",
    re.I,
)
MAX_DETACH_FAILURES = 5
# REISift tag-admin property counts lag 30–90s after removing a tag on a property page.
POST_DETACH_COUNT_WAIT_SEC = 90.0
POST_DETACH_POLL_INTERVAL_MS = 3000
PROPERTY_UUID_RE = re.compile(
    r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}",
    re.I,
)
PROPERTY_HREF_RE = re.compile(r"/records/properties/([a-f0-9-]+)", re.I)
TOOLTIP_SELECTORS = (
    '[role="tooltip"]',
    '[class*="Tooltip"]',
    '[class*="Popover"]',
    '[class*="HoverCard"]',
)
TAGS_TAB = '[class*="MiniTabsItem"]'
MINI_TABS = '[class*="MiniTabsContainer"]'
TAG_PILL_CONTAINER = '[class*="SelectedTagsContainer"]'
TAG_REMOVE = '[data-testid="TagInput__Remove"]'
TAG_PILL = '[class*="SelectedTag"]'


@dataclass
class DeleteStats:
    deleted: int = 0
    failed: int = 0
    skipped: int = 0
    detached: int = 0


PHASE_DETACH = "detach"
PHASE_DELETE = "delete"

# Pre-seeded catalog: workers probe podio-ID-{n}; missing tags → gone (no UI scrape).
DEFAULT_TAG_ID_PREFIX = "podio-ID-"
PODIO_ID_MIN = 0
PODIO_ID_MAX = 12000
UNKNOWN_PROPERTY_COUNT = -1


@dataclass
class PendingTag:
    """Legacy — kept for typing; phase 2 reads live tag rows instead."""
    name: str
    detached_at: float


# Max wait for all workers to finish phase 1 before aborting the run.
IDLE_STOP_SEC = 6.0
DETACH_BARRIER_TIMEOUT_SEC = 900.0

_log_prefix = threading.local()


def log(msg: str = "", *, end: str = "\n") -> None:
    prefix = getattr(_log_prefix, "value", "")
    line = f"{prefix} {msg}" if prefix else msg
    try:
        print(line, end=end, flush=True)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe = line.encode(encoding, errors="replace").decode(encoding, errors="replace")
        print(safe, end=end, flush=True)


class TagCoordinator:
    """SQLite-backed tag claims, pending queue, and delete lock (safe across threads/processes)."""

    def __init__(
        self,
        db_path: Path,
        *,
        limit: int | None,
        worker_count: int,
        reset: bool = True,
        tag_id_prefix: str = DEFAULT_TAG_ID_PREFIX,
        id_min: int = PODIO_ID_MIN,
        id_max: int = PODIO_ID_MAX,
        delete_first: bool = False,
    ) -> None:
        self.db_path = ensure_coord_db_path(db_path)
        self.limit = limit
        self.worker_count = worker_count
        self.tag_id_prefix = tag_id_prefix
        self.id_min = id_min
        self.id_max = id_max
        self.delete_first = delete_first
        self._idle_stop_sec = IDLE_STOP_SEC
        self._local = threading.local()
        if reset:
            self._reset_db()
            self.seed_catalog_id_range()
        else:
            self._init_schema()
            self.clear_stale_claims()
        self.prepare_run()

    def _connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.db_path), timeout=30.0, isolation_level=None)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            self._local.conn = conn
        return conn

    def _init_schema(self) -> None:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tag_states (
                tag_name TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                detached_at REAL,
                worker_id TEXT,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ui_delete_lock (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                holder TEXT,
                since REAL
            );
            CREATE TABLE IF NOT EXISTS worker_detach_done (
                worker_id TEXT PRIMARY KEY,
                done INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS worker_login_ready (
                worker_id TEXT PRIMARY KEY,
                ready INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS tag_detach_failures (
                tag_name TEXT PRIMARY KEY,
                failures INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS tag_catalog (
                tag_id INTEGER NOT NULL,
                tag_name TEXT PRIMARY KEY,
                property_count INTEGER NOT NULL DEFAULT -1,
                status TEXT NOT NULL DEFAULT 'pending',
                worker_id TEXT,
                scraped_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tag_catalog_id ON tag_catalog(tag_id);
            CREATE INDEX IF NOT EXISTS idx_tag_catalog_status ON tag_catalog(status);
            INSERT OR IGNORE INTO ui_delete_lock (id, holder, since) VALUES (1, NULL, NULL);
            """
        )
        conn.close()

    def _reset_db(self) -> None:
        for path in (self.db_path, Path(f"{self.db_path}-wal"), Path(f"{self.db_path}-shm")):
            if path.exists():
                path.unlink()
        self._init_schema()
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        for key, val in (
            ("deleted", "0"),
            ("failed", "0"),
            ("detached", "0"),
            ("stop", "0"),
            ("idle_since", ""),
            ("phase", PHASE_DETACH),
            ("catalog_ready", "0"),
            ("search_term", ""),
        ):
            conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (key, val))
        for i in range(1, self.worker_count + 1):
            wid = f"W{i}"
            conn.execute(
                "INSERT INTO worker_detach_done (worker_id, done) VALUES (?, 0)",
                (wid,),
            )
            conn.execute(
                "INSERT INTO worker_login_ready (worker_id, ready) VALUES (?, 0)",
                (wid,),
            )
        conn.execute("COMMIT")

    def seed_catalog_id_range(self) -> int:
        """Pre-load tag_name slots (property_count unknown until a worker probes the UI)."""
        conn = self._connect()
        now = time.monotonic()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM tag_catalog")
        rows: list[tuple[int, str, int, str, str, float, float]] = []
        for tag_id in range(self.id_min, self.id_max + 1):
            name = f"{self.tag_id_prefix}{tag_id}"
            rows.append(
                (tag_id, name, UNKNOWN_PROPERTY_COUNT, "pending", "", now, now)
            )
        conn.executemany(
            "INSERT INTO tag_catalog "
            "(tag_id, tag_name, property_count, status, worker_id, scraped_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self._set_meta("catalog_ready", "1", conn)
        self._set_meta("catalog_count", str(len(rows)), conn)
        self._set_meta("catalog_scraped_at", str(now), conn)
        self._set_meta("tag_id_prefix", self.tag_id_prefix, conn)
        self._set_meta("id_min", str(self.id_min), conn)
        self._set_meta("id_max", str(self.id_max), conn)
        conn.execute("COMMIT")
        return len(rows)

    def mark_catalog_gone(self, name: str) -> None:
        """Tag ID slot does not exist in REISift — skip permanently."""
        conn = self._connect()
        now = time.monotonic()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM tag_states WHERE tag_name=?", (name,))
        conn.execute(
            "UPDATE tag_catalog SET status='gone', property_count=0, worker_id='', "
            "updated_at=? WHERE tag_name=?",
            (now, name),
        )
        conn.execute("COMMIT")

    def catalog_all_done(self) -> bool:
        """True when every catalog slot is terminal (gone/deleted/abandoned)."""
        conn = self._connect()
        row = conn.execute(
            """
            SELECT 1 FROM tag_catalog
            WHERE status IN ('pending', 'detached', 'working', 'detaching', 'deleting')
            LIMIT 1
            """
        ).fetchone()
        return row is None

    def get_phase(self) -> str:
        return self._meta("phase") or PHASE_DETACH

    def set_phase(self, phase: str) -> None:
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        self._set_meta("phase", phase, conn)
        conn.execute("COMMIT")

    def skip_names(self, *, for_delete: bool = False) -> set[str]:
        conn = self._connect()
        if for_delete:
            rows = conn.execute(
                "SELECT tag_name FROM tag_states WHERE state IN ('in_flight', 'deleting')"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT tag_name FROM tag_states WHERE state IN "
                "('in_flight', 'detached', 'deleting', 'abandoned')"
            ).fetchall()
        return {r[0] for r in rows}

    def detached_count(self) -> int:
        return int(self._meta("detached") or 0)

    def _meta(self, key: str, conn: sqlite3.Connection | None = None) -> str:
        c = conn or self._connect()
        row = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else ""

    def _set_meta(self, key: str, value: str, conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def abandoned_names(self) -> set[str]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT tag_name FROM tag_states WHERE state='abandoned'"
        ).fetchall()
        abandoned = {r[0] for r in rows}
        rows = conn.execute(
            "SELECT tag_name FROM tag_catalog WHERE status='abandoned'"
        ).fetchall()
        abandoned.update(r[0] for r in rows)
        return abandoned

    def upsert_catalog_tag(self, name: str, property_count: int) -> None:
        """Merge one scraped tag row into the catalog."""
        conn = self._connect()
        now = time.monotonic()
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT status FROM tag_catalog WHERE tag_name=?", (name,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO tag_catalog "
                "(tag_name, property_count, status, worker_id, scraped_at, updated_at) "
                "VALUES (?, ?, 'pending', '', ?, ?)",
                (name, property_count, now, now),
            )
        else:
            status = row[0]
            if status in ("deleted", "gone"):
                status = "pending"
            elif status == "detached" and property_count > 0:
                status = "pending"
            elif status in ("abandoned", "detaching", "deleting"):
                pass  # keep status; refresh property_count from UI
            conn.execute(
                "UPDATE tag_catalog SET property_count=?, status=?, scraped_at=?, updated_at=? "
                "WHERE tag_name=?",
                (property_count, status, now, now, name),
            )
        conn.execute("COMMIT")

    def update_catalog_property_count(self, name: str, property_count: int) -> None:
        conn = self._connect()
        now = time.monotonic()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE tag_catalog SET property_count=?, updated_at=? WHERE tag_name=?",
            (property_count, now, name),
        )
        conn.execute("COMMIT")

    def set_catalog_status(self, name: str, status: str, *, worker_id: str = "") -> None:
        conn = self._connect()
        now = time.monotonic()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE tag_catalog SET status=?, worker_id=?, updated_at=? WHERE tag_name=?",
            (status, worker_id, now, name),
        )
        conn.execute("COMMIT")

    def catalog_has_properties_in_db(self) -> bool:
        """True if any live catalog row still has property_count > 0 (SQLite gate for delete phase)."""
        conn = self._connect()
        row = conn.execute(
            """
            SELECT 1 FROM tag_catalog
            WHERE property_count > 0
              AND status NOT IN ('abandoned', 'deleted', 'gone')
            LIMIT 1
            """
        ).fetchone()
        return row is not None

    def catalog_detach_pending(self) -> bool:
        """IDs still needing UI probe or property detach."""
        conn = self._connect()
        row = conn.execute(
            """
            SELECT 1 FROM tag_catalog c
            LEFT JOIN tag_states s ON s.tag_name = c.tag_name
            WHERE c.status NOT IN ('abandoned', 'deleted', 'gone', 'detached')
              AND (
                c.property_count > 0
                OR c.property_count = ?
              )
              AND (s.state IS NULL OR s.state NOT IN ('in_flight', 'abandoned'))
            LIMIT 1
            """,
            (UNKNOWN_PROPERTY_COUNT,),
        ).fetchone()
        return row is not None

    def catalog_delete_pending(self) -> bool:
        """Tags ready to delete — detached in DB with zero properties."""
        conn = self._connect()
        row = conn.execute(
            """
            SELECT 1 FROM tag_catalog c
            LEFT JOIN tag_states s ON s.tag_name = c.tag_name
            WHERE c.status = 'detached'
              AND c.property_count = 0
              AND (s.state IS NULL OR s.state NOT IN ('in_flight', 'abandoned'))
            LIMIT 1
            """
        ).fetchone()
        return row is not None

    def catalog_work_pending(self) -> bool:
        """Any catalog slot still needing probe, detach, or delete."""
        conn = self._connect()
        row = conn.execute(
            """
            SELECT 1 FROM tag_catalog c
            LEFT JOIN tag_states s ON s.tag_name = c.tag_name
            WHERE c.status NOT IN ('gone', 'deleted', 'abandoned')
              AND (s.state IS NULL OR s.state NOT IN ('in_flight', 'abandoned'))
            LIMIT 1
            """
        ).fetchone()
        return row is not None

    def prepare_run(self) -> None:
        """Reset per-run flags and ensure worker barrier rows exist."""
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        self._set_meta("stop", "0", conn)
        self._set_meta("idle_since", "", conn)
        if not self._meta("ui_next_page", conn):
            self._set_meta("ui_next_page", "1", conn)
        self.ensure_worker_slots(conn)
        conn.execute("COMMIT")

    def set_ui_total_pages(self, total: int) -> None:
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        prev = int(self._meta("ui_total_pages", conn) or 0)
        if total > prev:
            self._set_meta("ui_total_pages", str(total), conn)
        conn.execute("COMMIT")

    def ui_total_pages(self) -> int:
        return int(self._meta("ui_total_pages") or 0)

    def ui_next_page_number(self) -> int:
        return int(self._meta("ui_next_page") or 1)

    def claim_ui_page_number(self) -> int | None:
        """Hand out the next list page (1..N) for a worker to process."""
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        if self._meta("stop", conn) == "1":
            conn.execute("ROLLBACK")
            return None
        page_num = int(self._meta("ui_next_page", conn) or 1)
        total = int(self._meta("ui_total_pages", conn) or 0)
        if total > 0 and page_num > total:
            conn.execute("ROLLBACK")
            return None
        self._set_meta("ui_next_page", str(page_num + 1), conn)
        self._clear_idle(conn)
        conn.execute("COMMIT")
        return page_num

    def ui_pages_exhausted(self) -> bool:
        total = self.ui_total_pages()
        if total <= 0:
            return False
        return self.ui_next_page_number() > total and self.in_flight_count() == 0

    def reset_ui_page_queue(self) -> None:
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        self._set_meta("ui_next_page", "1", conn)
        for row in conn.execute("SELECT key FROM meta WHERE key LIKE 'worker_page_%'").fetchall():
            conn.execute("DELETE FROM meta WHERE key=?", (row[0],))
        conn.execute("COMMIT")

    def get_or_assign_worker_page(self, worker_id: str) -> int | None:
        """Keep a worker on one list page until every claimable tag there is handled."""
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        if self._meta("stop", conn) == "1":
            conn.execute("ROLLBACK")
            return None
        key = f"worker_page_{worker_id}"
        assigned = self._meta(key, conn)
        if assigned:
            conn.execute("COMMIT")
            return int(assigned)
        page_num = int(self._meta("ui_next_page", conn) or 1)
        total = int(self._meta("ui_total_pages", conn) or 0)
        if total > 0 and page_num > total:
            conn.execute("ROLLBACK")
            return None
        self._set_meta("ui_next_page", str(page_num + 1), conn)
        self._set_meta(key, str(page_num), conn)
        self._clear_idle(conn)
        conn.execute("COMMIT")
        return page_num

    def release_worker_page(self, worker_id: str) -> None:
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM meta WHERE key=?", (f"worker_page_{worker_id}",))
        conn.execute("COMMIT")

    def assigned_list_page(self, worker_id: str) -> int | None:
        raw = self._meta(f"worker_page_{worker_id}")
        return int(raw) if raw else None

    def catalog_stats_summary(self) -> dict[str, int]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT status, COUNT(*) FROM tag_catalog GROUP BY status"
        ).fetchall()
        counts = {status: int(n) for status, n in rows}
        counts["deleted_meta"] = int(self._meta("deleted", conn) or 0)
        counts["failed_meta"] = int(self._meta("failed", conn) or 0)
        return counts

    def ensure_worker_slots(self, conn: sqlite3.Connection | None = None) -> None:
        """Ensure W1…Wn exist in barrier tables (resume may use a different --workers count)."""
        own_conn = conn is None
        if own_conn:
            conn = self._connect()
            conn.execute("BEGIN IMMEDIATE")
        for i in range(1, self.worker_count + 1):
            wid = f"W{i}"
            conn.execute(
                "INSERT OR IGNORE INTO worker_login_ready (worker_id, ready) VALUES (?, 0)",
                (wid,),
            )
            conn.execute(
                "INSERT OR IGNORE INTO worker_detach_done (worker_id, done) VALUES (?, 0)",
                (wid,),
            )
            conn.execute("UPDATE worker_login_ready SET ready=0 WHERE worker_id=?", (wid,))
            conn.execute("UPDATE worker_detach_done SET done=0 WHERE worker_id=?", (wid,))
        if own_conn:
            conn.execute("COMMIT")

    def _tag_id_from_name(self, name: str) -> int | None:
        prefix = re.escape(self.tag_id_prefix)
        m = re.search(rf"^{prefix}(\d+)$", name)
        return int(m.group(1)) if m else None

    def ingest_ui_tag(self, name: str, property_count: int) -> str:
        """Upsert one live UI tag; revive false gone/abandoned marks. Returns action."""
        tag_id = self._tag_id_from_name(name)
        if tag_id is None:
            return "skip"
        conn = self._connect()
        now = time.monotonic()
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT status FROM tag_catalog WHERE tag_name=?", (name,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO tag_catalog "
                "(tag_id, tag_name, property_count, status, worker_id, scraped_at, updated_at) "
                "VALUES (?, ?, ?, 'pending', '', ?, ?)",
                (tag_id, name, property_count, now, now),
            )
            conn.execute("COMMIT")
            return "added"
        status = row[0]
        if status in ("gone", "abandoned"):
            conn.execute("DELETE FROM tag_states WHERE tag_name=?", (name,))
            conn.execute("DELETE FROM tag_detach_failures WHERE tag_name=?", (name,))
            conn.execute(
                "UPDATE tag_catalog SET status='pending', property_count=?, worker_id='', "
                "updated_at=? WHERE tag_name=?",
                (property_count, now, name),
            )
            conn.execute("COMMIT")
            return "revived"
        if status in ("pending", "detached", "working", "detaching", "deleting"):
            conn.execute(
                "UPDATE tag_catalog SET property_count=?, updated_at=? WHERE tag_name=?",
                (property_count, now, name),
            )
            conn.execute("COMMIT")
            return "updated"
        conn.execute("COMMIT")
        return "unchanged"

    def _set_in_flight(self, conn: sqlite3.Connection, name: str, worker_id: str) -> bool:
        """Mark tag in_flight; reclaim rows left in 'detached' state from prior runs."""
        now = time.monotonic()
        conn.execute(
            """
            INSERT INTO tag_states (tag_name, state, detached_at, worker_id, updated_at)
            VALUES (?, 'in_flight', NULL, ?, ?)
            ON CONFLICT(tag_name) DO UPDATE SET
                state='in_flight',
                worker_id=excluded.worker_id,
                updated_at=excluded.updated_at,
                detached_at=NULL
            WHERE tag_states.state NOT IN ('in_flight', 'deleting', 'abandoned')
            """,
            (name, worker_id, now),
        )
        return conn.execute("SELECT changes()").fetchone()[0] > 0

    def clear_stale_claims(self) -> None:
        """On --resume, release tags left in_flight by a crashed prior run."""
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM tag_states WHERE state IN ('in_flight', 'detached', 'deleting')")
        conn.execute("DELETE FROM tag_detach_failures")
        conn.execute("DELETE FROM tag_states WHERE state='abandoned'")
        conn.execute(
            """
            UPDATE tag_catalog SET
                worker_id='',
                status=CASE
                    WHEN status = 'abandoned' THEN 'pending'
                    WHEN status IN ('working', 'detaching', 'deleting') AND property_count = 0 THEN 'detached'
                    WHEN status IN ('working', 'detaching', 'deleting') THEN 'pending'
                    ELSE status
                END
            WHERE status IN ('working', 'detaching', 'deleting', 'abandoned')
            """
        )
        conn.execute("COMMIT")

    def claim_next_work(self, worker_id: str) -> str | None:
        """Claim next tag needing probe, detach, and/or delete (single-pass loop)."""
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        if self._meta("stop", conn) == "1":
            conn.execute("ROLLBACK")
            return None
        row = conn.execute(
            """
            SELECT c.tag_name
            FROM tag_catalog c
            LEFT JOIN tag_states s ON s.tag_name = c.tag_name
            WHERE c.status NOT IN ('gone', 'deleted', 'abandoned')
              AND (s.state IS NULL OR s.state NOT IN ('in_flight', 'deleting', 'abandoned'))
            ORDER BY
              CASE
                WHEN c.status = 'detached' AND c.property_count <= 0 THEN 0
                WHEN c.status = 'pending' AND c.property_count = 0 THEN 1
                WHEN c.status = 'pending' AND c.property_count = ? THEN 2
                WHEN c.status = 'pending' AND c.property_count > 0 THEN 3
                ELSE 4
              END,
              c.tag_id ASC
            LIMIT 1
            """,
            (UNKNOWN_PROPERTY_COUNT,),
        ).fetchone()
        if not row:
            conn.execute("ROLLBACK")
            return None
        name = row[0]
        now = time.monotonic()
        if not self._set_in_flight(conn, name, worker_id):
            conn.execute("ROLLBACK")
            return None
        conn.execute(
            "UPDATE tag_catalog SET status='working', worker_id=?, updated_at=? "
            "WHERE tag_name=?",
            (worker_id, now, name),
        )
        self._clear_idle(conn)
        conn.execute("COMMIT")
        return name

    def try_claim_by_name(self, name: str, worker_id: str) -> bool:
        """Claim a tag discovered on the UI list (revives false gone/abandoned)."""
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        if self._meta("stop", conn) == "1":
            conn.execute("ROLLBACK")
            return False
        row = conn.execute(
            "SELECT status FROM tag_catalog WHERE tag_name=?", (name,)
        ).fetchone()
        now = time.monotonic()
        if row is None:
            tag_id = self._tag_id_from_name(name)
            if tag_id is None:
                conn.execute("ROLLBACK")
                return False
            conn.execute(
                "INSERT INTO tag_catalog "
                "(tag_id, tag_name, property_count, status, worker_id, scraped_at, updated_at) "
                "VALUES (?, ?, 0, 'pending', '', ?, ?)",
                (tag_id, name, now, now),
            )
        elif row[0] in ("gone", "abandoned"):
            conn.execute("DELETE FROM tag_states WHERE tag_name=?", (name,))
            conn.execute("DELETE FROM tag_detach_failures WHERE tag_name=?", (name,))
            conn.execute(
                "UPDATE tag_catalog SET status='pending', property_count=0, worker_id='', "
                "updated_at=? WHERE tag_name=?",
                (now, name),
            )
        elif row[0] in ("deleted", "working", "detaching", "deleting"):
            conn.execute("ROLLBACK")
            return False
        if conn.execute(
            "SELECT 1 FROM tag_states WHERE tag_name=? AND state IN ('in_flight', 'deleting', 'abandoned')",
            (name,),
        ).fetchone():
            conn.execute("ROLLBACK")
            return False
        if not self._set_in_flight(conn, name, worker_id):
            conn.execute("ROLLBACK")
            return False
        conn.execute(
            "UPDATE tag_catalog SET status='working', worker_id=?, updated_at=? "
            "WHERE tag_name=?",
            (worker_id, now, name),
        )
        self._clear_idle(conn)
        conn.execute("COMMIT")
        return True

    def claim_next_detach(self, worker_id: str) -> str | None:
        """Claim next ID that still needs probe or detach (phase 1 only)."""
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        if self._meta("stop", conn) == "1" or self._meta("phase", conn) != PHASE_DETACH:
            conn.execute("ROLLBACK")
            return None
        row = conn.execute(
            """
            SELECT c.tag_name
            FROM tag_catalog c
            LEFT JOIN tag_states s ON s.tag_name = c.tag_name
            WHERE c.status NOT IN ('abandoned', 'deleted', 'gone', 'detached')
              AND (
                c.property_count > 0
                OR c.property_count = ?
              )
              AND (s.state IS NULL OR s.state NOT IN ('in_flight', 'abandoned'))
            ORDER BY c.tag_id ASC
            LIMIT 1
            """,
            (UNKNOWN_PROPERTY_COUNT,),
        ).fetchone()
        if not row:
            conn.execute("ROLLBACK")
            return None
        name = row[0]
        now = time.monotonic()
        if not self._set_in_flight(conn, name, worker_id):
            conn.execute("ROLLBACK")
            return None
        conn.execute(
            "UPDATE tag_catalog SET status='detaching', worker_id=?, updated_at=? "
            "WHERE tag_name=?",
            (worker_id, now, name),
        )
        conn.execute("UPDATE worker_detach_done SET done=0 WHERE worker_id=?", (worker_id,))
        self._clear_idle(conn)
        conn.execute("COMMIT")
        return name

    def claim_next_delete(self, worker_id: str) -> str | None:
        """Claim next tag cleared in DB for deletion (phase 2 only)."""
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        if self._meta("stop", conn) == "1" or self._meta("phase", conn) != PHASE_DELETE:
            conn.execute("ROLLBACK")
            return None
        deleted = int(self._meta("deleted", conn) or 0)
        if self.limit is not None and deleted >= self.limit:
            conn.execute("ROLLBACK")
            return None
        row = conn.execute(
            """
            SELECT c.tag_name
            FROM tag_catalog c
            LEFT JOIN tag_states s ON s.tag_name = c.tag_name
            WHERE c.status = 'detached'
              AND c.property_count = 0
              AND (s.state IS NULL OR s.state NOT IN ('in_flight', 'abandoned'))
            ORDER BY c.tag_id ASC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            conn.execute("ROLLBACK")
            return None
        name = row[0]
        now = time.monotonic()
        if not self._set_in_flight(conn, name, worker_id):
            conn.execute("ROLLBACK")
            return None
        conn.execute(
            "UPDATE tag_catalog SET status='deleting', worker_id=?, updated_at=? "
            "WHERE tag_name=?",
            (worker_id, now, name),
        )
        self._clear_idle(conn)
        conn.execute("COMMIT")
        return name

    def catalog_tag_pending(self) -> bool:
        return self.catalog_detach_pending() or self.catalog_delete_pending()

    def catalog_active_count(self) -> int:
        conn = self._connect()
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM tag_catalog WHERE status NOT IN ('deleted', 'gone')"
            ).fetchone()[0]
        )

    def reset_detach_barrier(self) -> None:
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE worker_detach_done SET done=0")
        conn.execute("COMMIT")

    def worker_detach_signaled(self, worker_id: str) -> bool:
        conn = self._connect()
        row = conn.execute(
            "SELECT done FROM worker_detach_done WHERE worker_id=?", (worker_id,)
        ).fetchone()
        return bool(row and row[0] == 1)

    def signal_detach_idle(self, worker_id: str) -> None:
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE worker_detach_done SET done=1 WHERE worker_id=?", (worker_id,)
        )
        conn.execute("COMMIT")

    def _maybe_advance_to_delete_phase(self, worker_id: str = "") -> bool:
        """Advance when all workers idle and SQLite shows no tags with properties."""
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        if self._meta("phase", conn) != PHASE_DETACH:
            conn.execute("ROLLBACK")
            return self.get_phase() == PHASE_DELETE
        done = conn.execute(
            "SELECT COUNT(*) FROM worker_detach_done WHERE done=1"
        ).fetchone()[0]
        in_flight = conn.execute(
            "SELECT COUNT(*) FROM tag_states WHERE state='in_flight'"
        ).fetchone()[0]
        if done < self.worker_count or in_flight > 0:
            conn.execute("ROLLBACK")
            return False
        conn.execute("COMMIT")

        if self.catalog_detach_pending() or self.catalog_has_properties_in_db():
            if worker_id == "W1":
                self.reset_detach_barrier()
                log("Phase 1: catalog still has tags with properties — continuing detach…")
            return False

        if worker_id == "W1":
            log("Phase 2 starting — catalog shows zero properties on all tags; deleting…")

        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        self._set_meta("phase", PHASE_DELETE, conn)
        self._set_meta("idle_since", "", conn)
        conn.execute("COMMIT")
        return True

    def wait_for_delete_phase(self, worker_id: str) -> bool:
        """Block until phase DELETE (SQLite gate, no UI scrape)."""
        self.signal_detach_idle(worker_id)
        deadline = time.monotonic() + DETACH_BARRIER_TIMEOUT_SEC
        while self.get_phase() != PHASE_DELETE:
            if self._meta("stop") == "1":
                return False
            if time.monotonic() >= deadline:
                if worker_id == "W1":
                    log("Detach barrier timeout — stopping run.")
                self.signal_stop()
                return False
            if not self.worker_detach_signaled(worker_id):
                return False
            if worker_id == "W1":
                if self._maybe_advance_to_delete_phase(worker_id):
                    break
            time.sleep(0.4)
        return self.get_phase() == PHASE_DELETE

    def mark_needs_detach(self, name: str, property_count: int) -> None:
        """UI still shows properties during delete — send tag back to phase 1 queue."""
        conn = self._connect()
        now = time.monotonic()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM tag_states WHERE tag_name=?", (name,))
        conn.execute(
            "UPDATE tag_catalog SET status='pending', property_count=?, worker_id='', "
            "updated_at=? WHERE tag_name=?",
            (property_count, now, name),
        )
        conn.execute("COMMIT")

    def mark_catalog_scraped(self, search_term: str, count: int) -> None:
        conn = self._connect()
        now = time.monotonic()
        conn.execute("BEGIN IMMEDIATE")
        self._set_meta("catalog_ready", "1", conn)
        self._set_meta("search_term", search_term, conn)
        self._set_meta("catalog_count", str(count), conn)
        self._set_meta("catalog_scraped_at", str(now), conn)
        conn.execute("COMMIT")

    def wait_for_catalog(self, worker_id: str, *, timeout: float = 600.0) -> bool:
        if self._meta("catalog_ready") == "1":
            return True
        deadline = time.monotonic() + timeout
        while self._meta("catalog_ready") != "1":
            if self._meta("stop") == "1":
                return False
            if time.monotonic() >= deadline:
                if worker_id == "W1":
                    log("Catalog scrape timeout — stopping run.")
                self.signal_stop()
                return False
            time.sleep(0.35)
        return True

    def _clear_idle(self, conn: sqlite3.Connection) -> None:
        self._set_meta("idle_since", "", conn)

    def release_claim(self, name: str) -> None:
        conn = self._connect()
        now = time.monotonic()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "DELETE FROM tag_states WHERE tag_name=? AND state IN ('in_flight', 'deleting')",
            (name,),
        )
        conn.execute(
            """
            UPDATE tag_catalog SET
                worker_id='',
                updated_at=?,
                status=CASE
                    WHEN status IN ('working', 'detaching', 'deleting') AND property_count > 0 THEN 'pending'
                    WHEN status IN ('working', 'detaching', 'deleting')
                         AND property_count >= 0 THEN 'detached'
                    WHEN status IN ('working', 'detaching', 'deleting') THEN 'pending'
                    ELSE status
                END
            WHERE tag_name=?
            """,
            (now, name),
        )
        conn.execute("COMMIT")

    def clear_detach_failures(self, name: str) -> None:
        conn = self._connect()
        conn.execute("DELETE FROM tag_detach_failures WHERE tag_name=?", (name,))

    def note_detach_failure(self, name: str) -> bool:
        """Increment per-tag failure count; return True if tag is now abandoned."""
        conn = self._connect()
        now = time.monotonic()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO tag_detach_failures (tag_name, failures) VALUES (?, 1) "
            "ON CONFLICT(tag_name) DO UPDATE SET failures = failures + 1",
            (name,),
        )
        row = conn.execute(
            "SELECT failures FROM tag_detach_failures WHERE tag_name=?", (name,)
        ).fetchone()
        failures = int(row[0]) if row else 1
        abandoned = failures >= MAX_DETACH_FAILURES
        if abandoned:
            conn.execute(
                "INSERT INTO tag_states (tag_name, state, detached_at, worker_id, updated_at) "
                "VALUES (?, 'abandoned', NULL, '', ?) "
                "ON CONFLICT(tag_name) DO UPDATE SET state='abandoned', updated_at=excluded.updated_at",
                (name, now),
            )
            conn.execute(
                "UPDATE tag_catalog SET status='abandoned', worker_id='', updated_at=? "
                "WHERE tag_name=?",
                (now, name),
            )
        conn.execute("COMMIT")
        return abandoned

    def mark_detached(self, name: str) -> None:
        """Tag cleared in admin UI — keep in_flight until delete finishes (same worker)."""
        conn = self._connect()
        now = time.monotonic()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM tag_detach_failures WHERE tag_name=?", (name,))
        conn.execute(
            "UPDATE tag_catalog SET status='detached', property_count=0, "
            "updated_at=? WHERE tag_name=?",
            (now, name),
        )
        n = int(self._meta("detached", conn) or 0) + 1
        self._set_meta("detached", str(n), conn)
        self._clear_idle(conn)
        conn.execute("COMMIT")

    def finish_detach(self, name: str) -> None:
        """Phase 1 done for one tag — release claim and move to the next tag immediately."""
        conn = self._connect()
        now = time.monotonic()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM tag_states WHERE tag_name=?", (name,))
        conn.execute("DELETE FROM tag_detach_failures WHERE tag_name=?", (name,))
        conn.execute(
            "UPDATE tag_catalog SET status='detached', worker_id='', updated_at=? "
            "WHERE tag_name=?",
            (now, name),
        )
        n = int(self._meta("detached", conn) or 0) + 1
        self._set_meta("detached", str(n), conn)
        self._clear_idle(conn)
        conn.execute("COMMIT")

    def catalog_status(self, name: str) -> str:
        conn = self._connect()
        row = conn.execute(
            "SELECT status FROM tag_catalog WHERE tag_name=?", (name,)
        ).fetchone()
        return row[0] if row else ""

    def begin_delete(self, name: str, worker_id: str) -> None:
        """Mark delete in progress so UI sweep and other workers skip this tag."""
        conn = self._connect()
        now = time.monotonic()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO tag_states (tag_name, state, detached_at, worker_id, updated_at)
            VALUES (?, 'deleting', NULL, ?, ?)
            ON CONFLICT(tag_name) DO UPDATE SET
                state='deleting',
                worker_id=excluded.worker_id,
                updated_at=excluded.updated_at
            """,
            (name, worker_id, now),
        )
        conn.execute(
            "UPDATE tag_catalog SET status='deleting', worker_id=?, updated_at=? "
            "WHERE tag_name=?",
            (worker_id, now, name),
        )
        conn.execute("COMMIT")

    def finish_delete(self, name: str, *, success: bool) -> None:
        conn = self._connect()
        now = time.monotonic()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM tag_states WHERE tag_name=?", (name,))
        if success:
            conn.execute(
                "UPDATE tag_catalog SET status='deleted', worker_id='', updated_at=? "
                "WHERE tag_name=?",
                (now, name),
            )
            deleted = int(self._meta("deleted", conn) or 0) + 1
            self._set_meta("deleted", str(deleted), conn)
            self._clear_idle(conn)
        else:
            conn.execute(
                "UPDATE tag_catalog SET status='detached', worker_id='', updated_at=? "
                "WHERE tag_name=?",
                (now, name),
            )
            failed = int(self._meta("failed", conn) or 0) + 1
            self._set_meta("failed", str(failed), conn)
        conn.execute("COMMIT")

    def signal_login_ready(self, worker_id: str) -> None:
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT OR IGNORE INTO worker_login_ready (worker_id, ready) VALUES (?, 0)",
            (worker_id,),
        )
        conn.execute(
            "UPDATE worker_login_ready SET ready=1 WHERE worker_id=?", (worker_id,)
        )
        conn.execute("COMMIT")

    def login_ready_count(self) -> int:
        conn = self._connect()
        ids = [f"W{i}" for i in range(1, self.worker_count + 1)]
        placeholders = ",".join("?" * len(ids))
        return int(
            conn.execute(
                f"SELECT COUNT(*) FROM worker_login_ready "
                f"WHERE worker_id IN ({placeholders}) AND ready=1",
                ids,
            ).fetchone()[0]
        )

    def wait_for_all_logins(self, worker_id: str, *, timeout: float = 300.0) -> bool:
        """Block until every worker has logged in and opened the tags page."""
        self.signal_login_ready(worker_id)
        log(f"Logged in and on tags page ({self.login_ready_count()}/{self.worker_count} ready)")
        deadline = time.monotonic() + timeout
        last_count = -1
        while self.login_ready_count() < self.worker_count:
            if self._meta("stop") == "1":
                return False
            if time.monotonic() >= deadline:
                log(
                    f"Login barrier timeout — only {self.login_ready_count()}/"
                    f"{self.worker_count} workers ready"
                )
                self.signal_stop()
                return False
            count = self.login_ready_count()
            if count != last_count and worker_id == "W1":
                log(f"Waiting for all workers… ({count}/{self.worker_count} ready)")
                last_count = count
            time.sleep(0.35)
        if worker_id == "W1":
            log(f"All {self.worker_count} workers logged in — starting work.")
        return True

    def note_work(self) -> None:
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        self._clear_idle(conn)
        conn.execute("COMMIT")

    def note_no_work(self) -> None:
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        busy = conn.execute(
            "SELECT COUNT(*) FROM tag_states WHERE state IN ('in_flight', 'deleting')"
        ).fetchone()[0]
        if busy == 0 and not self._meta("idle_since", conn):
            self._set_meta("idle_since", str(time.monotonic()), conn)
        conn.execute("COMMIT")

    def in_flight_count(self) -> int:
        conn = self._connect()
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM tag_states WHERE state IN ('in_flight', 'deleting')"
            ).fetchone()[0]
        )

    def should_continue_detach(self) -> bool:
        if self.get_phase() != PHASE_DETACH:
            return False
        return self._should_continue_common()

    def should_continue_delete(self) -> bool:
        if self.get_phase() != PHASE_DELETE:
            return False
        deleted = int(self._meta("deleted") or 0)
        if self.limit is not None and deleted >= self.limit:
            return False
        return self._should_continue_common()

    def should_continue_catalog(self) -> bool:
        if self.is_stopped():
            return False
        deleted = int(self._meta("deleted") or 0)
        if self.limit is not None and deleted >= self.limit:
            return False
        return self._should_continue_common()

    def should_continue_work(self) -> bool:
        if self.is_stopped():
            return False
        deleted = int(self._meta("deleted") or 0)
        if self.limit is not None and deleted >= self.limit:
            return False
        return self._should_continue_common()

    def _should_continue_common(self) -> bool:
        conn = self._connect()
        if self._meta("stop", conn) == "1":
            return False
        busy = conn.execute(
            "SELECT COUNT(*) FROM tag_states WHERE state IN ('in_flight', 'deleting')"
        ).fetchone()[0]
        if busy > 0:
            return True
        idle_raw = self._meta("idle_since", conn)
        if not idle_raw:
            return True
        return (time.monotonic() - float(idle_raw)) < self._idle_stop_sec

    def stats(self) -> DeleteStats:
        conn = self._connect()
        return DeleteStats(
            deleted=int(self._meta("deleted", conn) or 0),
            failed=int(self._meta("failed", conn) or 0),
            detached=int(self._meta("detached", conn) or 0),
        )

    def record_failed(self) -> None:
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        failed = int(self._meta("failed", conn) or 0) + 1
        self._set_meta("failed", str(failed), conn)
        conn.execute("COMMIT")

    def signal_stop(self) -> None:
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        self._set_meta("stop", "1", conn)
        conn.execute("COMMIT")

    def is_stopped(self) -> bool:
        return self._meta("stop") == "1"

    @contextmanager
    def ui_delete_lock(self, holder: str, timeout: float = 180.0):
        """Only one worker may drive the delete modal at a time (SQLite mutex)."""
        deadline = time.monotonic() + timeout
        conn = self._connect()
        acquired = False
        try:
            while time.monotonic() < deadline:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT holder FROM ui_delete_lock WHERE id=1").fetchone()
                if row[0] is None or row[0] == holder:
                    conn.execute(
                        "UPDATE ui_delete_lock SET holder=?, since=? WHERE id=1",
                        (holder, time.monotonic()),
                    )
                    conn.execute("COMMIT")
                    acquired = True
                    break
                conn.execute("ROLLBACK")
                time.sleep(0.08)
            if not acquired:
                raise PlaywrightTimeout(f"ui delete lock not acquired for {holder}")
            yield
        finally:
            if acquired:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "UPDATE ui_delete_lock SET holder=NULL, since=NULL WHERE id=1 AND holder=?",
                    (holder,),
                )
                conn.execute("COMMIT")


def default_coord_db_path() -> Path:
    return Path(__file__).resolve().parent.parent / ".reisift-tag-coordinator.db"


def ensure_coord_db_path(db_path: Path) -> Path:
    """Resolve path and create parent directory so SQLite can open the file."""
    resolved = db_path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def dismiss_popups(page: Page) -> None:
    """Close notification / promo overlays that block the tags table."""
    for locator in (
        page.get_by_role("button", name=re.compile(r"No,\s*thanks", re.I)),
        page.get_by_text(re.compile(r"NO,\s*THANKS", re.I)),
        page.get_by_text(re.compile(r"Not now", re.I)),
        page.get_by_text(re.compile(r"Maybe later", re.I)),
    ):
        if locator.count() > 0 and locator.first.is_visible():
            locator.first.click()
            page.wait_for_timeout(400)
            log("Dismissed notification popup.")
            return


def close_modal_overlays(page: Page) -> None:
    """Close stray confirm/prompt modals that block clicks on the tags table."""
    overlay = page.locator('[class*="ModalOverlay"]')
    if overlay.count() == 0 or not overlay.first.is_visible():
        return
    for pattern in (
        re.compile(r"cancel", re.I),
        re.compile(r"^close$", re.I),
        re.compile(r"^no$", re.I),
        re.compile(r"not now", re.I),
    ):
        btn = page.get_by_role("button", name=pattern)
        if btn.count() > 0 and btn.first.is_visible():
            btn.first.click()
            page.wait_for_timeout(400)
            return
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)


def prepare_tags_ui(page: Page) -> None:
    dismiss_popups(page)
    close_modal_overlays(page)


def prompt_credentials(email: str | None, password: str | None) -> tuple[str, str]:
    if not email:
        email = os.environ.get("REISIFT_EMAIL", "").strip()
    if not password:
        password = os.environ.get("REISIFT_PASSWORD", "")
    if not email:
        email = input("REISift email: ").strip()
    if not password:
        password = getpass.getpass("REISift password: ")
    if not email or not password:
        raise SystemExit("Email and password are required.")
    return email, password


def on_login_page(page: Page) -> bool:
    """Detect login screen by UI, not URL (DataSift may redirect off /login)."""
    if page.locator('input[type="password"]').count() == 0:
        return False
    return (
        page.get_by_role("button", name=re.compile(r"sign in", re.I)).count() > 0
        or page.get_by_text(re.compile(r"Welcome back", re.I)).count() > 0
        or page.get_by_text(re.compile(r"terms of use", re.I)).count() > 0
    )


def is_authenticated(page: Page) -> bool:
    return page.get_by_role("link", name=re.compile(r"^Tags$", re.I)).count() > 0


def _click_custom_checkbox(page: Page, locator, label: str) -> None:
    box = locator.first
    box.wait_for(state="visible", timeout=10_000)
    box.click()
    page.wait_for_timeout(250)
    log(f"Checked: {label}")


def check_login_boxes(page: Page) -> None:
    """Click DataSift custom checkboxes once — re-clicking toggles them off."""
    sign_in = page.get_by_role("button", name="Sign In")
    if sign_in.count() > 0 and sign_in.first.is_enabled():
        log("SIGN IN already enabled.")
        return

    remember = page.locator('[data-testid="Checkbox"]').first
    terms = page.locator('[class*="TermsWrapper"] [data-testid="Checkbox"]')

    if remember.count() > 0:
        _click_custom_checkbox(page, remember, "remember me")
    if terms.count() > 0:
        _click_custom_checkbox(page, terms, "terms of use")
    else:
        raise SystemExit('Could not find terms checkbox — expected [class*="TermsWrapper"] [data-testid="Checkbox"]')

    for _ in range(25):
        if sign_in.first.is_enabled():
            log("SIGN IN enabled.")
            return
        page.wait_for_timeout(200)

    raise SystemExit("SIGN IN still disabled — terms checkbox may not have registered.")


def login(page: Page, email: str, password: str) -> None:
    log("Opening login page…")
    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    if is_authenticated(page) and not on_login_page(page):
        log("Already logged in.")
        return

    if not on_login_page(page):
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

    if is_authenticated(page) and not on_login_page(page):
        log("Already logged in.")
        return

    if not on_login_page(page):
        raise SystemExit("Could not find DataSift login form — complete login manually in the browser window.")

    log("Login form detected — signing in…")

    email_input = page.locator(
        'input[type="email"], input[name="email"], input[placeholder*="example" i], '
        'input[placeholder*="email" i], input[autocomplete="username"]'
    ).first
    password_input = page.locator('input[type="password"]').first

    email_input.wait_for(state="visible", timeout=20_000)
    email_input.fill(email)
    password_input.fill(password)

    check_login_boxes(page)

    sign_in = page.get_by_role("button", name="Sign In")
    log("Clicking SIGN IN…")
    sign_in.first.click()

    try:
        page.wait_for_function(
            "() => !document.querySelector('input[type=\"password\"]') || "
            "document.querySelector('a[href*=\"/tags\"]')",
            timeout=30_000,
        )
        page.wait_for_timeout(1500)
    except PlaywrightTimeout:
        if on_login_page(page):
            raise SystemExit("Login failed — check email/password or terms checkbox.")
    if not is_authenticated(page):
        raise SystemExit("Login may have failed — Tags menu not visible.")
    dismiss_popups(page)
    log("Login OK.")


def configure_tags_folder(*, name: str = DEFAULT_TAGS_FOLDER_NAME, url: str = "") -> None:
    global _TAGS_FOLDER_NAME, _TAGS_FOLDER_URL
    _TAGS_FOLDER_NAME = name.strip() or DEFAULT_TAGS_FOLDER_NAME
    _TAGS_FOLDER_URL = url.strip()


def is_tags_folder_view(page: Page) -> bool:
    return bool(TAGS_FOLDER_PATH_RE.search(page.url))


def is_tags_root_view(page: Page) -> bool:
    return "/tags/property" in page.url and not is_tags_folder_view(page)


def current_tag_folder_url(page: Page) -> str | None:
    if not is_tags_folder_view(page):
        return None
    return page.url.split("?")[0]


def go_to_tags_root(page: Page) -> None:
    if is_tags_root_view(page):
        return
    folders_link = page.get_by_role("link", name=re.compile(r"Tags Folders", re.I))
    if folders_link.count() > 0:
        folders_link.first.click()
        page.wait_for_timeout(1500)
        if is_tags_root_view(page):
            return
    page.goto(f"{BASE_URL}{TAGS_PATH}", wait_until="domcontentloaded")
    page.wait_for_timeout(1500)


def collect_tag_folder_urls(page: Page) -> list[str]:
    """Folder URLs listed on the property-tags root page."""
    urls: list[str] = []
    seen: set[str] = set()
    for i in range(page.locator(FOLDER_LINK_SELECTOR).count()):
        href = page.locator(FOLDER_LINK_SELECTOR).nth(i).get_attribute("href")
        if not href:
            continue
        url = href if href.startswith("http") else f"{BASE_URL}{href}"
        url = url.split("?")[0]
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def discover_folder_url_by_click(page: Page, folder_name: str) -> str | None:
    """REISift often renders folders as clickable rows, not <a href> links."""
    go_to_tags_root(page)
    candidates = (
        page.locator(FOLDER_LINK_SELECTOR).filter(
            has_text=re.compile(rf"^{re.escape(folder_name)}$", re.I)
        ),
        page.locator(ROW_SELECTOR).filter(
            has_text=re.compile(rf"\b{re.escape(folder_name)}\b", re.I)
        ),
        page.get_by_text(folder_name, exact=True),
        page.locator(f'text="{folder_name}"'),
    )
    for loc in candidates:
        if loc.count() == 0:
            continue
        try:
            loc.first.click()
            page.wait_for_url(TAGS_FOLDER_PATH_RE, timeout=15_000)
            page.wait_for_timeout(1000)
            return current_tag_folder_url(page)
        except Exception:
            continue
    return None


def enter_tags_folder(
    page: Page,
    *,
    folder_name: str | None = None,
    folder_url: str | None = None,
) -> bool:
    """Open one tag folder. REISift nests tags under folders, not on /tags/property root."""
    global _TAGS_FOLDER_URL

    if folder_url:
        page.goto(folder_url.split("?")[0], wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        if is_tags_folder_view(page):
            _TAGS_FOLDER_URL = current_tag_folder_url(page) or folder_url
            return True
        return False

    if is_tags_folder_view(page):
        return True

    name = folder_name or _TAGS_FOLDER_NAME
    discovered = discover_folder_url_by_click(page, name)
    if discovered:
        _TAGS_FOLDER_URL = discovered
        return True

    folders = collect_tag_folder_urls(page)
    if len(folders) == 1:
        page.goto(folders[0], wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        if is_tags_folder_view(page):
            _TAGS_FOLDER_URL = folders[0]
            return True
    return False


def ensure_in_tags_folder(page: Page) -> None:
    if is_tags_folder_view(page):
        return
    if _TAGS_FOLDER_URL:
        if enter_tags_folder(page, folder_url=_TAGS_FOLDER_URL):
            log(f"Opened tag folder {_TAGS_FOLDER_URL}")
            return
    if is_tags_root_view(page) or "/tags/" in page.url:
        go_to_tags_root(page)
    if enter_tags_folder(page, folder_name=_TAGS_FOLDER_NAME):
        log(f'Opened tag folder "{_TAGS_FOLDER_NAME}"')
        return
    folders = collect_tag_folder_urls(page)
    if folders:
        page.goto(folders[0], wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        log(f"Opened tag folder {folders[0]}")
        return
    log("WARNING: could not open a tag folder — podio tags may be nested under folders")


def list_all_tag_folder_urls(page: Page) -> list[str]:
    if _TAGS_FOLDER_URL:
        return [_TAGS_FOLDER_URL.split("?")[0]]
    if is_tags_folder_view(page):
        cur = current_tag_folder_url(page)
        if cur:
            return [cur]
    saved = page.url
    go_to_tags_root(page)
    folders = collect_tag_folder_urls(page)
    if folders:
        return folders
    discovered = discover_folder_url_by_click(page, _TAGS_FOLDER_NAME)
    if discovered:
        return [discovered]
    if TAGS_FOLDER_PATH_RE.search(saved):
        return [saved.split("?")[0]]
    return []


def open_property_tags(page: Page) -> None:
    log("Opening Property Tags…")
    if not is_authenticated(page):
        raise SystemExit("Not logged in — cannot open Tags page.")

    page.goto(f"{BASE_URL}{TAGS_PATH}", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    search = page.locator(f'input[placeholder="{SEARCH_PLACEHOLDER}"]')
    if search.count() == 0:
        page.get_by_role("link", name=re.compile(r"Property Tag", re.I)).click()
        page.wait_for_timeout(1500)

    search.wait_for(state="visible", timeout=30_000)
    dismiss_popups(page)
    ensure_in_tags_folder(page)


def apply_search(page: Page, term: str, *, quiet: bool = False) -> None:
    dismiss_popups(page)
    search = page.locator(f'input[placeholder="{SEARCH_PLACEHOLDER}"]')
    search.click()
    search.fill(term)
    page.wait_for_timeout(1200)
    if not quiet:
        log(f'Search applied: "{term}"')


def tags_list_ready(page: Page, search_term: str) -> bool:
    if "/tags/" not in page.url or not is_tags_folder_view(page):
        return False
    search = page.locator(f'input[placeholder="{SEARCH_PLACEHOLDER}"]')
    if search.count() == 0:
        return False
    try:
        return search.input_value().strip().lower() == search_term.lower()
    except Exception:
        return False


def list_page_spinbutton(page: Page):
    for spin in (
        page.locator('[class*="Pagination"] input[type="number"]'),
        page.locator('[class*="Pagination"] [role="spinbutton"]'),
        page.get_by_role("spinbutton"),
    ):
        if spin.count() > 0:
            return spin.first
    return None


def set_list_page_number(page: Page, page_num: int) -> bool:
    """Jump to page N via the pagination spinbutton (search filter must already be active)."""
    page_num = max(1, page_num)
    cur, _ = list_pagination_info(page)
    if cur == page_num:
        return True
    spin = list_page_spinbutton(page)
    if spin is None:
        return False
    try:
        spin.click(timeout=5000)
        spin.fill(str(page_num))
        spin.press("Enter")
        page.wait_for_timeout(1200)
        dismiss_popups(page)
        after, _ = list_pagination_info(page)
        return after == page_num
    except Exception:
        return False


def refresh_tags_list(
    page: Page,
    search_term: str,
    *,
    force: bool = False,
    page_num: int | None = None,
) -> None:
    """Open tags + search; optionally land on a specific list page."""
    cur, _ = list_pagination_info(page)
    if (
        not force
        and tags_list_ready(page, search_term)
        and (page_num is None or cur == page_num)
    ):
        dismiss_popups(page)
        return
    if not force and tags_list_ready(page, search_term) and page_num is not None:
        set_list_page_number(page, page_num)
        return
    goto_tags_list_page(page, page_num or 1, search_term)


def list_pagination_info(page: Page) -> tuple[int, int]:
    """Return (current_page, total_pages) from URL, spinbutton, or 'Page N of M'."""
    cur = 1
    url_m = re.search(r"[?&]page=(\d+)", page.url)
    if url_m:
        cur = int(url_m.group(1))

    pag = page.locator('[class*="Pagination"]')
    pag_text = pag.first.inner_text() if pag.count() > 0 else ""
    if not pag_text:
        pag_text = page.locator("body").inner_text()

    for pattern in (
        r"Page\s+(\d+)\s+of\s+([\d,]+)",
        r"(\d+)\s+of\s+([\d,]+)",
    ):
        m = re.search(pattern, pag_text, re.I)
        if m:
            cur = int(m.group(1))
            total = int(m.group(2).replace(",", ""))
            return cur, total

    total_m = re.search(r"of\s+([\d,]+)", pag_text, re.I)
    total = int(total_m.group(1).replace(",", "")) if total_m else 1

    if cur == 1:
        for spin in (
            page.locator('[class*="Pagination"] input[type="number"]'),
            page.locator('[class*="Pagination"] [role="spinbutton"]'),
            page.get_by_role("spinbutton"),
        ):
            if spin.count() == 0:
                continue
            try:
                val = spin.first.input_value() or spin.first.get_attribute("value") or ""
                if val.strip().isdigit():
                    cur = int(val.strip())
                    break
            except Exception:
                continue

    return cur, max(total, cur)


def goto_tags_list_page(page: Page, page_num: int, search_term: str) -> None:
    """Land on list page N with search active.

    REISift resets to page 1 when the search box is filled — use spinbutton for N>1,
    not ?page=N after apply_search().
    """
    ensure_in_tags_folder(page)
    page_num = max(1, page_num)
    if not tags_list_ready(page, search_term):
        base = current_tag_folder_url(page) or _TAGS_FOLDER_URL or page.url.split("?")[0]
        page.goto(base.split("?")[0], wait_until="domcontentloaded")
        page.wait_for_timeout(800)
        apply_search(page, search_term, quiet=True)
    dismiss_popups(page)
    cur, _ = list_pagination_info(page)
    if cur != page_num and not set_list_page_number(page, page_num):
        log(f"Warning: could not jump to list page {page_num} (stuck on {cur})")


def click_list_page_next(page: Page) -> bool:
    before_cur, before_total = list_pagination_info(page)
    if before_cur >= before_total:
        return False
    next_page = before_cur + 1
    if set_list_page_number(page, next_page):
        return True
    base = page.url.split("?")[0]
    if "/tags/" in base:
        page.goto(f"{base}?page={next_page}", wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        after_cur, _ = list_pagination_info(page)
        if after_cur > before_cur:
            return True
    for loc in (
        page.locator('[class*="Pagination"] button:not([disabled])').last,
        page.get_by_role("button", name=re.compile(r"Next|›|→|>", re.I)),
        page.locator('button[aria-label*="Next" i]'),
    ):
        if loc.count() == 0:
            continue
        btn = loc.last if loc.count() > 1 else loc.first
        try:
            if not btn.is_enabled():
                continue
        except Exception:
            continue
        btn.click()
        page.wait_for_timeout(1000)
        after_cur, _ = list_pagination_info(page)
        return after_cur > before_cur
    return False


def ensure_list_page_one(page: Page) -> None:
    for _ in range(200):
        cur, _ = list_pagination_info(page)
        if cur <= 1:
            return
        clicked = False
        for loc in (
            page.locator('[class*="Pagination"] button:not([disabled])').first,
            page.get_by_role("button", name=re.compile(r"Previous|‹|←|<", re.I)),
            page.locator('button[aria-label*="Previous" i]'),
        ):
            if loc.count() == 0:
                continue
            btn = loc.first
            try:
                if not btn.is_enabled():
                    continue
            except Exception:
                continue
            btn.click()
            page.wait_for_timeout(800)
            clicked = True
            break
        if not clicked:
            return


def iter_list_pages(page: Page, *, reset: bool = True):
    """Walk paginated list pages (tags or records). When reset=True, start from page 1."""
    if reset:
        ensure_list_page_one(page)
    cur, total = list_pagination_info(page)
    yield cur
    while cur < total:
        if not click_list_page_next(page):
            break
        cur, total = list_pagination_info(page)
        yield cur


def read_page_count(page: Page) -> str:
    _, total = list_pagination_info(page)
    return str(total)


def tags_pagination_info(page: Page) -> tuple[int, int]:
    return list_pagination_info(page)


def click_tags_page_next(page: Page) -> bool:
    return click_list_page_next(page)


def ensure_tags_page_one(page: Page) -> None:
    ensure_list_page_one(page)


def iter_tags_pages(page: Page, *, reset: bool = True):
    yield from iter_list_pages(page, reset=reset)


def ensure_tags_search(page: Page, search_term: str) -> None:
    refresh_tags_list(page, search_term, force=True)


def scan_all_matching_tags(page: Page, search_term: str):
    """Yield (row, name, prop_count) for every matching tag on every page."""
    folder_urls = list_all_tag_folder_urls(page)
    if not folder_urls:
        ensure_in_tags_folder(page)
        apply_search(page, search_term, quiet=True)
        for _ in iter_tags_pages(page, reset=True):
            yield from iter_matching_tags(page, search_term)
        ensure_tags_page_one(page)
        return

    for folder_url in folder_urls:
        page.goto(folder_url, wait_until="domcontentloaded")
        page.wait_for_timeout(1200)
        apply_search(page, search_term, quiet=True)
        for _ in iter_tags_pages(page, reset=True):
            yield from iter_matching_tags(page, search_term)
    ensure_tags_page_one(page)


def count_matching_tags_all_pages(page: Page, search_term: str) -> int:
    n = sum(1 for _ in scan_all_matching_tags(page, search_term))
    ensure_tags_page_one(page)
    return n


def any_podio_tag_has_properties(
    page: Page, search_term: str, *, skip: set[str]
) -> bool:
    """True if any matching tag on any page still has properties (gate for phase 2)."""
    for _, name, count in scan_all_matching_tags(page, search_term):
        if name in skip or count <= 0:
            continue
        return True
    return False


def has_detach_work(page: Page, search_term: str, skip: set[str]) -> bool:
    for _, name, count in scan_all_matching_tags(page, search_term):
        if name in skip or count <= 0:
            continue
        return True
    return False


def has_delete_work(page: Page, search_term: str, skip: set[str]) -> bool:
    for _, name, count in scan_all_matching_tags(page, search_term):
        if name in skip or count != 0:
            continue
        return True
    return False


def find_tag_by_name(page: Page, tag_name: str) -> object | None:
    """Search for one exact tag name (single-ID probe, no bulk scrape)."""
    try:
        if "/tags/" not in page.url:
            open_property_tags(page)
        folder_urls = list_all_tag_folder_urls(page)
        if not folder_urls:
            ensure_in_tags_folder(page)
            folder_urls = [current_tag_folder_url(page) or page.url.split("?")[0]]
        for folder_url in folder_urls:
            page.goto(folder_url.split("?")[0], wait_until="domcontentloaded")
            page.wait_for_timeout(1000)
            apply_search(page, tag_name, quiet=True)
            ensure_tags_page_one(page)
            row = find_tag_row(page, tag_name)
            if row is not None:
                return row
        return None
    except PlaywrightTimeout:
        ensure_tags_page_for_work(page)
        raise


def lookup_tag_in_ui(
    page: Page,
    coordinator: TagCoordinator,
    tag_name: str,
    *,
    mark_missing_gone: bool = False,
) -> tuple[object | None, int]:
    """Probe UI for one catalog ID; only mark gone when explicitly requested."""
    row = find_tag_by_name(page, tag_name)
    if row is None:
        if mark_missing_gone:
            coordinator.mark_catalog_gone(tag_name)
        return None, 0
    prop_count = property_count_from_row(row)
    coordinator.update_catalog_property_count(tag_name, prop_count)
    return row, prop_count


def sync_catalog_from_ui(
    page: Page, coordinator: TagCoordinator, search_term: str
) -> tuple[int, int, int]:
    """Match catalog to live REISift tag list (fixes false gone/abandoned, adds new IDs)."""
    refresh_tags_list(page, search_term, force=True)
    added = revived = updated = 0
    for _, name, prop_count in scan_all_matching_tags(page, search_term):
        if coordinator.tag_id_prefix not in name:
            continue
        action = coordinator.ingest_ui_tag(name, prop_count)
        if action == "added":
            added += 1
        elif action == "revived":
            revived += 1
        elif action == "updated":
            updated += 1
    ensure_tags_page_one(page)
    return added, revived, updated


def finish_if_no_matching_tags(
    page: Page,
    coordinator: "TagCoordinator",
    search_term: str,
    worker_id: str,
) -> bool:
    """W1: advance detach→delete, or stop when delete sweep is done."""
    if worker_id != "W1":
        return False
    if coordinator.in_flight_count() > 0:
        return False
    if not coordinator.ui_pages_exhausted():
        return False

    if coordinator.get_phase() == PHASE_DETACH:
        coordinator.set_phase(PHASE_DELETE)
        coordinator.reset_ui_page_queue()
        log("=" * 60)
        log("Phase 1 (detach) complete — Phase 2 (delete) starting")
        log("=" * 60)
        return False

    goto_tags_list_page(page, 1, search_term)
    if any(iter_matching_tags(page, search_term)):
        coordinator.reset_ui_page_queue()
        log("Phase 2: tags remain — resetting delete queue from page 1")
        return False
    log(f'No "{search_term}" tags remaining — done.')
    coordinator.signal_stop()
    return True


def _safe_inner_text(row, *, timeout: float = 8_000) -> str:
    try:
        return row.inner_text(timeout=timeout)
    except PlaywrightTimeout:
        return ""


def tag_name_from_row(row) -> str:
    for line in _safe_inner_text(row).splitlines():
        line = line.strip()
        if line and line not in {"See Breakdown", "Skip Trace", "Show Properties"} and "propert" not in line.lower():
            return line
    return "(unknown)"


def iter_matching_tags(page: Page, search_term: str):
    """Yield (row, name, prop_count) for tags matching search on the current page."""
    needle = search_term.lower()
    for i in range(tag_rows(page).count()):
        row = tag_rows(page).nth(i)
        name = tag_name_from_row(row)
        if needle not in name.lower():
            continue
        yield row, name, property_count_from_row(row, trust_show_properties=False)


def tag_rows(page: Page):
    rows = page.locator(ROW_SELECTOR)
    if rows.count() > 0:
        return rows
    return page.locator('a:has-text("Show Properties")').locator(
        "xpath=ancestor::*[contains(@class,'Row') or contains(@class,'Card')][1]"
    )


def property_count_from_row(row, *, trust_show_properties: bool = True) -> int:
    text = _safe_inner_text(row)
    m = re.search(r"(\d+)\s+propert", text, re.I)
    if m:
        return int(m.group(1))
    if trust_show_properties and row.get_by_role("link", name="Show Properties").count() > 0:
        return 1
    return 0


def refresh_tag_on_list_page(
    page: Page,
    tag_name: str,
    search_term: str,
    *,
    page_num: int | None = None,
) -> tuple[object | None, int]:
    """Re-read one tag row on the current (or assigned) list page."""
    refresh_tags_list(page, search_term, force=False, page_num=page_num)
    row = find_tag_row(page, tag_name)
    if row is None:
        return None, 0
    return row, property_count_from_row(row, trust_show_properties=False)


def delete_blocked_in_modal(page: Page) -> bool:
    """True when REISift shows 'cannot delete tags that have properties associated'."""
    blocked = page.get_by_text(
        re.compile(
            r"cannot.*delete|still in use|properties associated|"
            r"cannot delete tags",
            re.I,
        )
    )
    return blocked.count() > 0 and blocked.first.is_visible()


def wait_for_tag_count_zero(
    page: Page,
    tag_name: str,
    search_term: str,
    *,
    page_num: int | None = None,
    max_wait_sec: float = POST_DETACH_COUNT_WAIT_SEC,
) -> tuple[object | None, int]:
    """Poll tag admin until property count reads 0 (REISift lags after property-page detach)."""
    deadline = time.monotonic() + max_wait_sec
    row: object | None = None
    count = -1
    polls = 0
    while time.monotonic() < deadline:
        refresh_tags_list(page, search_term, force=False, page_num=page_num)
        row = find_tag_row(page, tag_name)
        if row is None:
            return None, 0
        count = property_count_from_row(row, trust_show_properties=False)
        if count <= 0:
            if polls > 0:
                log(f"  → {tag_name} property count cleared after {polls} poll(s)")
            return row, 0
        polls += 1
        if polls == 1 or polls % 5 == 0:
            log(f"  → waiting for {tag_name} count to clear (admin shows {count})…")
        page.wait_for_timeout(POST_DETACH_POLL_INTERVAL_MS)
    return row, count


def on_dashboard(page: Page) -> bool:
    return "/dashboard" in page.url


def on_records_view(page: Page) -> bool:
    return "/records/properties" in page.url and not on_dashboard(page)


def wait_for_property_panel(page: Page, timeout: float = 15_000) -> bool:
    """Split-panel or /details view after clicking a property row."""
    try:
        page.wait_for_function(
            "() => location.pathname.includes('/details')"
            " || document.querySelector('[class*=\"MiniTabsContainer\"]')",
            timeout=timeout,
        )
        page.wait_for_timeout(400)
        return not on_dashboard(page)
    except PlaywrightTimeout:
        return not on_dashboard(page) and page.locator(MINI_TABS).count() > 0


def load_local_env() -> None:
    """Load REISIFT_* from .env next to script or project root (no extra deps)."""
    for path in (Path(__file__).resolve().parent.parent / ".env", Path(__file__).resolve().parent / ".env"):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


def _first_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _looks_like_property_row(text: str) -> bool:
    if not text:
        return False
    if STREET_IN_ADDRESS.search(text):
        return True
    return bool(re.search(r"\d+\s+\S+", text)) and bool(re.search(r"\b[A-Z]{2}\s+\d{5}\b", text))


def _junk_record_label(label: str) -> bool:
    line = _first_line(label)
    if not line:
        return True
    return bool(RECORDS_JUNK_LABEL.match(line))


def parse_property_uuid(text: str) -> str | None:
    if not text:
        return None
    m = PROPERTY_HREF_RE.search(text)
    if m:
        return m.group(1).lower()
    m = PROPERTY_UUID_RE.search(text)
    return m.group(0).lower() if m else None


def property_details_url(uuid: str) -> str:
    return f"{BASE_URL}/records/properties/{uuid.lower()}/details?page=1"


def _uuid_from_row_dom(row) -> str | None:
    """Scan row HTML/attributes for a property UUID (no hover).

    Records rows are <a.TableRowContainer href="/records/properties/{uuid}/..."> —
    the link is on the row itself, not a child anchor.
    """
    href = row.get_attribute("href") or ""
    found = parse_property_uuid(href)
    if found:
        return found

    raw = row.evaluate(
        """(el) => {
            const hrefRe = /\\/records\\/properties\\/([a-f0-9-]+)/i;
            const uuidRe = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
            const fromHref = (node) => {
                if (!node) return null;
                const href = node.getAttribute('href') || '';
                const m = href.match(hrefRe);
                return m ? m[1].toLowerCase() : null;
            };
            let u = fromHref(el);
            if (u) return u;
            u = fromHref(el.closest('a[href*="/records/properties/"]'));
            if (u) return u;
            for (const a of el.querySelectorAll('a[href*="/records/properties/"]')) {
                u = fromHref(a);
                if (u) return u;
            }
            for (const node of [el, ...el.querySelectorAll('*')]) {
                for (const attr of node.attributes || []) {
                    const hm = attr.value.match(hrefRe);
                    if (hm) return hm[1].toLowerCase();
                    if (uuidRe.test(attr.value.trim())) return attr.value.trim().toLowerCase();
                }
            }
            const hm = el.innerHTML.match(hrefRe);
            return hm ? hm[1].toLowerCase() : null;
        }"""
    )
    return raw if raw else None


def _uuid_from_visible_tooltips(page: Page) -> str | None:
    for sel in TOOLTIP_SELECTORS:
        tips = page.locator(sel)
        for i in range(tips.count()):
            tip = tips.nth(i)
            try:
                if not tip.is_visible():
                    continue
            except Exception:
                continue
            blob = f"{tip.inner_text()} {tip.get_attribute('title') or ''}"
            u = parse_property_uuid(blob)
            if u:
                return u
    return _uuid_from_visible_overlays(page)


def _uuid_from_visible_overlays(page: Page) -> str | None:
    """Any small visible overlay/popover text containing a property UUID."""
    raw = page.evaluate(
        """() => {
            const hrefRe = /\\/records\\/properties\\/([a-f0-9-]+)/i;
            const uuidRe = /[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}/i;
            for (const n of document.querySelectorAll('body *')) {
                const style = window.getComputedStyle(n);
                if (style.display === 'none' || style.visibility === 'hidden') continue;
                const r = n.getBoundingClientRect();
                if (r.width < 2 || r.height < 2) continue;
                const text = (n.textContent || '').trim();
                if (!text || text.length > 200) continue;
                const hm = text.match(hrefRe);
                if (hm) return hm[1].toLowerCase();
                if (uuidRe.test(text)) {
                    const m = text.match(uuidRe);
                    if (m) return m[0].toLowerCase();
                }
            }
            return null;
        }"""
    )
    return raw if raw else None


def resolve_property_uuid(page: Page, row) -> str | None:
    """Property UUID from row DOM, or from tooltip shown on row hover."""
    found = _uuid_from_row_dom(row)
    if found:
        return found

    hover_targets = []
    for loc in (
        row.locator(PROPERTY_ADDRESS).first,
        row.locator('[class*="RecordsProperties"]').first,
        row.locator('[class*="Info"]').first,
        row,
    ):
        if loc.count() > 0:
            hover_targets.append(loc)
    if not hover_targets:
        hover_targets = [row]

    for target in hover_targets:
        try:
            target.scroll_into_view_if_needed()
            target.hover()
            page.wait_for_timeout(900)
            found = _uuid_from_visible_tooltips(page) or _uuid_from_row_dom(row)
            page.mouse.move(8, 8)
            page.wait_for_timeout(200)
            if found:
                return found
        except Exception:
            continue
    return None


def _record_rows_with_address(page: Page):
    rows = page.locator(RECORDS_ROW_LINK)
    if rows.count() == 0:
        rows = page.locator(f'{ROW_SELECTOR}:has({PROPERTY_ADDRESS})')
    if rows.count() == 0:
        rows = page.locator(ROW_SELECTOR).filter(has=page.locator(PROPERTY_ADDRESS))
    return rows


def _label_from_record_row(row) -> str:
    """Address label from property row — owner cell may be empty."""
    addr = row.locator(PROPERTY_ADDRESS).first
    if addr.count():
        label = _first_line(addr.inner_text())
        if label and not _junk_record_label(label):
            return label
    for cell in row.locator(RECORDS_TABLE_CELL).all():
        text = _first_line(cell.inner_text())
        if text and not _junk_record_label(text) and _looks_like_property_row(text):
            return text
    return _first_line(row.inner_text())


def _uuid_from_record_row(page: Page, row) -> str | None:
    found = _uuid_from_row_dom(row)
    if found:
        return found
    return resolve_property_uuid(page, row)


def collect_record_properties(page: Page) -> list[tuple[str, str]]:
    """Return (property_uuid, address_label) for each visible records row."""
    results: list[tuple[str, str]] = []
    seen: set[str] = set()
    rows = _record_rows_with_address(page)

    for i in range(rows.count()):
        row = rows.nth(i)
        label = _label_from_record_row(row)
        if not label or _junk_record_label(label):
            if not parse_property_uuid(row.get_attribute("href") or ""):
                continue
            label = label or "(property)"

        uuid = _uuid_from_record_row(page, row)
        if not uuid:
            log(f"  → no UUID for row {label!r} (href/hover scan failed)")
            continue
        if uuid in seen:
            continue
        seen.add(uuid)
        results.append((uuid, label))

    return results


def collect_record_properties_all_pages(page: Page) -> list[tuple[str, str]]:
    """Return (uuid, label) from every records page (current filter/tab)."""
    combined: list[tuple[str, str]] = []
    seen: set[str] = set()
    for page_num in iter_list_pages(page, reset=True):
        cur, total = list_pagination_info(page)
        if total > 1:
            log(f"  → records page {cur}/{total}")
        for uuid, label in collect_record_properties(page):
            if uuid in seen:
                continue
            seen.add(uuid)
            combined.append((uuid, label))
    ensure_list_page_one(page)
    return combined


def _records_have_rows_any_page(page: Page) -> bool:
    for _ in iter_list_pages(page, reset=True):
        if record_target_count(page) > 0:
            ensure_list_page_one(page)
            return True
    return False


def record_row_count(page: Page) -> int:
    """Fast count of visible property rows (no hover / UUID resolution)."""
    rows = _record_rows_with_address(page)
    if rows.count() > 0 and page.locator(RECORDS_ROW_LINK).count() > 0:
        return page.locator(RECORDS_ROW_LINK).count()
    count = 0
    for i in range(rows.count()):
        row = rows.nth(i)
        label = _label_from_record_row(row)
        if label and not _junk_record_label(label) and _looks_like_property_row(label):
            count += 1
        elif parse_property_uuid(row.get_attribute("href") or ""):
            count += 1
    return count


def record_target_count(page: Page) -> int:
    return record_row_count(page)


def wait_records_table(page: Page, timeout_ms: int = 10_000) -> None:
    """Wait for address cells or an explicit empty state after filter changes."""
    try:
        page.wait_for_function(
            """() => {
                if (document.querySelector('a[class*="TableRowContainer"][href*="/records/properties/"]')) return true;
                if (document.querySelector('[class*="RecordsPropertiesAddressLine1"]')) return true;
                const t = document.body.innerText || '';
                return /no (properties|records|results)/i.test(t);
            }""",
            timeout=timeout_ms,
        )
    except PlaywrightTimeout:
        pass
    page.wait_for_timeout(400)


def ensure_property_records_tab(page: Page) -> None:
    """Show Properties sometimes opens bare /records — switch to Property Records."""
    if "/records/properties" in page.url:
        return
    tab = page.get_by_role("link", name=re.compile(r"Property Records", re.I))
    if tab.count() > 0:
        tab.first.click()
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(1500)


def reveal_record_rows(page: Page) -> None:
    """Records defaults to Clean — tagged properties may only appear under All/Incomplete."""
    dismiss_popups(page)
    ensure_property_records_tab(page)
    for label in ("All", "Incomplete", "Clean"):
        btn = page.get_by_role("button", name=label, exact=True)
        if btn.count() == 0:
            continue
        btn.first.click()
        wait_records_table(page)
        if _records_have_rows_any_page(page):
            log(f"  → found rows with {label!r} filter")
            return
    log("  → no rows under All / Incomplete / Clean (checked all pages)")


def open_show_properties_popup(page: Page, row) -> Page:
    """Show Properties opens Records in a new tab — not same-page navigation."""
    show = row.get_by_role("link", name="Show Properties")
    if show.count() == 0:
        show = page.get_by_role("link", name="Show Properties").first
    else:
        show = show.first
    show.scroll_into_view_if_needed()
    with page.expect_popup(timeout=20_000) as popup_info:
        show.click()
    records = popup_info.value
    records.wait_for_load_state("domcontentloaded")
    records.wait_for_timeout(2000)
    return records


def open_tags_tab(page: Page) -> None:
    """Switch to Tags sub-tab inside the Records split-panel (never sidebar nav)."""
    if on_dashboard(page):
        raise RuntimeError(f"on dashboard instead of property view: {page.url}")

    tabs_bar = page.locator(MINI_TABS).first
    if tabs_bar.count() == 0 or not tabs_bar.is_visible():
        header = page.get_by_role("button", name=re.compile(r"Lists\s*&\s*Tags", re.I))
        if header.count() > 0:
            header.scroll_into_view_if_needed()
            if header.get_attribute("aria-expanded") == "false":
                header.click()
                page.wait_for_timeout(500)

    tabs_bar = page.locator(MINI_TABS).first
    tabs_bar.wait_for(state="visible", timeout=10_000)
    tags_tab = tabs_bar.locator(TAGS_TAB).filter(has_text=re.compile(r"Tags\s*\(\d+\)", re.I))
    if tags_tab.count() == 0:
        tags_tab = tabs_bar.get_by_text(re.compile(r"Tags\s*\(\d+\)"))
    tags_tab.first.scroll_into_view_if_needed()
    tags_tab.first.click()
    page.wait_for_timeout(400)


def remove_tag_from_property(page: Page, tag_name: str) -> bool:
    """Records split-panel → Tags tab → click X on pill (never the add-tag search box)."""
    log(f"  → removing tag {tag_name} from property… (url={page.url})")
    if on_dashboard(page):
        log("  → on dashboard — cannot remove tag here")
        return False

    try:
        open_tags_tab(page)
    except (PlaywrightTimeout, RuntimeError) as exc:
        log(f"  → Tags tab not found: {exc}")
        return False

    container = page.locator(TAG_PILL_CONTAINER).first
    container.wait_for(state="visible", timeout=10_000)

    pill = container.locator(TAG_PILL).filter(has_text=re.compile(f"^{re.escape(tag_name)}$", re.I))
    if pill.count() == 0:
        pill = container.locator(TAG_PILL).filter(has_text=re.compile(re.escape(tag_name), re.I))
    if pill.count() == 0:
        log(f"  → tag pill {tag_name!r} already removed from this property")
        return True

    remove_btn = pill.first.locator(TAG_REMOVE)
    remove_btn.scroll_into_view_if_needed()
    remove_btn.wait_for(state="visible", timeout=10_000)
    remove_btn.click()
    page.wait_for_timeout(800)
    log(f"    removed {tag_name} from property")
    return True


def find_tag_row(page: Page, tag_name: str):
    for i in range(tag_rows(page).count()):
        row = tag_rows(page).nth(i)
        if tag_name_from_row(row) == tag_name:
            return row
    return None


def find_tag_row_all_pages(page: Page, tag_name: str) -> object | None:
    for _ in iter_tags_pages(page, reset=True):
        row = find_tag_row(page, tag_name)
        if row is not None:
            return row
    return None


def pick_next_tag_to_detach(
    page: Page, search_term: str, *, skip: set[str]
) -> tuple[object, str, int] | None:
    """Phase 1 — tags with properties, scanning every results page (no page reload)."""
    for page_num in iter_tags_pages(page, reset=True):
        best = None
        best_count: int | None = None
        for i in range(tag_rows(page).count()):
            row = tag_rows(page).nth(i)
            name = tag_name_from_row(row)
            if search_term.lower() not in name.lower() or name in skip:
                continue
            count = property_count_from_row(row)
            if count <= 0:
                continue
            if best is None or count < best_count:
                best = (row, name, count)
                best_count = count
        if best is not None:
            cur, total = tags_pagination_info(page)
            if total > 1:
                log(f"  → detach candidate on tags page {cur}/{total}")
            return best
    return None


def pick_next_tag_to_delete(
    page: Page, search_term: str, *, skip: set[str]
) -> tuple[object, str, int] | None:
    """Phase 2 — 0-property tags, scanning every results page (no page reload)."""
    for page_num in iter_tags_pages(page, reset=True):
        for i in range(tag_rows(page).count()):
            row = tag_rows(page).nth(i)
            name = tag_name_from_row(row)
            if search_term.lower() not in name.lower() or name in skip:
                continue
            count = property_count_from_row(row)
            if count == 0:
                cur, total = tags_pagination_info(page)
                if total > 1:
                    log(f"  → delete candidate on tags page {cur}/{total}")
                return row, name, count
    return None


def detach_tag_from_properties(
    page: Page,
    row,
    tag_name: str,
    *,
    retries: int = 3,
) -> str:
    """Show Properties → remove tag from each property.

    Returns 'already_clear' (0 in admin or 0 rows in Records), 'detached', or 'failed'.
    """
    count = property_count_from_row(row, trust_show_properties=False)
    if count <= 0:
        return "already_clear"

    log(f"  {count} propert{'y' if count == 1 else 'ies'} attached — detaching first…")
    dismiss_popups(page)

    for attempt in range(1, retries + 1):
        records = None
        try:
            records = open_show_properties_popup(page, row)
        except PlaywrightTimeout:
            log(f"  → Show Properties popup did not open (attempt {attempt}/{retries})")
            page.wait_for_timeout(1200)
            continue

        try:
            log(f"  → Records opened in new tab: {records.url}")
            if on_dashboard(records):
                log("  → popup landed on dashboard")
                continue
            if "tags=" not in records.url and "/records/properties" not in records.url:
                log("  → Records popup missing tag filter — opening Property Records tab")
                ensure_property_records_tab(records)

            reveal_record_rows(records)
            records_list_url = records.url
            properties = collect_record_properties_all_pages(records)
            if not properties:
                log("  → no property rows in Records — already detached (ghost admin count)")
                dismiss_popups(page)
                return "already_clear"
            log(f"  → on Records: {len(properties)} property(s) via UUID (tag admin says {count})")

            detached = 0
            processed: set[str] = set()
            while detached < count:
                if detached > 0:
                    records.goto(records_list_url, wait_until="domcontentloaded")
                    records.wait_for_timeout(800)
                    reveal_record_rows(records)
                    properties = collect_record_properties_all_pages(records)
                    if not properties:
                        break

                uuid, label = next(
                    ((u, lbl) for u, lbl in properties if u not in processed), (None, None)
                )
                if uuid is None:
                    remaining = collect_record_properties_all_pages(records)
                    uuid, label = next(
                        ((u, lbl) for u, lbl in remaining if u not in processed), (None, None)
                    )
                    if uuid is None:
                        break
                    properties = remaining

                log(f"  → opening property {detached + 1}/{count}: {label} → {uuid}…")
                records.goto(property_details_url(uuid), wait_until="domcontentloaded")
                records.wait_for_timeout(1200)
                if on_dashboard(records):
                    log("  → property URL redirected to dashboard")
                    return "failed"
                if not wait_for_property_panel(records):
                    log(f"  → property panel did not open (url={records.url})")
                    return "failed"
                if not remove_tag_from_property(records, tag_name):
                    return "failed"
                processed.add(uuid)
                detached += 1

            log(f"  → detached from {detached} propert{'y' if detached == 1 else 'ies'}")
            if detached > 0:
                dismiss_popups(page)
                return "detached"
            log("  → nothing detached")
        finally:
            if records is not None:
                try:
                    records.close()
                except Exception:
                    pass

    dismiss_popups(page)
    return "failed"


def confirm_delete_modal(page: Page, tag_name: str) -> None:
    """0-property tags: simple confirm. Tags that had properties: type name first."""
    if delete_blocked_in_modal(page):
        raise PlaywrightTimeout("delete blocked — properties still associated")

    submit = page.get_by_role("button", name=re.compile(r"Yes,\s*delete", re.I))
    submit.wait_for(state="visible", timeout=10_000)

    inp = page.locator('[class*="Prompt"] input, [class*="Modal"] input').first
    if inp.count() > 0 and inp.is_visible():
        inp.fill(tag_name)
        page.wait_for_timeout(400)
        for _ in range(50):
            if submit.is_enabled():
                break
            page.wait_for_timeout(200)
        if not submit.is_enabled():
            raise PlaywrightTimeout("Yes, delete it! still disabled after typing tag name")

    submit.click()
    page.wait_for_timeout(600)
    close_modal_overlays(page)


def delete_one_tag(page: Page, row, name: str) -> tuple[bool, str]:
    """Delete a tag row; returns (success, failure_reason)."""
    for attempt in range(3):
        prepare_tags_ui(page)
        try:
            dropdown = row.get_by_test_id("Tags__ListItem__Dropdown")
            if dropdown.count() > 0:
                dropdown.click(timeout=10_000)
            else:
                row.locator("button, svg").last.click(timeout=10_000)
            page.get_by_text("Delete", exact=True).last.wait_for(state="visible", timeout=5000)
            page.get_by_text("Delete", exact=True).last.click(timeout=10_000)
            page.wait_for_timeout(400)

            page.get_by_text(re.compile(r"Are you sure|delete this tag", re.I)).wait_for(
                state="visible", timeout=8000
            )
            if delete_blocked_in_modal(page):
                close_modal_overlays(page)
                return False, "still has properties"
            confirm_delete_modal(page, name)
        except PlaywrightTimeout as exc:
            close_modal_overlays(page)
            if delete_blocked_in_modal(page):
                close_modal_overlays(page)
                return False, "still has properties"
            if "delete blocked" in str(exc).lower():
                return False, "still has properties"
            if attempt >= 2:
                return False, "ui timeout"
            page.wait_for_timeout(600)
            fresh = find_tag_row(page, name)
            if fresh is None:
                return False, "row not found"
            row = fresh
            continue

        if delete_blocked_in_modal(page):
            close_modal_overlays(page)
            return False, "still has properties"
        return True, ""

    return False, "ui timeout"


def ensure_tags_page_for_work(page: Page) -> None:
    """Navigate to Property Tags if the worker left that view."""
    if TAGS_PATH not in page.url or page.get_by_placeholder(SEARCH_PLACEHOLDER).count() == 0:
        open_property_tags(page)
    elif not is_tags_folder_view(page):
        ensure_in_tags_folder(page)


def delete_one_tag_coordinated(
    page: Page,
    coordinator: TagCoordinator,
    name: str,
    *,
    worker_id: str,
    row=None,
    force: bool = False,
) -> tuple[bool, str]:
    """Delete one tag row in this worker's browser (no cross-worker lock — separate sessions)."""
    if row is None:
        row = find_tag_row(page, name)
    if row is None:
        return False, "row not found"
    if not force:
        prop_count = property_count_from_row(row, trust_show_properties=False)
        if prop_count > 0:
            coordinator.mark_needs_detach(name, prop_count)
            return False, f"still has {prop_count} propert{'y' if prop_count == 1 else 'ies'}"
    return delete_one_tag(page, row, name)


def _finish_delete_attempt(
    page: Page,
    coordinator: TagCoordinator,
    name: str,
    row,
    *,
    delay_ms: int,
    worker_id: str,
    force: bool,
    seq: int,
    quiet: bool = False,
) -> str:
    """Run delete modal flow. Returns 'ok', 'gone', 'still_has', or other failure token."""
    coordinator.begin_delete(name, worker_id)
    if not quiet:
        log(f"[{seq:04d}] Delete {name}…", end=" ")
    ok, reason = delete_one_tag_coordinated(
        page, coordinator, name, worker_id=worker_id, row=row, force=force
    )
    if ok:
        coordinator.finish_delete(name, success=True)
        page.wait_for_timeout(delay_ms)
        log("OK")
        stats = coordinator.stats()
        if stats.deleted and stats.deleted % 10 == 0:
            log(f"--- {stats.deleted} deleted total ---")
        return "ok"
    if reason == "row not found":
        coordinator.finish_delete(name, success=True)
        log("gone")
        return "gone"
    if reason == "still has properties":
        coordinator.release_claim(name)
        log("delete blocked — REISift count lag (will retry)")
        return "count_lag"
    if reason.startswith("still has"):
        ui_count = property_count_from_row(row)
        coordinator.release_claim(name)
        coordinator.record_failed()
        abandoned = coordinator.note_detach_failure(name)
        coordinator.mark_needs_detach(name, ui_count)
        suffix = " (gave up)" if abandoned else ""
        log(f"{reason}{suffix}")
        return "still_has"
    coordinator.finish_delete(name, success=False)
    log(reason or "delete failed")
    return reason or "failed"


def process_detach_only(
    page: Page,
    coordinator: TagCoordinator,
    name: str,
    search_term: str,
    *,
    worker_id: str,
    row: object,
    prop_count: int,
    list_page_num: int | None,
) -> None:
    """Phase 1: remove tag from properties, then immediately move on (no admin wait)."""
    ensure_tags_page_for_work(page)
    seq = coordinator.stats().detached + 1
    if prop_count <= 0:
        coordinator.release_claim(name)
        return

    coordinator.note_work()
    log(f"[{seq:04d}] Detach {name} ({prop_count} propert{'y' if prop_count == 1 else 'ies'})…")
    result = detach_tag_from_properties(page, row, name)
    if result == "failed":
        coordinator.release_claim(name)
        coordinator.record_failed()
        abandoned = coordinator.note_detach_failure(name)
        if abandoned:
            log(f"[{seq:04d}] GIVE UP {name} — detach failed {MAX_DETACH_FAILURES} times")
        else:
            log(f"[{seq:04d}] SKIP {name} — detach failed")
        return

    coordinator.finish_detach(name)
    if result == "already_clear":
        log(f"  → {name} already clear in Records — next tag")
    else:
        log(f"  → {name} removed from propert{'y' if prop_count == 1 else 'ies'} — next tag")


def process_delete_only(
    page: Page,
    coordinator: TagCoordinator,
    name: str,
    search_term: str,
    *,
    delay_ms: int,
    worker_id: str,
    row: object | None,
    prop_count: int | None,
    list_page_num: int | None,
) -> None:
    """Phase 2: delete tags that show 0 properties (or were detached in phase 1)."""
    ensure_tags_page_for_work(page)
    if row is None or prop_count is None:
        row, prop_count = refresh_tag_on_list_page(
            page, name, search_term, page_num=list_page_num
        )
    if row is None:
        coordinator.finish_delete(name, success=True)
        log(f"SKIP {name} — gone")
        return

    detached_in_phase1 = coordinator.catalog_status(name) == "detached"
    if prop_count > 0 and not detached_in_phase1:
        coordinator.release_claim(name)
        log(f"SKIP {name} — still has {prop_count} propert{'y' if prop_count == 1 else 'ies'}")
        return

    seq = coordinator.stats().deleted + 1
    coordinator.note_work()
    _finish_delete_attempt(
        page,
        coordinator,
        name,
        row,
        delay_ms=delay_ms,
        worker_id=worker_id,
        force=False,
        seq=seq,
    )


def process_tag_work(
    page: Page,
    coordinator: TagCoordinator,
    name: str,
    search_term: str,
    *,
    delay_ms: int,
    worker_id: str,
    delete_first: bool = False,
    row: object | None = None,
    prop_count: int | None = None,
    list_page_num: int | None = None,
) -> None:
    """Route to phase 1 (detach) or phase 2 (delete)."""
    if list_page_num is None:
        list_page_num = coordinator.assigned_list_page(worker_id)
    if coordinator.get_phase() == PHASE_DETACH:
        if row is None:
            row, prop_count = refresh_tag_on_list_page(
                page, name, search_term, page_num=list_page_num
            )
        if row is None:
            coordinator.release_claim(name)
            return
        process_detach_only(
            page,
            coordinator,
            name,
            search_term,
            worker_id=worker_id,
            row=row,
            prop_count=prop_count or 0,
            list_page_num=list_page_num,
        )
    else:
        process_delete_only(
            page,
            coordinator,
            name,
            search_term,
            delay_ms=delay_ms,
            worker_id=worker_id,
            row=row,
            prop_count=prop_count,
            list_page_num=list_page_num,
        )


def process_one_tag(
    page: Page,
    coordinator: TagCoordinator,
    name: str,
    search_term: str,
    *,
    delay_ms: int,
    worker_id: str,
    delete_first: bool = False,
) -> None:
    process_tag_work(
        page,
        coordinator,
        name,
        search_term,
        delay_ms=delay_ms,
        worker_id=worker_id,
        delete_first=delete_first,
    )


def claim_next_from_ui(
    page: Page,
    coordinator: TagCoordinator,
    search_term: str,
    worker_id: str,
) -> tuple[object, str, int] | None:
    """Claim the next tag on this worker's assigned list page (pages 1..N)."""
    skip = coordinator.skip_names(for_delete=True)
    prev_page = coordinator.assigned_list_page(worker_id)
    page_num = coordinator.get_or_assign_worker_page(worker_id)
    if page_num is None:
        return None
    if prev_page != page_num:
        log(f"Assigned list page {page_num}/{coordinator.ui_total_pages() or '?'}")
    goto_tags_list_page(page, page_num, search_term)
    matches = [
        (row, name, prop_count)
        for row, name, prop_count in iter_matching_tags(page, search_term)
        if coordinator.tag_id_prefix in name
    ]
    if not matches:
        coordinator.release_worker_page(worker_id)
        return None
    claimable = [(row, name, prop_count) for row, name, prop_count in matches if name not in skip]
    if coordinator.get_phase() == PHASE_DETACH:
        claimable = [
            (r, n, p)
            for r, n, p in claimable
            if p > 0 and coordinator.catalog_status(n) != "detached"
        ]
    else:
        claimable = [
            (r, n, p)
            for r, n, p in claimable
            if p <= 0 or coordinator.catalog_status(n) == "detached"
        ]
    if not claimable:
        coordinator.release_worker_page(worker_id)
        return None
    if coordinator.get_phase() == PHASE_DELETE:
        claimable.sort(key=lambda item: item[2])
    for row, name, prop_count in claimable:
        if not coordinator.try_claim_by_name(name, worker_id):
            continue
        coordinator.update_catalog_property_count(name, prop_count)
        return row, name, prop_count
    return None


def try_delete_zero_property_from_ui(
    page: Page,
    coordinator: TagCoordinator,
    search_term: str,
    *,
    delay_ms: int,
    worker_id: str,
) -> bool:
    """Scan the podio tag list and delete the next 0-property tag (fast delete phase)."""
    refresh_tags_list(page, search_term, force=False)
    skip = coordinator.skip_names(for_delete=True)
    for _ in iter_tags_pages(page, reset=True):
        for row, name, prop_count in iter_matching_tags(page, search_term):
            if coordinator.tag_id_prefix not in name or name in skip:
                continue
            if prop_count > 0:
                continue
            if not coordinator.try_claim_by_name(name, worker_id):
                continue
            seq = coordinator.stats().detached + coordinator.stats().deleted + coordinator.stats().failed + 1
            try:
                _finish_delete_attempt(
                    page,
                    coordinator,
                    name,
                    row,
                    delay_ms=delay_ms,
                    worker_id=worker_id,
                    force=True,
                    seq=seq,
                )
            except Exception:
                coordinator.release_claim(name)
                raise
            return True
    ensure_tags_page_one(page)
    return False


def run_work_loop(
    page: Page,
    coordinator: TagCoordinator,
    search_term: str,
    *,
    delay_ms: int,
    worker_id: str,
    delete_first: bool = False,
    ui_first: bool = True,
) -> None:
    """Work from the live REISift tag list; catalog is tracking only."""
    if worker_id == "W1":
        n = int(coordinator._meta("catalog_count") or 0)
        stats = coordinator.catalog_stats_summary()
        pending = stats.get("pending", 0) + stats.get("detached", 0)
        log(
            f"Catalog ready: {coordinator.tag_id_prefix}{coordinator.id_min}…"
            f"{coordinator.id_max} ({n} slots)"
        )
        log(
            f"Resume state: {stats.get('deleted_meta', 0)} deleted, "
            f"{pending} pending, {stats.get('gone', 0)} gone, "
            f"{stats.get('abandoned', 0)} abandoned"
        )
        ensure_tags_page_for_work(page)
        goto_tags_list_page(page, 1, search_term)
        cur, total_pages = list_pagination_info(page)
        coordinator.set_ui_total_pages(total_pages)
        page_tags = sum(1 for _ in iter_matching_tags(page, search_term))
        log(
            f"UI list: {total_pages} pages, ~{page_tags} tags/page "
            f"(~{total_pages * page_tags:,} {search_term!r} tags total)"
        )
        if ui_first:
            phase = coordinator.get_phase()
            log(
                f"Mode: two-pass — Phase 1 detach all pages, "
                f"then Phase 2 delete (currently: {phase})"
            )
        if delete_first:
            log("Mode: delete-first override (single-tag detach+delete)")

    ensure_tags_page_for_work(page)
    idle_passes = 0

    while coordinator.should_continue_work():
        name: str | None = None
        ui_row: object | None = None
        ui_count: int | None = None

        if ui_first:
            ui_claim = claim_next_from_ui(page, coordinator, search_term, worker_id)
            if ui_claim:
                ui_row, name, ui_count = ui_claim

        if name is None and not ui_first:
            name = coordinator.claim_next_work(worker_id)

        if name is None:
            if coordinator.in_flight_count() > 0:
                idle_passes = 0
                page.wait_for_timeout(1200)
                continue
            if worker_id == "W1" and idle_passes == 0:
                cur, total_pages = list_pagination_info(page)
                if total_pages > coordinator.ui_total_pages():
                    coordinator.set_ui_total_pages(total_pages)
                next_p = coordinator.ui_next_page_number()
                log(
                    f"Queue: page {next_p} next / {coordinator.ui_total_pages()} total "
                    f"({coordinator.in_flight_count()} in flight)"
                )
            idle_passes += 1
            if finish_if_no_matching_tags(page, coordinator, search_term, worker_id):
                break
            coordinator.note_no_work()
            page.wait_for_timeout(2000)
            continue

        idle_passes = 0
        try:
            if delete_first:
                process_tag_work(
                    page,
                    coordinator,
                    name,
                    search_term,
                    delay_ms=delay_ms,
                    worker_id=worker_id,
                    delete_first=True,
                    row=ui_row,
                    prop_count=ui_count,
                    list_page_num=coordinator.assigned_list_page(worker_id),
                )
            elif coordinator.get_phase() == PHASE_DETACH:
                process_detach_only(
                    page,
                    coordinator,
                    name,
                    search_term,
                    worker_id=worker_id,
                    row=ui_row,
                    prop_count=ui_count or 0,
                    list_page_num=coordinator.assigned_list_page(worker_id),
                )
            else:
                process_delete_only(
                    page,
                    coordinator,
                    name,
                    search_term,
                    delay_ms=delay_ms,
                    worker_id=worker_id,
                    row=ui_row,
                    prop_count=ui_count,
                    list_page_num=coordinator.assigned_list_page(worker_id),
                )
        except PlaywrightTimeout as exc:
            coordinator.release_claim(name)
            close_modal_overlays(page)
            ensure_tags_page_for_work(page)
            coordinator.record_failed()
            log(f"TIMEOUT {name}: {exc}")
        except Exception as exc:
            coordinator.release_claim(name)
            close_modal_overlays(page)
            ensure_tags_page_for_work(page)
            coordinator.record_failed()
            log(f"ERROR {name}: {exc}")


def run_worker_loop(
    page: Page,
    coordinator: TagCoordinator,
    search_term: str,
    *,
    delay_ms: int,
    worker_id: str,
    delete_first: bool = False,
    ui_first: bool = True,
) -> None:
    run_work_loop(
        page,
        coordinator,
        search_term,
        delay_ms=delay_ms,
        worker_id=worker_id,
        delete_first=delete_first,
        ui_first=ui_first,
    )
    if worker_id == "W1" and not coordinator.is_stopped():
        finish_if_no_matching_tags(page, coordinator, search_term, worker_id)


def wait_for_all_logins(coordinator: TagCoordinator, worker_id: str) -> bool:
    if coordinator.worker_count <= 1:
        coordinator.signal_login_ready(worker_id)
        return True
    return coordinator.wait_for_all_logins(worker_id)


def run_browser_worker(
    worker_id: int,
    email: str,
    password: str,
    coordinator: TagCoordinator,
    *,
    search_term: str,
    headless: bool,
    slow_mo: int,
    delay_ms: int,
    delete_first: bool = False,
    ui_first: bool = True,
) -> None:
    """One logged-in browser session; safe to run concurrently with other workers."""
    _log_prefix.value = f"[W{worker_id}]"
    launch_args: list[str] = []
    if not headless:
        x = 40 + (worker_id - 1) * 680
        launch_args = [f"--window-position={x},40", "--window-size=1280,900"]
    page: Page | None = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless, slow_mo=slow_mo, args=launch_args)
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()
            login(page, email, password)
            open_property_tags(page)
            wid = f"W{worker_id}"
            if not wait_for_all_logins(coordinator, wid):
                return
            if not is_authenticated(page):
                log("Session lost after login barrier — aborting.")
                coordinator.signal_stop()
                return
            if worker_id == 1:
                log(
                    f"Workers: {coordinator.worker_count} session(s); "
                    f"queue from live UI list ({search_term!r} in tag folder)"
                )
                log("-" * 60)
            run_worker_loop(
                page,
                coordinator,
                search_term,
                delay_ms=delay_ms,
                worker_id=wid,
                delete_first=delete_first,
                ui_first=ui_first,
            )
            browser.close()
    except KeyboardInterrupt:
        coordinator.signal_stop()
        raise
    except Exception as exc:
        log(f"Worker stopped: {exc}")
        if page is not None:
            try:
                close_modal_overlays(page)
            except Exception:
                pass
    finally:
        _log_prefix.value = ""


def delete_matching_tags(
    page: Page,
    search_term: str,
    *,
    coord_db: Path,
    limit: int | None,
    delay_ms: int,
    tag_id_prefix: str = DEFAULT_TAG_ID_PREFIX,
    id_min: int = PODIO_ID_MIN,
    id_max: int = PODIO_ID_MAX,
    resume: bool = False,
    delete_first: bool = False,
    ui_first: bool = True,
) -> DeleteStats:
    """Single-browser entry (workers=1)."""
    coordinator = TagCoordinator(
        coord_db,
        limit=limit,
        worker_count=1,
        reset=not resume,
        tag_id_prefix=tag_id_prefix,
        id_min=id_min,
        id_max=id_max,
        delete_first=delete_first,
    )
    dismiss_popups(page)
    log(f"Coord DB: {coord_db}")
    log("-" * 60)
    run_worker_loop(
        page,
        coordinator,
        search_term,
        delay_ms=delay_ms,
        worker_id="W1",
        delete_first=delete_first,
        ui_first=ui_first,
    )
    return coordinator.stats()


def delete_matching_tags_parallel(
    email: str,
    password: str,
    search_term: str,
    *,
    coord_db: Path,
    workers: int,
    limit: int | None,
    delay_ms: int,
    headless: bool,
    slow_mo: int,
    tag_id_prefix: str = DEFAULT_TAG_ID_PREFIX,
    id_min: int = PODIO_ID_MIN,
    id_max: int = PODIO_ID_MAX,
    resume: bool = False,
    delete_first: bool = False,
    ui_first: bool = True,
) -> DeleteStats:
    coordinator = TagCoordinator(
        coord_db,
        limit=limit,
        worker_count=workers,
        reset=not resume,
        tag_id_prefix=tag_id_prefix,
        id_min=id_min,
        id_max=id_max,
        delete_first=delete_first,
    )
    log(f"Coord DB: {coord_db}")
    threads: list[threading.Thread] = []
    for worker_id in range(1, workers + 1):
        thread = threading.Thread(
            target=run_browser_worker,
            name=f"reisift-worker-{worker_id}",
            args=(worker_id, email, password, coordinator),
            kwargs={
                "search_term": search_term,
                "headless": headless,
                "slow_mo": slow_mo,
                "delay_ms": delay_ms,
                "delete_first": delete_first,
                "ui_first": ui_first,
            },
            daemon=True,
        )
        threads.append(thread)
        thread.start()
        time.sleep(1.5)

    for thread in threads:
        thread.join()

    return coordinator.stats()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    parser = argparse.ArgumentParser(description="Delete REISift property tags via browser automation.")
    parser.add_argument("--search", default="podio", help='Search term (default: "podio")')
    parser.add_argument("--email", default="", help="Login email (prompted if empty)")
    parser.add_argument("--password", default="", help="Login password (prompted if empty)")
    parser.add_argument("--limit", type=int, default=None, help="Stop after N deletes (spot-check)")
    parser.add_argument("--headless", action="store_true", help="Headless browser (default: visible)")
    parser.add_argument("--slow-mo", type=int, default=150, help="Playwright slow_mo in ms")
    parser.add_argument("--delay", type=int, default=800, help="Pause after each delete in ms")
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Parallel browser sessions (same login). Default: 1.",
    )
    parser.add_argument(
        "--tag-id-prefix",
        default=DEFAULT_TAG_ID_PREFIX,
        help=f'Tag name prefix before numeric ID (default: "{DEFAULT_TAG_ID_PREFIX}")',
    )
    parser.add_argument(
        "--id-min",
        type=int,
        default=PODIO_ID_MIN,
        help=f"Lowest podio ID to probe (default: {PODIO_ID_MIN})",
    )
    parser.add_argument(
        "--id-max",
        type=int,
        default=PODIO_ID_MAX,
        help=f"Highest podio ID to probe (default: {PODIO_ID_MAX})",
    )
    parser.add_argument(
        "--coord-db",
        default="",
        help="SQLite coordinator DB (default: .reisift-tag-coordinator.db in project root)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from existing coordinator DB instead of resetting progress",
    )
    parser.add_argument(
        "--delete-first",
        action="store_true",
        help="Try deleting tags before detaching; sweep UI list for 0-property tags (default with --resume)",
    )
    parser.add_argument(
        "--detach-first",
        action="store_true",
        help="Always detach from properties before attempting delete",
    )
    parser.add_argument(
        "--catalog-probe",
        action="store_true",
        help="Probe pre-seeded catalog IDs instead of working from the live UI tag list",
    )
    parser.add_argument(
        "--tags-folder",
        default=DEFAULT_TAGS_FOLDER_NAME,
        help=f'Tag folder name to open (default: "{DEFAULT_TAGS_FOLDER_NAME}")',
    )
    parser.add_argument(
        "--tags-folder-url",
        default="",
        help="Direct tag folder URL (skips folder discovery; e.g. .../tags/property/folder/<uuid>)",
    )
    args = parser.parse_args()
    load_local_env()
    configure_tags_folder(name=args.tags_folder, url=args.tags_folder_url)
    workers = max(1, args.workers)
    slow_mo = args.slow_mo if workers == 1 else min(args.slow_mo, 80)
    delete_first = args.delete_first or (args.resume and not args.detach_first)
    ui_first = not args.catalog_probe
    delay_ms = 400 if delete_first else args.delay
    coord_db = ensure_coord_db_path(Path(args.coord_db) if args.coord_db else default_coord_db_path())

    email, password = prompt_credentials(args.email or None, args.password or None)

    log("=" * 60)
    log("REISift tag cleanup (Playwright — not Beautiful Soup)")
    log(f"Search  : {args.search!r} (per-tag probe uses {args.tag_id_prefix}{{id}})")
    log(f"ID range: {args.id_min} … {args.id_max} ({args.id_max - args.id_min + 1} slots)")
    log(f"Window  : {'headless' if args.headless else 'visible'}")
    log(f"Workers : {workers}")
    if workers > 6:
        mode = "headless" if args.headless else "visible"
        log(f"Note    : {workers} {mode} Chromium sessions — watch RAM/CPU; dial back if flaky.")
    if args.limit:
        log(f"Limit   : {args.limit}")
    if args.resume:
        log("Resume  : yes (existing coordinator DB)")
    if delete_first:
        log("Mode    : delete-first")
    log(f"Queue   : {'live UI tag list' if ui_first else 'catalog ID probe'}")
    if args.tags_folder_url:
        log(f"Folder  : {args.tags_folder_url}")
    else:
        log(f"Folder  : {args.tags_folder!r}")
    log("=" * 60)

    try:
        if workers == 1:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=args.headless, slow_mo=slow_mo)
                context = browser.new_context(viewport={"width": 1400, "height": 900})
                page = context.new_page()
                login(page, email, password)
                open_property_tags(page)
                stats = delete_matching_tags(
                    page,
                    args.search,
                    coord_db=coord_db,
                    limit=args.limit,
                    delay_ms=args.delay,
                    tag_id_prefix=args.tag_id_prefix,
                    id_min=args.id_min,
                    id_max=args.id_max,
                    resume=args.resume,
                    delete_first=delete_first,
                    ui_first=ui_first,
                )
                browser.close()
        else:
            stats = delete_matching_tags_parallel(
                email,
                password,
                args.search,
                coord_db=coord_db,
                workers=workers,
                limit=args.limit,
                delay_ms=delay_ms,
                headless=args.headless,
                slow_mo=slow_mo,
                tag_id_prefix=args.tag_id_prefix,
                id_min=args.id_min,
                id_max=args.id_max,
                resume=args.resume,
                delete_first=delete_first,
                ui_first=ui_first,
            )
    except KeyboardInterrupt:
        log("\nStopped by user.")
        return 130
    except Exception as exc:
        log(f"\nError: {exc}")
        raise

    log("=" * 60)
    log(f"Deleted : {stats.deleted}")
    log(f"Detached: {stats.detached}")
    if stats.failed:
        log(f"Failed  : {stats.failed}")
    try:
        conn = sqlite3.connect(str(coord_db), timeout=5.0)
        pending = conn.execute(
            "SELECT COUNT(*) FROM tag_catalog "
            "WHERE status IN ('pending', 'detached', 'working', 'detaching', 'deleting')"
        ).fetchone()[0]
        conn.close()
        if pending:
            log(f"Pending : {pending} catalog tag(s) still need work — run again with --resume")
    except Exception:
        pass
    log("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
