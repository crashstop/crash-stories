#!/usr/bin/env python3
"""Compile every stories/<year>/<year-month>.yaml file into a single CSV.

Walks all story files and writes one row per story entry to
stories/compiled-stories.csv, with the owning crash_record_id in the first
column followed by the story fields (url, title, site, date, description, plus
any extra keys that appear).

Usage: python3 compile_stories.py
"""

import csv
import sys
from datetime import date, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent  # repo root (this file lives in scripts/)
STORIES = ROOT / "stories"
OUT = ROOT / "stories.csv"

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

        for crash_id, stories in data.items():
            if not isinstance(stories, list):
                print(f"skip {rel}: {crash_id} value is not a list", file=sys.stderr)
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

    print(f"wrote {OUT.relative_to(ROOT)}: {len(rows)} stories from {len(paths)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
