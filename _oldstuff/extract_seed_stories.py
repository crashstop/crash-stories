#!/usr/bin/env python3
""" Split seeds-stories.yaml into per-month files under stories/<year>/<year-month>.yaml.
Usage: python3 split_stories.py

NOTE: After the repo creation, this script and seeds-stories.yaml are deprecated.
Contributions are to be made to the Github repo yaml files


For each crash_record_id in the seed file, look up its crash_date in db.sqlite, then
route that crash's story entries into the file for the crash's year and month.
"""
import sqlite3
import sys
from pathlib import Path

import yaml
from yaml.events import AliasEvent, CollectionStartEvent, NodeEvent, ScalarEvent

ROOT = Path(__file__).resolve().parent.parent  # repo root (this file lives in scripts/)
SEED = ROOT / "_oldstuff" / "seeds-stories.yaml"
DB = ROOT / "db.sqlite"
OUT = ROOT / "stories"


class StoryDumper(yaml.SafeDumper):
    """SafeDumper that keeps the hand-maintained seed's formatting intact."""

    def increase_indent(self, flow=False, indentless=False):
        # Indent block sequences under their mapping key ("  - url:") to match
        # the seed's style instead of PyYAML's default flush-left sequences.
        return super().increase_indent(flow, False)

    def check_simple_key(self):
        # PyYAML hardcodes a 128-char cap on "simple" mapping keys; a longer key
        # falls back to the explicit "? key\n: value" form. The 128-char SHA-512
        # crash_record_id keys trip that cap, so raise it to keep the seed's
        # readable "crash_id:\n  - ..." block style. (Body copied from
        # Emitter.check_simple_key with only the numeric limit changed.)
        length = 0
        if isinstance(self.event, NodeEvent) and self.event.anchor is not None:
            if self.prepared_anchor is None:
                self.prepared_anchor = self.prepare_anchor(self.event.anchor)
            length += len(self.prepared_anchor)
        if isinstance(self.event, (ScalarEvent, CollectionStartEvent)) \
                and self.event.tag is not None:
            if self.prepared_tag is None:
                self.prepared_tag = self.prepare_tag(self.event.tag)
            length += len(self.prepared_tag)
        if isinstance(self.event, ScalarEvent):
            if self.analysis is None:
                self.analysis = self.analyze_scalar(self.event.value)
            length += len(self.analysis.scalar)
        return (length < 1024 and (isinstance(self.event, AliasEvent)
            or (isinstance(self.event, ScalarEvent)
                    and not self.analysis.empty and not self.analysis.multiline)
            or self.check_empty_sequence() or self.check_empty_mapping()))


def _represent_str(dumper, data):
    # Multi-line descriptions stay as literal block scalars (|-), like the seed.
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


StoryDumper.add_representer(str, _represent_str)


def load_crash_dates(con, crash_ids):
    """Return {crash_record_id: 'YYYY-MM-DD HH:MM'} from crashes_serving."""
    dates = {}
    for cid in crash_ids:
        row = con.execute(
            "SELECT crash_date FROM crashes_serving WHERE crash_record_id = ?",
            (cid,),
        ).fetchone()
        if row is None or not row[0]:
            print(f"WARNING: no crash_date found for {cid} — skipping", file=sys.stderr)
            continue
        dates[cid] = row[0]
    return dates


def main():
    seed = yaml.safe_load(SEED.read_text())
    if not seed:
        print("seed file is empty; nothing to do", file=sys.stderr)
        return

    con = sqlite3.connect(DB)
    try:
        dates = load_crash_dates(con, seed.keys())
    finally:
        con.close()

    # Group by the crash's own year-month: {'YYYY-MM': {crash_id: [stories]}}.
    # crash_date is naive local time ('2026-06-05 16:50'); slice it rather than
    # datetime-parse to avoid any timezone/day-boundary drift near midnight.
    months = {}
    for cid, stories in seed.items():
        crash_date = dates.get(cid)
        if crash_date is None:
            continue
        year_month = crash_date[:7]
        months.setdefault(year_month, {})[cid] = stories

    files = 0
    for year_month, crashes in sorted(months.items()):
        year = year_month[:4]
        year_dir = OUT / year
        year_dir.mkdir(parents=True, exist_ok=True)
        path = year_dir / f"{year_month}.yaml"
        path.write_text(
            yaml.dump(
                crashes,
                Dumper=StoryDumper,
                sort_keys=False,
                allow_unicode=True,
                default_flow_style=False,
                width=4096,
            )
        )
        story_count = sum(len(v) for v in crashes.values())
        print(f"wrote {path.relative_to(ROOT)}  ({len(crashes)} crashes, {story_count} stories)")
        files += 1

    total_stories = sum(len(v) for v in seed.values())
    print(f"done: {files} files, {total_stories} stories from {len(seed)} crashes")


if __name__ == "__main__":
    main()
