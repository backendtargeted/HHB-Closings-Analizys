"""Refresh only the exclusion-policy appendix, preserving the operator contract."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "BUYBOX.md"
POLICY = ROOT / "backend" / "app" / "services" / "buybox_policy.json"
START = "<!-- BUYBOX_POLICY_APPENDIX_START -->"
END = "<!-- BUYBOX_POLICY_APPENDIX_END -->"


def main() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    current = OUT.read_text(encoding="utf-8")
    if current.count(START) != 1 or current.count(END) != 1:
        raise ValueError("Expected exactly one policy appendix marker pair; refusing to overwrite contract")
    before, rest = current.split(START, 1)
    _, after = rest.split(END, 1)
    zips = sorted(set(policy["excluded_zips"]))
    cities = sorted(set(policy["excluded_cities"]))
    appendix = (
        "\n\n## Exclusion-policy appendix\n\n"
        f"Generated from `buybox_policy.json`: {len(zips)} ZIPs and {len(cities)} city keys.\n\n"
        "### Excluded ZIPs\n\n"
        + ", ".join(f"`{z}`" for z in zips)
        + "\n\n### Excluded city keys\n\n"
        + "\n".join(f"- {city}" for city in cities)
        + "\n\n"
    )
    OUT.write_text(before + START + appendix + END + after, encoding="utf-8")
    print(f"Updated policy appendix: {len(zips)} ZIPs, {len(cities)} city keys")


if __name__ == "__main__":
    main()
