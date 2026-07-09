#!/usr/bin/env python3
"""Shared paths, schema constants, and helpers for the story-file scripts.

Everything here is used by two or more of format.py, lint.py, reconcile.py,
and wrangle.py: the repo paths, the special top-level YAML keys, the
changed-only file scan, the schema gate (valid_structure), and the shared
per-file plumbing (load, compare-and-rewrite, story iteration, db lookup).
"""

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent  # repo root (this file lives in scripts/)
STORIES = ROOT / "stories"
DB = ROOT / "db.sqlite"
STORIES_CSV = ROOT / "stories.csv"

COMMENTS_KEY = "__COMMENTS__"
GENERAL_KEY = "__GENERAL__"


def modified_since_csv(paths):
    """Paths modified after stories.csv; all of them when stories.csv is absent."""
    if not STORIES_CSV.exists():
        return paths
    cutoff = STORIES_CSV.stat().st_mtime
    return [p for p in paths if p.stat().st_mtime > cutoff]


def story_paths(changed_only=True, verb="scan", verbing="scanning", tag=""):
    """Every story yaml path — or, when changed_only, just those modified
    since stories.csv (with the explanatory line the scripts print).

    Exits with status 1 when no story files exist at all.
    """
    paths = sorted(STORIES.rglob("*.yaml"))
    if not paths:
        print(
            f"no story files found under {STORIES.relative_to(ROOT)}/", file=sys.stderr
        )
        raise SystemExit(1)
    if changed_only:
        all_count = len(paths)
        paths = modified_since_csv(paths)
        if len(paths) < all_count:
            print(
                f"{tag}{verbing} {len(paths)} of {all_count} story files modified since "
                f"{STORIES_CSV.name} (pass --all to {verb} every file)"
            )
    return paths


def valid_structure(data):
    """True when data is {crash_id: mapping} plus optional __COMMENTS__ (string
    list) and __GENERAL__ (story-mapping list) keys."""
    if not isinstance(data, dict):
        return False
    for key, value in data.items():
        if key == COMMENTS_KEY:
            comments = value or []
            if not isinstance(comments, list) or not all(
                isinstance(c, str) for c in comments
            ):
                return False
            continue
        if key == GENERAL_KEY:
            general = value or []
            if not isinstance(general, list) or not all(
                isinstance(s, dict) for s in general
            ):
                return False
            continue
        if not isinstance(value, dict):
            return False
        stories = value.get("stories") or []
        if not isinstance(stories, list) or not all(
            isinstance(s, dict) for s in stories
        ):
            return False
    return True


def load_story_file(path):
    """Parse one story yaml, or None (with a stderr skip note) when it is
    invalid YAML or fails valid_structure."""
    rel = path.relative_to(ROOT)
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        print(f"skip {rel}: invalid YAML ({exc.__class__.__name__})", file=sys.stderr)
        return None
    if not valid_structure(data):
        print(f"skip {rel}: unexpected structure", file=sys.stderr)
        return None
    return data


def rewrite_file(path, new_text, verb, dry=False, tag=""):
    """Write new_text when it differs from the file; report either way.

    Returns 1 when the file changed (or would have, under dry), else 0, so
    callers can sum it into their changed counter.
    """
    rel = path.relative_to(ROOT)
    if new_text != path.read_text():
        if not dry:
            path.write_text(new_text)
        print(f"{tag}{verb} {rel}")
        return 1
    print(f"{tag}unchanged {rel}")
    return 0


def iter_stories(data):
    """Yield (crash_record_id, story) for every story mapping in one file's
    data — crash `stories` lists and the top-level __GENERAL__ list alike.
    __GENERAL__ stories carry a blank id; __COMMENTS__ is skipped.

    Assumes data already passed valid_structure.
    """
    for key, value in data.items():
        if key == COMMENTS_KEY:
            continue
        if key == GENERAL_KEY:
            for story in value or []:
                yield "", story
        else:
            for story in value.get("stories") or []:
                yield key, story


def crash_date(con, crash_id, cache):
    """Return the crash's 'YYYY-MM-DD HH:MM' crash_date from db.sqlite, or None."""
    if crash_id not in cache:
        row = con.execute(
            "SELECT crash_date FROM crashes_serving WHERE crash_record_id = ? LIMIT 1",
            (crash_id,),
        ).fetchone()
        cache[crash_id] = row[0] if row and row[0] else None
    return cache[crash_id]
