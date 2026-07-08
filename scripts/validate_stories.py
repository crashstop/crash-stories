#!/usr/bin/env python3
"""Validate the per-month story files under stories/<year>/<year-month>.yaml.

For every YAML file it checks:
  - the file is valid YAML shaped as {crash_record_id: crash entry}, where a
    crash entry is a mapping with `notes` and/or `private_notes` strings
    and/or a `stories` list
  - each crash entry has at least one of the keys `notes`, `private_notes`,
    `stories` (any of them may be empty; the others may be missing entirely)
  - each crash_record_id exists in db.sqlite (crashes_serving)
  - each crash_record_id sits in the file for its crash month, i.e. the crash's
    crash_date year-month matches the file's <year-month>.yaml name
  - each story entry has at least a title and a url
  - no story url is duplicated within a single crash_record_id
    (the same url appearing under *different* crashes is fine — a story may
    cover more than one crash)

By default only files modified since stories.csv was last written are checked
(all files when stories.csv doesn't exist); pass --all to check every file.

Prints a per-file report to stdout and exits non-zero if any errors are found.

Usage: python3 validate_stories.py [--all]
"""

import argparse
import sqlite3
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent  # repo root (this file lives in scripts/)
DB = ROOT / "db.sqlite"
STORIES = ROOT / "stories"
CSV = ROOT / "stories.csv"


def modified_since_csv(paths):
    """Paths modified after stories.csv; all of them when stories.csv is absent."""
    if not CSV.exists():
        return paths
    cutoff = CSV.stat().st_mtime
    return [p for p in paths if p.stat().st_mtime > cutoff]


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
    """Return ({count name: count}, [error strings]) for one YAML file.

    The counts dict has keys: crashes, stories, notes, private_notes. It is
    None when the file couldn't be read as a top-level mapping at all.
    """
    errors = []
    file_month = path.stem  # '<year-month>' from <year-month>.yaml, e.g. '2026-05'
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        return None, [f"invalid YAML: {exc}"]

    counts = {"crashes": 0, "stories": 0, "notes": 0, "private_notes": 0}
    if data is None:
        return counts, ["file is empty"]
    if not isinstance(data, dict):
        return None, [
            f"top level must be a mapping of crash_record_id -> crash entry, got {type(data).__name__}"
        ]

    counts["crashes"] = len(data)

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
                f"{crash_id}: value must be a mapping with a `notes`, `private_notes`, and/or `stories` key, got {type(crash).__name__}"
            )
            continue

        if not any(k in crash for k in ("notes", "private_notes", "stories")):
            errors.append(
                f"{crash_id}: must have a `notes`, `private_notes`, or `stories` key"
            )

        for key in ("notes", "private_notes"):
            value = crash.get(key)
            if key in crash and value is not None and not isinstance(value, str):
                errors.append(
                    f"{crash_id}: `{key}` must be a string, got {type(value).__name__}"
                )
            if isinstance(value, str) and value.strip():
                counts[key] += 1

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
            counts["stories"] += 1
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

    return counts, errors


def main(changed_only=True):
    if not DB.exists():
        print(f"error: database not found at {DB}", file=sys.stderr)
        return 2

    paths = sorted(STORIES.rglob("*.yaml"))
    if not paths:
        print(
            f"no story files found under {STORIES.relative_to(ROOT)}/", file=sys.stderr
        )
        return 1

    if changed_only:
        all_count = len(paths)
        paths = modified_since_csv(paths)
        if len(paths) < all_count:
            print(
                f"checking {len(paths)} of {all_count} story files modified since "
                f"{CSV.name} (pass --all to check every file)"
            )
        if not paths:
            return 0

    con = sqlite3.connect(DB)
    cache = {}
    totals = {"crashes": 0, "stories": 0, "notes": 0, "private_notes": 0}
    total_errors = 0

    try:
        for path in paths:
            counts, errors = validate_file(path, con, cache)
            if counts is None:
                line = f"{path.relative_to(ROOT)}:  crashes: ?    stories: ?"
            else:
                line = (
                    f"{path.relative_to(ROOT)}:"
                    f"  crashes: {counts['crashes']}"
                    f"    stories: {counts['stories']}"
                )
                for key in ("notes", "private_notes"):  # only shown when present
                    if counts[key]:
                        line += f"    {key}: {counts[key]}"
                for key in totals:
                    totals[key] += counts[key]
            print(line)
            if errors:
                print("  errors:")
                for err in errors:
                    print(f"    - {err}")

            total_errors += len(errors)
    finally:
        con.close()

    print(
        f"summary: {len(paths)} files, {totals['crashes']} crashes, {totals['stories']} stories, "
        f"{totals['notes']} notes, {totals['private_notes']} private_notes, {total_errors} errors"
    )
    return 1 if total_errors else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--all",
        dest="changed_only",
        action="store_false",
        help="check every story file, not just those modified since stories.csv",
    )
    sys.exit(main(**vars(parser.parse_args())))
