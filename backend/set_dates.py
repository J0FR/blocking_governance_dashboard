"""Rewrite the `SET start_date / end_date / data_end_date` lines of the impact / retention SQL
files with the window that is correct for the day you run it.

    python set_dates.py impact    C:\\path\\impact.sql
    python set_dates.py retention C:\\path\\retention.sql
    python set_dates.py both      C:\\path\\impact.sql C:\\path\\retention.sql

Add --today 2026-11-10 to simulate another run date. The SQL is edited in place
(a .bak copy is kept the first time).
"""
import argparse
import re
import shutil
import sys
from datetime import date
from pathlib import Path

from app.block_impact import query_windows


def patch(path: Path, window: dict) -> list[str]:
    sql = path.read_text(encoding="utf-8")
    changed = []
    for key, value in window.items():
        pat = re.compile(rf"(?im)^(\s*SET\s+{key}\s*=\s*)[0-9\-]+(\s*;)")
        if not pat.search(sql):
            continue  # impact has no data_end_date; the retention query now derives start/end itself
        sql = pat.sub(rf"\g<1>{value}\g<2>", sql)
        changed.append(f"SET {key}={value}")
    if not changed:
        raise SystemExit(f"{path.name}: no SET start_date / end_date / data_end_date line found")
    bak = path.with_suffix(path.suffix + ".bak")
    if not bak.exists():
        shutil.copy(path, bak)
    path.write_text(sql, encoding="utf-8")
    return changed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("which", choices=["impact", "retention", "both"])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--today", help="yyyy-MM-dd (default: today)")
    a = ap.parse_args()
    w = query_windows(date.fromisoformat(a.today) if a.today else None)
    jobs = [("impact", a.files[0]), ("retention", a.files[1] if a.which == "both" else a.files[0])] \
        if a.which == "both" else [(a.which, a.files[0])]
    if a.which == "both" and len(a.files) < 2:
        sys.exit("'both' needs two files: impact.sql retention.sql")
    for name, f in jobs:
        print(f"{name}: {Path(f).name} -> {', '.join(patch(Path(f), w[name]))}")


if __name__ == "__main__":
    main()
