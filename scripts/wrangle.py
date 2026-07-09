#!/usr/bin/env python3
"""Compile every stories/<year>/<year-month>.yaml file into two CSVs.

Each story file is a mapping of crash_record_id -> {notes: ..., stories: [...]}.
Walks all story files and writes:
  - stories.csv: one row per story entry, with the owning crash_record_id in
    the first column followed by the story fields (date, url, title, site,
    description, plus any extra keys that appear), ordered by date,
    crash_record_id, site, title
  - notes.csv: one row per crash-level `notes` entry, with columns
    crash_record_id, crash_yearmonth (the file's YYYY-MM stem), and content,
    ordered by crash_yearmonth, crash_record_id

The crash-level `private_notes` field is deliberately not compiled into
either CSV. A top-level `__COMMENTS__` key (a list of free-text documenter
notes about incidents with no crash_record_id) is ignored entirely. A
top-level `__GENERAL__` key (month-wide stories not tied to any crash record)
is compiled into stories.csv with a blank crash_record_id.

Every (crash_record_id, url) pair — blank crash_record_id included — must be
unique across all files; each duplicated pair gets a warning on stderr:
WARNING: Duplicate crash id + url: [crash_record_id]: [url]

Pass --dry to report what would be written (output prefixed with '(dry)')
without touching either CSV.

Usage: python3 wrangle.py [--dry]
"""

import argparse
import csv
import sys
from datetime import date, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent  # repo root (this file lives in scripts/)
STORIES = ROOT / "stories"
OUT = ROOT / "stories.csv"
NOTES_OUT = ROOT / "notes.csv"
NOTES_COLUMNS = ["crash_record_id", "crash_yearmonth", "content"]
COMMENTS_KEY = "__COMMENTS__"
GENERAL_KEY = "__GENERAL__"

PREFERRED = ["date", "url", "title", "site", "description"]


def to_cell(value):
    """Render a YAML value as a CSV cell string."""
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def count_records(path):
    """Number of data rows in an existing CSV (header excluded), or None if absent."""
    if not path.exists():
        return None
    with open(path, newline="", encoding="utf-8") as f:
        return max(0, sum(1 for _ in csv.reader(f)) - 1)


def change_note(before, after):
    """Describe how a record count changed from a previous run."""
    if before is None:
        return "new file"
    if before == after:
        return f"unchanged from previous {before}"
    return f"was {before}, {after - before:+d}"


def main(dry=False):
    tag = "(dry) " if dry else ""
    paths = sorted(STORIES.rglob("*.yaml"))
    if not paths:
        print(
            f"no story files found under {STORIES.relative_to(ROOT)}/", file=sys.stderr
        )
        return 1

    rows = []
    notes_rows = []
    extra_keys = []  # any story keys beyond PREFERRED, in first-seen order
    for path in paths:
        rel = path.relative_to(ROOT)
        try:
            data = yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            print(
                f"skip {rel}: invalid YAML ({exc.__class__.__name__})", file=sys.stderr
            )
            continue
        if not isinstance(data, dict):
            print(f"skip {rel}: unexpected structure", file=sys.stderr)
            continue

        for crash_id, crash in data.items():
            if crash_id == COMMENTS_KEY:  # documenter notes, not a crash record
                continue
            if crash_id == GENERAL_KEY:  # month-wide stories with no crash record
                out_id = ""
                stories = crash or []
            else:
                out_id = crash_id
                if not isinstance(crash, dict):
                    print(
                        f"skip {rel}: {crash_id} value is not a mapping",
                        file=sys.stderr,
                    )
                    continue
                notes = crash.get("notes")
                if isinstance(notes, str) and notes.strip():
                    notes_rows.append(
                        {
                            "crash_record_id": crash_id,
                            "crash_yearmonth": path.stem,
                            "content": notes,
                        }
                    )

                stories = crash.get("stories") or []
            if not isinstance(stories, list):
                print(
                    f"skip {rel}: {crash_id} `stories` is not a list", file=sys.stderr
                )
                continue
            for story in stories:
                if not isinstance(story, dict):
                    print(
                        f"skip {rel}: {crash_id} has a non-mapping story entry",
                        file=sys.stderr,
                    )
                    continue
                row = {"crash_record_id": out_id}
                for k, v in story.items():
                    row[k] = v
                    if k not in PREFERRED and k not in extra_keys:
                        extra_keys.append(k)
                rows.append(row)

    # to_cell renders dates/datetimes as ISO strings, so mixed date types
    # still compare chronologically (and match the written cell values)
    rows.sort(
        key=lambda r: tuple(
            to_cell(r.get(c)) for c in ("date", "crash_record_id", "site", "title")
        )
    )
    notes_rows.sort(key=lambda r: (r["crash_yearmonth"], r["crash_record_id"]))

    pair_counts = {}  # (crash_record_id, url) -> occurrences, across all files
    for row in rows:
        pair = (row["crash_record_id"], to_cell(row.get("url")))
        pair_counts[pair] = pair_counts.get(pair, 0) + 1
    for crash_id, url in sorted(p for p, n in pair_counts.items() if n > 1):
        print(f"WARNING: Duplicate crash id + url: {crash_id}: {url}", file=sys.stderr)

    prior_stories = count_records(OUT)
    prior_notes = count_records(NOTES_OUT)

    if not dry:
        columns = ["crash_record_id"] + PREFERRED + extra_keys
        with open(OUT, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            for row in rows:
                writer.writerow([to_cell(row.get(c)) for c in columns])

        with open(NOTES_OUT, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(NOTES_COLUMNS)
            for row in notes_rows:
                writer.writerow([to_cell(row[c]) for c in NOTES_COLUMNS])

    # __GENERAL__ rows carry a blank id, so they never count as a crash record
    crashes_with_stories = {
        row["crash_record_id"] for row in rows if row["crash_record_id"]
    }
    general_count = sum(1 for row in rows if not row["crash_record_id"])
    print(
        f"{tag}wrote {OUT.relative_to(ROOT)}: {len(rows)} stories ({general_count} general) "
        f"across {len(crashes_with_stories)} crash records from {len(paths)} files "
        f"({change_note(prior_stories, len(rows))})"
    )
    print(
        f"{tag}wrote {NOTES_OUT.relative_to(ROOT)}: {len(notes_rows)} notes from {len(paths)} files "
        f"({change_note(prior_notes, len(notes_rows))})"
    )
    print("wrangle DONE")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry",
        action="store_true",
        help="report what would be written without touching either CSV",
    )
    sys.exit(main(**vars(parser.parse_args())))
