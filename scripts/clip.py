#!/usr/bin/env python3
"""Fetch one story url and print it as a ready-to-paste story entry.

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

Only the YAML entry goes to stdout — notes and errors go to stderr — so
`clip.py <url> | pbcopy` pipes cleanly.

Usage: python3 clip.py <url> [--indent N]
"""

import argparse
import sys

from format import render_story

# The fields qlip always returns; a missing one comes back None and is worth a
# heads-up for the three lint treats as mandatory.
REQUIRED = ("url", "title", "date")

QLIP_MISSING = """error: this subcommand needs qlip, which isn't importable

  pip install -e /path/to/qlip     # https://github.com/dannguyen/qlip

qlip must be installed for the same interpreter that runs this script
({executable})."""


def main(url, indent=0):
    """Print the story entry for one url. Returns a process exit code."""
    try:
        import qlip
    except ImportError:
        print(QLIP_MISSING.format(executable=sys.executable), file=sys.stderr)
        return 2

    try:
        story = qlip.extract(qlip.fetch(url), url)
    except Exception as exc:  # noqa: BLE001 -- qlip raises curl_cffi's tree, which
        # we can't name without importing curl_cffi ourselves; a url that won't
        # fetch is a normal outcome here, not something to traceback over.
        print(f"error: {url}: {exc}", file=sys.stderr)
        return 1

    blank = [field for field in REQUIRED if not story.get(field)]
    if blank:
        print(f"note: no {', '.join(blank)} found on the page", file=sys.stderr)

    print(render_story(story, indent=" " * indent))
    return 0


def add_arguments(parser):
    """Register this script's arguments on parser.

    The single definition of clip's command line: both the __main__ block below
    and the repo-root ./cli dispatcher call this, so the two can't drift.
    """
    parser.add_argument("url", help="the story url to fetch")
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
