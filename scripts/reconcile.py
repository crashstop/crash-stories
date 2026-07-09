#!/usr/bin/env python3
"""Reconcile story files against external sources (currently db.sqlite).

This is the home for any story-file rewriting that depends on data outside
the file itself; self-contained formatting lives in format.py. For each
stories/<year>/<year-month>.yaml file it:
  - reorders crash records chronologically by their crash_date (from
    db.sqlite), with crashes unknown to the db last, ordered by id
  - derives a `site` wherever one is missing/empty (crash `stories` and
    __GENERAL__ entries alike): the url's domain, swapped for its display
    name from reference/domain-lookup.csv when the domain has a row there

Files are rewritten through format.py's renderer, so a reconciled file also
comes out formatted.

By default only files modified since stories.csv was last written are scanned
(all files when stories.csv doesn't exist); pass --all to scan every file.
Pass --dry to report what would be reordered (output prefixed with '(dry)')
without touching any file.

Usage: python3 reconcile.py [--all] [--dry]
"""

import argparse
import csv
import sqlite3
import sys
from urllib.parse import urlparse

import yaml

from format import (
    COMMENTS_KEY,
    GENERAL_KEY,
    ROOT,
    STORIES,
    modified_since_csv,
    render_file,
    valid_structure,
)

DB = ROOT / "db.sqlite"
LOOKUP_CSV = ROOT / "reference" / "domain-lookup.csv"


def crash_date(con, crash_id, cache):
    """Return the crash's 'YYYY-MM-DD HH:MM' crash_date string, or None."""
    if crash_id not in cache:
        row = con.execute(
            "SELECT crash_date FROM crashes_serving WHERE crash_record_id = ? LIMIT 1",
            (crash_id,),
        ).fetchone()
        cache[crash_id] = row[0] if row and row[0] else None
    return cache[crash_id]


def derive_site(url):
    """Domain of the url with a leading 'www.' stripped, or None if unusable."""
    netloc = urlparse(url).netloc.strip()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc or None


def normalize_domain(value):
    """Lowercased, stripped domain with any leading 'www.' removed."""
    domain = value.strip().lower()
    return domain[4:] if domain.startswith("www.") else domain


def load_lookup():
    """domain -> site_name from reference/domain-lookup.csv, keys normalized.

    Empty when the CSV is absent, so reconciling degrades to raw domains.
    """
    if not LOOKUP_CSV.exists():
        print(
            f"warning: no lookup table at {LOOKUP_CSV.relative_to(ROOT)}; "
            "using raw domains for `site`",
            file=sys.stderr,
        )
        return {}
    lookup = {}
    with open(LOOKUP_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            domain = normalize_domain(row.get("domain") or "")
            name = (row.get("site_name") or "").strip()
            if domain and name:
                lookup[domain] = name
    return lookup


def fill_sites(data, lookup):
    """Derive a missing/empty `site` from each story's url, in place.

    Uses the url's domain, swapped for its display name from
    reference/domain-lookup.csv when the domain has a row there.
    """
    for key, value in data.items():
        if key == COMMENTS_KEY:
            continue
        stories = value or [] if key == GENERAL_KEY else value.get("stories") or []
        for story in stories:
            url = story.get("url")
            if not story.get("site") and isinstance(url, str) and url.strip():
                site = derive_site(url.strip())
                if site:
                    story["site"] = lookup.get(normalize_domain(site), site)


def reorder_crashes(data, con, cache):
    """Return data with crash records sorted by crash_date (unknown last, by id).

    The special __GENERAL__/__COMMENTS__ keys are carried over untouched;
    render_file places them regardless of mapping order.
    """

    def crash_key(crash_id):
        cd = crash_date(con, crash_id, cache)
        return (cd is None, cd or "", crash_id)

    crash_ids = [k for k in data if k not in (COMMENTS_KEY, GENERAL_KEY)]
    ordered = {k: data[k] for k in sorted(crash_ids, key=crash_key)}
    for key in (GENERAL_KEY, COMMENTS_KEY):
        if key in data:
            ordered[key] = data[key]
    return ordered


def main(changed_only=True, dry=False):
    tag = "(dry) " if dry else ""
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
                f"{tag}scanning {len(paths)} of {all_count} story files modified since "
                f"stories.csv (pass --all to scan every file)"
            )
        if not paths:
            return 0

    lookup = load_lookup()
    con = sqlite3.connect(DB)
    cache = {}
    changed = 0
    try:
        for path in paths:
            rel = path.relative_to(ROOT)
            try:
                data = yaml.safe_load(path.read_text())
            except yaml.YAMLError as exc:
                print(
                    f"skip {rel}: invalid YAML ({exc.__class__.__name__})",
                    file=sys.stderr,
                )
                continue

            if not valid_structure(data):
                print(f"skip {rel}: unexpected structure", file=sys.stderr)
                continue

            fill_sites(data, lookup)
            new_text = render_file(reorder_crashes(data, con, cache))
            if new_text != path.read_text():
                if not dry:
                    path.write_text(new_text)
                print(f"{tag}reconciled {rel}")
                changed += 1
            else:
                print(f"{tag}unchanged {rel}")
    finally:
        con.close()

    print(f"{tag}reconcile DONE: {len(paths)} file(s)  scanned, {changed} reconciled")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--all",
        dest="changed_only",
        action="store_false",
        help="scan every story file, not just those modified since stories.csv",
    )
    parser.add_argument(
        "--dry",
        action="store_true",
        help="report what would be reordered without writing any file",
    )
    sys.exit(main(**vars(parser.parse_args())))
