#!/usr/bin/env python3
"""Validate the per-month story files under stories/<year>/<year-month>.yaml.

For every YAML file it checks:
  - the file is valid YAML shaped as {crash_record_id: crash entry}, where a
    crash entry is a mapping with a `notes` string and/or a `stories` list
  - each crash entry has at least a `notes` or a `stories` key (either or
    both may be empty; `stories` may be missing entirely if `notes` exists)
  - each crash_record_id exists in db.sqlite (crashes_serving)
  - each crash_record_id sits in the file for its crash month, i.e. the crash's
    crash_date year-month matches the file's <year-month>.yaml name
  - each story entry has at least a title and a url
  - no story url is duplicated within a single crash_record_id
    (the same url appearing under *different* crashes is fine — a story may
    cover more than one crash)

Prints a per-file report to stdout and exits non-zero if any errors are found.

Usage: python3 validate_stories.py
"""

import sqlite3
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent  # repo root (this file lives in scripts/)
DB = ROOT / "db.sqlite"
STORIES = ROOT / "stories"


def crash_date(con, crash_id, cache):
    """Return the crash's 'YYYY-MM-DD HH:MM' crash_date, or None if not in db."""
    if crash_id not in cache:
        row = con.execute(
            "SELECT crash_date FROM crashes_serving WHERE crash_record_id = ? LIMIT 1",
            (crash_id,),
        ).fetchone()
        cache[crash_id] = row[0] if row and row[0] else None
    return cache[crash_id]


def validate_file(path, con, cache):
    """Return (crash_count, story_count, note_count, [error strings]) for one YAML file."""
    errors = []
    file_month = path.stem  # '<year-month>' from <year-month>.yaml, e.g. '2026-05'
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        return None, None, None, [f"invalid YAML: {exc}"]

    if data is None:
        return 0, 0, 0, ["file is empty"]
    if not isinstance(data, dict):
        return (
            None,
            None,
            None,
            [
                f"top level must be a mapping of crash_record_id -> crash entry, got {type(data).__name__}"
            ],
        )

    crash_count = len(data)
    story_count = 0
    note_count = 0

    for crash_id, crash in data.items():
        cdate = crash_date(con, crash_id, cache)
        if cdate is None:
            errors.append(f"{crash_id}: crash_record_id not found in db")
        elif cdate[:7] != file_month:
            errors.append(
                f"{crash_id}: crash_date {cdate} belongs in {cdate[:7]}.yaml, not {file_month}.yaml"
            )

        if not isinstance(crash, dict):
            errors.append(
                f"{crash_id}: value must be a mapping with a `notes` and/or `stories` key, got {type(crash).__name__}"
            )
            continue

        if "notes" not in crash and "stories" not in crash:
            errors.append(f"{crash_id}: must have a `notes` or a `stories` key")

        notes = crash.get("notes")
        if "notes" in crash and notes is not None and not isinstance(notes, str):
            errors.append(
                f"{crash_id}: `notes` must be a string, got {type(notes).__name__}"
            )
        if isinstance(notes, str) and notes.strip():
            note_count += 1

        stories = crash.get("stories")
        if stories is None:  # missing or empty key: nothing more to check
            continue
        if not isinstance(stories, list):
            errors.append(
                f"{crash_id}: `stories` must be a list, got {type(stories).__name__}"
            )
            continue

        seen_urls = {}
        for i, story in enumerate(stories, start=1):
            story_count += 1
            if not isinstance(story, dict):
                errors.append(
                    f"{crash_id}: story #{i} must be a mapping, got {type(story).__name__}"
                )
                continue

            title = story.get("title")
            url = story.get("url")
            if not (isinstance(title, str) and title.strip()):
                errors.append(f"{crash_id}: story #{i} missing title")
            if not (isinstance(url, str) and url.strip()):
                errors.append(f"{crash_id}: story #{i} missing url")
                continue

            if url in seen_urls:
                errors.append(
                    f"{crash_id}: duplicate url within this crash (stories #{seen_urls[url]} and #{i}): {url}"
                )
            else:
                seen_urls[url] = i

    return crash_count, story_count, note_count, errors


def main():
    if not DB.exists():
        print(f"error: database not found at {DB}", file=sys.stderr)
        return 2

    paths = sorted(STORIES.rglob("*.yaml"))
    if not paths:
        print(
            f"no story files found under {STORIES.relative_to(ROOT)}/", file=sys.stderr
        )
        return 1

    con = sqlite3.connect(DB)
    cache = {}
    total_crashes = total_stories = total_notes = total_errors = 0

    try:
        for path in paths:
            crash_count, story_count, note_count, errors = validate_file(
                path, con, cache
            )
            line = (
                f"{path.relative_to(ROOT)}:"
                f"  crashes: {crash_count if crash_count is not None else '?'}"
                f"    stories: {story_count if story_count is not None else '?'}"
            )
            if note_count:
                line += f"    notes: {note_count}"
            print(line)
            if errors:
                print("  errors:")
                for err in errors:
                    print(f"    - {err}")

            total_crashes += crash_count or 0
            total_stories += story_count or 0
            total_notes += note_count or 0
            total_errors += len(errors)
    finally:
        con.close()

    print(
        f"summary: {len(paths)} files, {total_crashes} crashes, {total_stories} stories, {total_notes} notes, {total_errors} errors"
    )
    return 1 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main())
