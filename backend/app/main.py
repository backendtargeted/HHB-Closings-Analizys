"""
Flask application main file
"""

import os
from pathlib import Path
from typing import Optional

from flask import Flask, abort, request, send_from_directory
from flask_cors import CORS

from .api.routes import api_bp, load_reports_from_disk
from .api.patches import patches_bp


def _frontend_dist() -> Optional[Path]:
    """When FRONTEND_DIST is set and contains index.html, Flask serves the SPA (production bundle)."""
    raw = os.environ.get("FRONTEND_DIST", "").strip()
    if not raw:
        return None
    p = Path(raw).resolve()
    if p.is_dir() and (p / "index.html").is_file():
        return p
    return None


def _try_serve_spa(path_within_dist: str):
    dist = _frontend_dist()
    if not dist:
        return None
    if path_within_dist:
        target = (dist / path_within_dist).resolve()
        try:
            target.relative_to(dist)
        except ValueError:
            abort(404)
        if target.is_file():
            return send_from_directory(str(dist), path_within_dist)
    return send_from_directory(str(dist), "index.html")


app = Flask(__name__)

# Align with Docker/nginx `client_max_body_size` (512m) for multipart uploads
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024

# Load persisted reports from volume into memory
load_reports_from_disk()
app.config["JSON_SORT_KEYS"] = False

# CORS: localhost defaults for dev; set CORS_ORIGINS for split Easypanel (comma-separated) or * for any origin.
_cors_raw = os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").strip()
if _cors_raw == "*":
    CORS(
        app,
        origins="*",
        allow_headers=["*"],
        methods=["GET", "POST", "OPTIONS"],
    )
else:
    _cors_list = [o.strip() for o in _cors_raw.split(",") if o.strip()]
    if not _cors_list:
        _cors_list = ["http://localhost:3000", "http://localhost:5173"]
    CORS(
        app,
        origins=_cors_list,
        supports_credentials=True,
        allow_headers=["*"],
        methods=["GET", "POST", "OPTIONS"],
    )

# Register API blueprints
app.register_blueprint(api_bp, url_prefix="/api")
app.register_blueprint(patches_bp, url_prefix="/api/patches")


@app.route("/health", methods=["GET", "HEAD"])
def health_check():
    """Health check endpoint (HEAD for reverse proxies / load balancers)."""
    if request.method == "HEAD":
        return "", 200
    return {"status": "healthy"}


@app.route("/", methods=["GET"])
def root():
    """Serve SPA when bundled; otherwise JSON root for API-only containers."""
    spa = _try_serve_spa("")
    if spa is not None:
        return spa
    return {"message": "Contact Attribution Analysis API", "version": "1.0.0"}


@app.route("/<path:path>", methods=["GET"])
def spa_static(path: str):
    """
    Vite assets and client-side routes. Must not shadow /api/* (blueprints register first).
    """
    if path.startswith("api"):
        abort(404)
    spa = _try_serve_spa(path)
    if spa is not None:
        return spa
    abort(404)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
