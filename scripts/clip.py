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

Usage: python3 clip.py [<url>] [--indent N]
       pbpaste | python3 clip.py
"""

import argparse
import sys

from format import render_story, story_sort_key

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
        print(f"error: {url}: {exc}", file=sys.stderr)
        return None

    blank = [field for field in REQUIRED if not story.get(field)]
    if blank:
        print(f"note: {url}: no {', '.join(blank)} found on the page", file=sys.stderr)
    return story


def main(url=None, indent=0):
    """Print a story entry per url. Returns a process exit code."""
    urls = urls_to_clip(url)
    if urls is None:
        print("error: no url given, and nothing piped in", file=sys.stderr)
        return 2
    if not urls:
        print("error: no urls on stdin", file=sys.stderr)
        return 2

    try:
        import qlip
    except ImportError:
        print(QLIP_MISSING.format(executable=sys.executable), file=sys.stderr)
        return 2

    fetched = [fetch_story(qlip, u) for u in urls]
    stories = [s for s in fetched if s is not None]
    if stories:
        # Oldest first and blank-line separated, i.e. the order and spacing
        # format.py would put them in anyway — so a multi-url paste lands
        # already settled instead of being reshuffled on the next format run.
        stories.sort(key=story_sort_key)
        print("\n\n".join(render_story(s, indent=" " * indent) for s in stories))
    return 1 if len(stories) < len(fetched) else 0


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
        "--indent",
        type=int,
        default=0,
        metavar="N",
        help="indent the entry by N spaces; use 4 to paste straight under a "
        "crash's `stories:` key (default: 0)",
    )
    return parser


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_arguments(parser)
    sys.exit(main(**vars(parser.parse_args())))
