#!/usr/bin/env python3
"""Normalize the formatting of every stories/<year>/<year-month>.yaml file.

For each file it rewrites:
  - crash records ordered chronologically by their crash_date (from db.sqlite)
  - within each crash, stories ordered chronologically by their `date`, with
    dateless stories last and date ties broken by url alphabetically
  - story-entry keys in a fixed order: url, title, site, date, description
    (any other keys are preserved and kept after these)
  - a `site` derived from the url's domain wherever one is missing/empty
  - a blank line between consecutive story entries within a crash
  - a blank line between crashes

Content is otherwise preserved. Idempotent: running twice yields the same output.

Usage: python3 formatter.py
"""

import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parent.parent  # repo root (this file lives in scripts/)
DB = ROOT / "db.sqlite"
STORIES = ROOT / "stories"

KEY_ORDER = ["url", "title", "site", "date", "description"]


class BlockDumper(yaml.SafeDumper):
    """SafeDumper that renders multi-line strings as literal block scalars."""


def _represent_str(dumper, data):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


BlockDumper.add_representer(str, _represent_str)


def derive_site(url):
    """Domain of the url with a leading 'www.' stripped, or None if unusable."""
    netloc = urlparse(url).netloc.strip()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc or None


def crash_date(con, crash_id, cache):
    """Return the crash's 'YYYY-MM-DD HH:MM' crash_date string, or None."""
    if crash_id not in cache:
        row = con.execute(
            "SELECT crash_date FROM crashes_serving WHERE crash_record_id = ? LIMIT 1",
            (crash_id,),
        ).fetchone()
        cache[crash_id] = row[0] if row and row[0] else None
    return cache[crash_id]


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
    """Return the story dict with keys in KEY_ORDER and a derived site if missing."""
    result = dict(story)

    url = result.get("url")
    if not result.get("site") and isinstance(url, str) and url.strip():
        site = derive_site(url.strip())
        if site:
            result["site"] = site

    ordered = {k: result[k] for k in KEY_ORDER if k in result}
    for k, v in result.items():  # keep any unexpected keys, after the known ones
        ordered.setdefault(k, v)
    return ordered


def render_story(story):
    """Dump one story mapping and indent it as a '  - ...' block sequence item."""
    dumped = yaml.dump(
        order_story(story),
        Dumper=BlockDumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=4096,
    ).rstrip("\n")
    lines = dumped.split("\n")
    out = ["  - " + lines[0]]
    out += ["    " + line for line in lines[1:]]  # uniform +4 keeps block scalars valid
    return "\n".join(out)


def render_file(data, con, cache):
    """Build the formatted text for one file's {crash_id: [stories]} mapping.

    Crashes are ordered by crash_date (unknown crashes last); stories within a
    crash are ordered by story_sort_key.
    """

    def crash_key(crash_id):
        cd = crash_date(con, crash_id, cache)
        return (cd is None, cd or "", crash_id)

    blocks = []
    for crash_id in sorted(data, key=crash_key):
        stories = data[crash_id]
        if not stories:
            blocks.append(f"{crash_id}: []")
            continue
        body = "\n\n".join(render_story(s) for s in sorted(stories, key=story_sort_key))
        blocks.append(f"{crash_id}:\n{body}")
    return "\n\n".join(blocks) + "\n"


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

            if not isinstance(data, dict) or not all(
                isinstance(v, list) and all(isinstance(s, dict) for s in v)
                for v in data.values()
            ):
                print(f"skip {rel}: unexpected structure", file=sys.stderr)
                continue

            new_text = render_file(data, con, cache)
            if new_text != path.read_text():
                path.write_text(new_text)
                print(f"formatted {rel}")
                changed += 1
            else:
                print(f"unchanged {rel}")
    finally:
        con.close()

    print(f"done: {changed} file(s) reformatted, {len(paths)} scanned")
    return 0


if __name__ == "__main__":
    sys.exit(main())
