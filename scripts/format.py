#!/usr/bin/env python3
"""Normalize the formatting of every stories/<year>/<year-month>.yaml file.

Each file is a mapping of crash_record_id -> crash entry, where a crash entry
holds optional `notes` and `private_notes` strings and/or an optional
`stories` list.

Only self-contained formatting happens here — nothing that needs db.sqlite or
any other external source. Crash records keep their original file order and
missing `site` values stay missing; chronological reordering by crash_date (a
db lookup) and site derivation from the url's domain are reconcile.py's job.

For each file it rewrites:
  - crash-level keys in a fixed order: notes, private_notes, stories (a
    missing key stays missing; any other keys are preserved and kept after
    these)
  - within each crash, stories ordered chronologically by their `date`, with
    dateless stories last and date ties broken by url alphabetically
  - story-entry keys in a fixed order: url, title, site, date, description
    (any other keys are preserved and kept after these)
  - a blank line between consecutive story entries within a crash
  - a blank line between crashes
  - an optional top-level `__GENERAL__` list (month-wide stories not tied to
    any crash record, same schema as crash `stories` entries) moved to the top
    of the file, its stories ordered and key-ordered like crash stories
  - an optional top-level `__COMMENTS__` list (free-text documenter notes
    about incidents with no crash_record_id) moved to the bottom of the file,
    its entries kept in their original order

Content is otherwise preserved. Idempotent: running twice yields the same output.

By default only files modified since stories.csv was last written are scanned
(all files when stories.csv doesn't exist); pass --all to scan every file.
Pass --dry to report what would be reformatted (output prefixed with '(dry)')
without touching any file.

Usage: python3 format.py [--all] [--dry]
"""

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent  # repo root (this file lives in scripts/)
STORIES = ROOT / "stories"
CSV = ROOT / "stories.csv"


def modified_since_csv(paths):
    """Paths modified after stories.csv; all of them when stories.csv is absent."""
    if not CSV.exists():
        return paths
    cutoff = CSV.stat().st_mtime
    return [p for p in paths if p.stat().st_mtime > cutoff]


KEY_ORDER = ["url", "title", "site", "date", "description"]
COMMENTS_KEY = "__COMMENTS__"
GENERAL_KEY = "__GENERAL__"


class BlockDumper(yaml.SafeDumper):
    """SafeDumper that renders multi-line strings as literal block scalars."""


def _represent_str(dumper, data):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


BlockDumper.add_representer(str, _represent_str)


def _to_naive_utc(value):
    """Coerce a story `date` (str/date/datetime/None) to a naive-UTC datetime.

    Returns None when absent or unparseable so it can be sorted last. Aware
    values are converted to UTC and stripped of tzinfo so naive and aware
    dates stay mutually comparable.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return (
            value.astimezone(timezone.utc).replace(tzinfo=None)
            if value.tzinfo
            else value
        )
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            try:
                dt = datetime.fromisoformat(s[:10])  # fall back to the date prefix
            except ValueError:
                return None
        return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
    return None


def story_sort_key(story):
    """Chronological story order: dated first, dateless last, url as tiebreak."""
    dt = _to_naive_utc(story.get("date"))
    url = story.get("url") if isinstance(story.get("url"), str) else ""
    return (dt is None, dt or datetime.min, url)


def order_story(story):
    """Return the story dict with keys in KEY_ORDER."""
    ordered = {k: story[k] for k in KEY_ORDER if k in story}
    for k, v in story.items():  # keep any unexpected keys, after the known ones
        ordered.setdefault(k, v)
    return ordered


def render_story(story, indent="    "):
    """Dump one story mapping and indent it as a '<indent>- ...' block sequence item."""
    dumped = yaml.dump(
        order_story(story),
        Dumper=BlockDumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=4096,
    ).rstrip("\n")
    lines = dumped.split("\n")
    out = [indent + "- " + lines[0]]
    # uniform +2 keeps block scalars valid; empty lines stay empty (no trailing ws)
    out += [indent + "  " + line if line else "" for line in lines[1:]]
    return "\n".join(out)


def _dump_indented(mapping):
    """Dump a mapping and indent it two spaces, as crash-entry key lines."""
    dumped = yaml.dump(
        mapping,
        Dumper=BlockDumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=4096,
    ).rstrip("\n")
    return ["  " + line if line else "" for line in dumped.split("\n")]


def render_crash(crash_id, crash):
    """Render one crash_id -> {notes, private_notes, stories, ...} entry as a text block."""
    if not crash:
        return f"{crash_id}: {{}}"

    lines = [f"{crash_id}:"]
    for key in ("notes", "private_notes"):
        if key in crash:
            lines += _dump_indented({key: crash[key]})

    if "stories" in crash:
        stories = crash["stories"] or []
        if not stories:
            lines.append("  stories: []")
        else:
            lines.append("  stories:")
            lines.append(
                "\n\n".join(
                    render_story(s) for s in sorted(stories, key=story_sort_key)
                )
            )

    extras = {
        k: v for k, v in crash.items() if k not in ("notes", "private_notes", "stories")
    }
    if extras:
        lines += _dump_indented(extras)
    return "\n".join(lines)


def render_general(stories):
    """Render the top-level __GENERAL__ story list, ordered like crash stories."""
    if not stories:
        return f"{GENERAL_KEY}: []"
    body = "\n\n".join(
        render_story(s, indent="  ") for s in sorted(stories, key=story_sort_key)
    )
    return f"{GENERAL_KEY}:\n{body}"


def render_comments(comments):
    """Render the top-level __COMMENTS__ string list, entries in original order."""
    if not comments:
        return f"{COMMENTS_KEY}: []"
    lines = [f"{COMMENTS_KEY}:"]
    for comment in comments:
        dumped = yaml.dump(
            [comment],
            Dumper=BlockDumper,
            allow_unicode=True,
            default_flow_style=False,
            width=4096,
        ).rstrip("\n")
        item = dumped.split("\n")
        lines.append("  " + item[0])
        lines += ["  " + line if line else "" for line in item[1:]]
    return "\n".join(lines)


def render_file(data):
    """Build the formatted text for one file's {crash_id: {stories: [...]}} mapping.

    Crashes render in the mapping's iteration order (reconcile.py passes a
    chronologically reordered mapping); stories within a crash are ordered by
    story_sort_key. A __GENERAL__ list goes first, a __COMMENTS__ list last,
    regardless of where they sit in the mapping.
    """
    blocks = []
    if GENERAL_KEY in data:
        blocks.append(render_general(data[GENERAL_KEY] or []))
    blocks += [
        render_crash(crash_id, crash)
        for crash_id, crash in data.items()
        if crash_id not in (COMMENTS_KEY, GENERAL_KEY)
    ]
    if COMMENTS_KEY in data:
        blocks.append(render_comments(data[COMMENTS_KEY] or []))
    return "\n\n".join(blocks) + "\n"


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


def main(changed_only=True, dry=False):
    tag = "(dry) " if dry else ""
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
                f"{CSV.name} (pass --all to scan every file)"
            )
        if not paths:
            print(f"{tag}format DONE: 0 file(s) scanned, 0 reformatted")
            return 0

    changed = 0
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

        new_text = render_file(data)
        if new_text != path.read_text():
            if not dry:
                path.write_text(new_text)
            print(f"{tag}formatted {rel}")
            changed += 1
        else:
            print(f"{tag}unchanged {rel}")

    print(f"{tag}format DONE: {len(paths)} file(s) scanned, {changed} reformatted")
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
        help="report what would be reformatted without writing any file",
    )
    sys.exit(main(**vars(parser.parse_args())))
