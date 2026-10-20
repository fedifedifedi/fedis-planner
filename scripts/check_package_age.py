"""Audit installed Python packages: flag any version published less than N days ago.

Usage: backend/.venv/Scripts/python.exe scripts/check_package_age.py [--days 14]
Exit code 1 if at least one package is too recent (or its date cannot be found).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from importlib.metadata import distributions

IGNORED = {"pip", "setuptools", "wheel"}


def fetch_upload_date(name: str, version: str, retries: int = 5) -> datetime | None:
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                files = json.load(resp)["urls"]
            if not files:
                return None
            return min(datetime.fromisoformat(f["upload_time_iso_8601"].replace("Z", "+00:00")) for f in files)
        except Exception:
            if attempt == retries - 1:
                return None
            time.sleep(2 * (attempt + 1))
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14)
    args = parser.parse_args()

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    too_recent: list[str] = []
    for dist in sorted(distributions(), key=lambda d: d.metadata["Name"].lower()):
        name, version = dist.metadata["Name"], dist.version
        if name.lower() in IGNORED:
            continue
        uploaded = fetch_upload_date(name, version)
        if uploaded is None:
            status = "UNKNOWN"
            too_recent.append(f"{name}=={version} (date not found)")
        elif uploaded > cutoff:
            status = "TOO RECENT"
            too_recent.append(f"{name}=={version} ({uploaded:%Y-%m-%d})")
        else:
            status = "ok"
        date_str = f"{uploaded:%Y-%m-%d}" if uploaded else "?"
        print(f"{status:<10} {name}=={version}  {date_str}")

    if too_recent:
        print(f"\n{len(too_recent)} package(s) violate the {args.days}-day rule:")
        for line in too_recent:
            print(f"  - {line}")
        return 1
    print(f"\nAll packages published more than {args.days} days ago.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
