#!/usr/bin/env python3
"""Replace story `site` domains with display names from reference/domain-lookup.csv.

Walks every stories/<year>/<year-month>.yaml file and, for each story entry
(crash `stories` lists and the top-level __GENERAL__ list alike), replaces a
`site` value matching a `domain` in reference/domain-lookup.csv with that
row's `site_name`. Matching is case-insensitive and ignores a leading 'www.'.
Values with no lookup row — including already-replaced display names — are
left untouched, so the script is idempotent. Domain-looking values that have
no lookup row are reported so the CSV can be extended.

Files are rewritten through format.py's renderer, so they come out formatted.

Pass --dry to report what would change (output prefixed with '(dry)') without
touching any file.

Usage: python3 site_domain_lookup.py [--dry]
"""

import argparse
import csv
import sys

import yaml

from format import (
    COMMENTS_KEY,
    GENERAL_KEY,
    ROOT,
    STORIES,
    render_file,
    valid_structure,
)

LOOKUP_CSV = ROOT / "reference" / "domain-lookup.csv"


def normalize_domain(value):
    """Lowercased, stripped domain with any leading 'www.' removed."""
    domain = value.strip().lower()
    return domain[4:] if domain.startswith("www.") else domain


def load_lookup():
    """domain -> site_name from the reference CSV, keys normalized."""
    lookup = {}
    with open(LOOKUP_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            domain = normalize_domain(row.get("domain") or "")
            name = (row.get("site_name") or "").strip()
            if domain and name:
                lookup[domain] = name
    return lookup


def file_stories(data):
    """Yield every story mapping in one file's data (crash and __GENERAL__ alike)."""
    for key, value in data.items():
        if key == COMMENTS_KEY:
            continue
        stories = value or [] if key == GENERAL_KEY else value.get("stories") or []
        yield from stories


def main(dry=False):
    tag = "(dry) " if dry else ""
    if not LOOKUP_CSV.exists():
        print(f"error: lookup table not found at {LOOKUP_CSV}", file=sys.stderr)
        return 2
    lookup = load_lookup()
    if not lookup:
        print(f"error: no usable rows in {LOOKUP_CSV}", file=sys.stderr)
        return 2

    paths = sorted(STORIES.rglob("*.yaml"))
    if not paths:
        print(
            f"no story files found under {STORIES.relative_to(ROOT)}/", file=sys.stderr
        )
        return 1

    changed_files = 0
    replaced = 0
    unmatched = {}  # domain-looking site values with no lookup row -> count
    for path in paths:
        rel = path.relative_to(ROOT)
        try:
            data = yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            print(
                f"skip {rel}: invalid YAML ({exc.__class__.__name__})", file=sys.stderr
            )
            continue
        if not valid_structure(data):
            print(f"skip {rel}: unexpected structure", file=sys.stderr)
            continue

        file_replaced = 0
        for story in file_stories(data):
            site = story.get("site")
            if not isinstance(site, str) or not site.strip():
                continue
            name = lookup.get(normalize_domain(site))
            if name:
                if story["site"] != name:
                    story["site"] = name
                    file_replaced += 1
            elif "." in site and " " not in site.strip():
                unmatched[normalize_domain(site)] = (
                    unmatched.get(normalize_domain(site), 0) + 1
                )

        if file_replaced:
            if not dry:
                path.write_text(render_file(data))
            print(f"{tag}updated {rel}: {file_replaced} site value(s)")
            changed_files += 1
            replaced += file_replaced

    for domain in sorted(unmatched):
        print(f"no lookup entry for {domain} ({unmatched[domain]} story(s))")

    print(
        f"{tag}site_domain_lookup DONE: {len(paths)} file(s) scanned, "
        f"{changed_files} updated, {replaced} site value(s) replaced"
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry",
        action="store_true",
        help="report what would change without writing any file",
    )
    sys.exit(main(**vars(parser.parse_args())))
