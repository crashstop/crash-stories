#!/usr/bin/env python3
"""Seed a stub entry for every fatal crash into stories/<year>/<year-month>.yaml.

Queries crashes_serving for every crash with fatal_tally > 0 (newest first) and
builds a stub_label from the crash data (date, address + neighborhood, casualty
counts, "category: primary cause"). For each crash:

  - if stories/YYYY/YYYY-MM.yaml for the crash month doesn't exist, create it
  - if the crash_record_id isn't already a key in that file, append an entry
    whose `private_notes` is the stub-notice line plus the stub_label

Existing files are appended to as text (never re-dumped), so hand-edited
formatting elsewhere in a file is left untouched. Entries land in crash_date
DESC order, not file-chronological order — run validate/lint afterwards.

Usage: python3 _oldstuff/scaffold-stubs.py
"""

import sqlite3
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent  # repo root (this file lives in _oldstuff/)
DB = ROOT / "db.sqlite"
STORIES = ROOT / "stories"

STUB_NOTICE = "This entry is just a stub, pre-filled with basic info from the crash data:\n"

# IFNULL on neighborhood_id only: it's the one concatenated column that is ever
# NULL (10 fatal crashes as of 2026-07), and a bare NULL would null out the
# whole stub_label.
QUERY = """
SELECT
    crash_date
    || char(10) || address  || ' ' || IFNULL(REPLACE(neighborhood_id, '-', ' '), '')
    || char(10) || fatal_tally || ' fatalities, '
        || (injured_tally + incap_tally) || ' injured'
    || char(10) || category || ': ' || cause_prim AS stub_label

        , *
FROM crashes_serving
WHERE fatal_tally > 0
ORDER BY
    crash_date DESC
"""


class _Dumper(yaml.SafeDumper):
    pass


def _repr_str(dumper, data):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _repr_str)


def entry_text(crash_id, private_notes):
    """One appendable YAML fragment for a single crash entry.

    The key line is written by hand: pyyaml refuses simple keys of 128+ chars
    and would emit the crash_record_id hashes in explicit `? key` style,
    unlike the plain `hash:` keys used in the hand-written files.
    """
    body = yaml.dump(
        {"private_notes": private_notes},
        Dumper=_Dumper,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=10**6,
    )
    indented = "".join(
        "  " + line if line.strip() else line for line in body.splitlines(keepends=True)
    )
    return f"{crash_id}:\n{indented}"


def existing_ids(path):
    """Set of crash_record_id keys already in a story file, or None if unreadable."""
    if not path.exists():
        return set()
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        print(
            f"skip {path.relative_to(ROOT)}: invalid YAML ({exc.__class__.__name__})",
            file=sys.stderr,
        )
        return None
    if data is None:
        return set()
    if not isinstance(data, dict):
        print(f"skip {path.relative_to(ROOT)}: unexpected structure", file=sys.stderr)
        return None
    return set(data.keys())


def main():
    if not DB.exists():
        print(f"error: database not found at {DB}", file=sys.stderr)
        return 2

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(QUERY).fetchall()
    finally:
        con.close()

    # Group by target file, preserving the query's crash_date DESC order.
    by_file = {}
    for row in rows:
        yearmonth = row["crash_date"][:7]
        path = STORIES / yearmonth[:4] / f"{yearmonth}.yaml"
        by_file.setdefault(path, []).append(row)

    added = skipped = created = 0
    for path, file_rows in sorted(by_file.items()):
        ids = existing_ids(path)
        if ids is None:
            skipped += len(file_rows)
            continue

        fresh = [r for r in file_rows if r["crash_record_id"] not in ids]
        skipped += len(file_rows) - len(fresh)
        if not fresh:
            continue

        is_new = not path.exists()
        text = path.read_text() if not is_new else ""
        if text and not text.endswith("\n"):
            text += "\n"

        chunks = []
        for row in fresh:
            notes = STUB_NOTICE + (row["stub_label"] or "")
            chunks.append(entry_text(row["crash_record_id"], notes))
        text += ("\n" if text else "") + "\n".join(chunks)

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

        added += len(fresh)
        if is_new:
            created += 1
        label = "created" if is_new else "updated"
        print(f"{label} {path.relative_to(ROOT)}: +{len(fresh)} stub entries")

    print(
        f"summary: {len(rows)} fatal crashes, {added} stubs added "
        f"({created} new files), {skipped} already present or skipped"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
