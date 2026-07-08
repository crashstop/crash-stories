#!/usr/bin/env python3
"""Compile every stories/<year>/<year-month>.yaml file into two CSVs.

Each story file is a mapping of crash_record_id -> {notes: ..., stories: [...]}.
Walks all story files and writes:
  - stories.csv: one row per story entry, with the owning crash_record_id in
    the first column followed by the story fields (url, title, site, date,
    description, plus any extra keys that appear)
  - notes.csv: one row per crash-level `notes` entry, with columns
    crash_record_id, crash_yearmonth (the file's YYYY-MM stem), and content

Usage: python3 wrangle_stories.py
"""

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

PREFERRED = ["url", "title", "site", "date", "description"]


def to_cell(value):
    """Render a YAML value as a CSV cell string."""
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def main():
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
            if not isinstance(crash, dict):
                print(f"skip {rel}: {crash_id} value is not a mapping", file=sys.stderr)
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
                row = {"crash_record_id": crash_id}
                for k, v in story.items():
                    row[k] = v
                    if k not in PREFERRED and k not in extra_keys:
                        extra_keys.append(k)
                rows.append(row)

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

    print(f"wrote {OUT.relative_to(ROOT)}: {len(rows)} stories from {len(paths)} files")
    print(
        f"wrote {NOTES_OUT.relative_to(ROOT)}: {len(notes_rows)} notes from {len(paths)} files"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
