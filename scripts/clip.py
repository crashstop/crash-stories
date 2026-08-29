#!/usr/bin/env python3
"""Fetch story urls and print them as ready-to-paste story entries.

With no url argument (or `-`), urls are read from stdin, one per line, so a url
sitting in the clipboard round-trips in one go:

    pbpaste | clip.py | pbcopy

Multiple urls give multiple entries, oldest first and blank-line separated —
the order and spacing format.py would put them in anyway, so a paste of several
doesn't get reshuffled on the next format run. A url that won't fetch is
reported on stderr and skipped; the rest still print, and the exit code is 1 if
any failed.

The fetching and metadata extraction are qlip's (https://github.com/dannguyen/qlip,
installed separately); the rendering is format.py's, so what comes out is
byte-identical to what `format.py` would write for that entry and survives the
next format/reconcile run untouched. That last part is why this doesn't just
shell out to `qlip`: qlip forces a `|-` literal block on every description,
where this repo uses a plain scalar for one-liners and `|` only for genuinely
multi-line text — so qlip's own YAML gets rewritten the next time anything
formats the file.

`site` comes out as the bare domain (qlip derives it from the url).
reconcile.py swaps it for the display name in reference/domain-lookup.csv on
its next run, so there's nothing to fix by hand.

Only the YAML entries go to stdout — notes and errors go to stderr — so the
pipe above carries nothing but the entries.

With `--id <crash_record_id>`, nothing is printed to paste: the entry is
inserted straight into that crash's `stories` list instead. The file it goes in
is the one the crash's `crash_date` puts it in — stories/<year>/<year-month>
.yaml — which is exactly where lint.py requires the entry to live, so the
lookup is one db query and no scan. The crash must already have an entry there;
creating one is a judgement call about `notes`/`private_notes` that belongs to
whoever is doing the research, so a missing entry is an error, not something
this fills in. A url already in that crash's stories is an error too. The file
is rewritten through format.py's renderer, so it also comes out formatted (and
the new entry lands in its chronological place, not at the end of the list).

Whatever went in is echoed to stderr, at the indentation it has in the file, so
an insert isn't something that happens entirely out of sight. It goes to stderr
rather than stdout because it is a report, not a payload: stdout carries the
usual "clipped <file>" status line.

A page that gives up no title or date is still inserted — the same entry a
paste would have produced — with a note naming the file, since lint.py treats
both as mandatory and nothing reviews the entry on its way in.

The url still comes from wherever it usually does, so the clipboard round-trip
works here too: `pbpaste | clip.py --id <crash_record_id>`. `--indent` only
shapes the printed entry and does nothing when inserting.

Usage: python3 clip.py [<url>] [--id CRASH_RECORD_ID] [--indent N]
       pbpaste | python3 clip.py
"""

import argparse
import sqlite3
import sys

import colors
from common import DB, ROOT, STORIES, crash_date, load_story_file, rewrite_file
from format import render_file, render_story, story_sort_key

# The fields qlip always returns; a missing one comes back None and is worth a
# heads-up for the three lint treats as mandatory.
REQUIRED = ("url", "title", "date")

QLIP_MISSING = """error: this subcommand needs qlip, which isn't importable

  pip install -e /path/to/qlip     # https://github.com/dannguyen/qlip

qlip must be installed for the same interpreter that runs this script
({executable})."""


def urls_to_clip(url):
    """The urls to fetch: the argument, or stdin's lines when there isn't one.

    Returns None when no url was given and stdin is a terminal — there is
    nothing to read there, and blocking on it would just look like a hang.
    """
    if url and url != "-":
        return [url]
    if sys.stdin.isatty():
        return None
    return [line.strip() for line in sys.stdin if line.strip()]


def fetch_story(qlip, url):
    """The story mapping for one url, or None if it couldn't be fetched."""
    try:
        story = qlip.extract(qlip.fetch(url), url)
    except Exception as exc:  # noqa: BLE001 -- qlip raises curl_cffi's tree, which
        # we can't name without importing curl_cffi ourselves; a url that won't
        # fetch is a normal outcome here, not something to traceback over.
        print(colors.error(f"error: {url}: {exc}"), file=sys.stderr)
        return None

    blank = [field for field in REQUIRED if not story.get(field)]
    if blank:
        print(
            colors.warning(f"note: {url}: no {', '.join(blank)} found on the page"),
            file=sys.stderr,
        )
    return story


class NoEntry(Exception):
    """No crash entry to insert into, with the exit code that failure deserves.

    2 for something wrong with the environment (no database, unreadable story
    file), 1 for a well-formed request the data can't satisfy — matching how
    every other script here splits the two.
    """

    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


def open_crash_entry(crash_record_id):
    """Find one crash's entry: (path, file data, that crash's mapping).

    The file is the one the crash's crash_date puts it in, which is where
    lint.py requires the entry to be. Raises NoEntry when there isn't one.
    """
    if not DB.exists():
        raise NoEntry(f"error: database not found at {DB}", code=2)

    con = sqlite3.connect(DB)
    try:
        cdate = crash_date(con, crash_record_id, {})
    finally:
        con.close()
    if cdate is None:
        raise NoEntry(f"error: no crash {crash_record_id} in {DB.name}")

    path = STORIES / cdate[:4] / f"{cdate[:7]}.yaml"
    rel = path.relative_to(ROOT)
    if not path.is_file():
        raise NoEntry(
            f"error: crash {crash_record_id} happened {cdate}, and there is no "
            f"story file at {rel} for it to have an entry in"
        )

    data = load_story_file(path)
    if data is None:  # load_story_file already said why on stderr
        raise NoEntry(f"error: can't insert into {rel}", code=2)
    if crash_record_id not in data:
        raise NoEntry(
            f"error: {rel} has no entry for crash {crash_record_id}; "
            "add one there first (see the README)"
        )
    return path, data, data[crash_record_id]


def insert_stories(crash, crash_record_id, stories):
    """Append stories to the crash's `stories` list, skipping urls already in it.

    Returns the stories actually appended; the duplicates left out are each
    reported on stderr.
    """
    existing = {
        story["url"].strip()
        for story in (crash.get("stories") or [])
        if isinstance(story.get("url"), str)
    }
    fresh = []
    for story in stories:
        url = (story.get("url") or "").strip()
        if url in existing:
            print(
                colors.error(
                    f"error: {url} is already in crash {crash_record_id}'s stories"
                ),
                file=sys.stderr,
            )
            continue
        existing.add(url)
        fresh.append(story)

    if fresh:
        # A `stories:` key can be present but empty, in which case it's None
        # rather than a list — setdefault alone wouldn't be enough.
        if not crash.get("stories"):
            crash["stories"] = []
        crash["stories"] += fresh
    return fresh


def main(url=None, crash_record_id=None, indent=0):
    """Print a story entry per url, or insert them into one crash's stories.

    Returns a process exit code.
    """
    urls = urls_to_clip(url)
    if urls is None:
        print(
            colors.error("error: no url given, and nothing piped in"), file=sys.stderr
        )
        return 2
    if not urls:
        print(colors.error("error: no urls on stdin"), file=sys.stderr)
        return 2

    try:
        import qlip
    except ImportError:
        print(
            colors.error(QLIP_MISSING.format(executable=sys.executable)),
            file=sys.stderr,
        )
        return 2

    # Resolved before anything is fetched, so a crash with no entry to insert
    # into costs no network round-trips.
    if crash_record_id is not None:
        try:
            path, data, crash = open_crash_entry(crash_record_id)
        except NoEntry as exc:
            print(colors.error(str(exc)), file=sys.stderr)
            return exc.code

    fetched = [fetch_story(qlip, u) for u in urls]
    stories = [s for s in fetched if s is not None]
    failed = len(fetched) - len(stories)

    if crash_record_id is None:
        if stories:
            # Oldest first and blank-line separated, i.e. the order and spacing
            # format.py would put them in anyway — so a multi-url paste lands
            # already settled instead of being reshuffled on the next format run.
            stories.sort(key=story_sort_key)
            print("\n\n".join(render_story(s, indent=" " * indent) for s in stories))
        return 1 if failed else 0

    fresh = insert_stories(crash, crash_record_id, stories)
    if fresh:
        # render_file puts the new entries in their chronological place, so
        # there is nothing to sort here.
        rewrite_file(path, render_file(data), "clipped")
        # The whole point of insert mode is that the entry goes somewhere the
        # user isn't looking, so echo what landed — on stderr, at the
        # indentation it has in the file. Only what actually went in: a url
        # refused as a duplicate has already had its own line.
        fresh.sort(key=story_sort_key)
        print("\n\n".join(render_story(s) for s in fresh), file=sys.stderr)
        # A page that gave up no title or date still goes in — the same as
        # pasting one by hand — but nothing reviews it on the way, so say
        # which file now needs the gap filled before it will lint.
        blank = sorted({f for s in fresh for f in REQUIRED if not s.get(f)})
        if blank:
            print(
                colors.warning(
                    f"note: what went into {path.relative_to(ROOT)} has no "
                    f"{', '.join(blank)}; `lint` will flag it until that's filled in"
                ),
                file=sys.stderr,
            )
    return 1 if failed or len(fresh) < len(stories) else 0


def add_arguments(parser):
    """Register this script's arguments on parser.

    The single definition of clip's command line: both the __main__ block below
    and the repo-root ./cli dispatcher call this, so the two can't drift.
    """
    parser.add_argument(
        "url",
        nargs="?",
        help="the story url to fetch; omit it (or pass -) to read urls from "
        "stdin, one per line",
    )
    parser.add_argument(
        "--id",
        dest="crash_record_id",
        metavar="CRASH_RECORD_ID",
        help="insert the entry into this crash's `stories` list (in the story "
        "file its crash_date puts it in) instead of printing it; the crash "
        "must already have an entry there",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=0,
        metavar="N",
        help="indent the entry by N spaces; use 4 to paste straight under a "
        "crash's `stories:` key (default: 0). No effect with --id — the "
        "renderer sets the indentation there",
    )
    return parser


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_arguments(parser)
    sys.exit(main(**vars(parser.parse_args())))
