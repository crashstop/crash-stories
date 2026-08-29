#!/usr/bin/env python3
"""Submit story urls to the Internet Archive's Wayback Machine.

Subcommands:
  story <url>     print a valid Wayback Machine archive link for one url to
                  stdout, if available: the latest existing snapshot (per the
                  availability API) when the url has already been archived,
                  otherwise the fresh snapshot from submitting the url to the
                  save endpoint. Status messages go to stderr, so stdout
                  carries only the archive link (or nothing) and is safe to
                  pipe. Exits 0 when a link was printed, 1 when none is
                  available.
  stories <path>  for every story item in one stories/<year>/<year-month>.yaml
                  file (crash `stories` and __GENERAL__ entries alike) that
                  has a url but no `archive_url`, retrieve/make an archive
                  link the same way and add it to the item as `archive_url`.
                  The file is rewritten through format.py's renderer, so it
                  also comes out formatted. Exits 0 when every missing link
                  was filled in, 1 when any url couldn't be archived.

Usage: python3 archive.py story <url>
       python3 archive.py stories <path/to/year-month.yaml>
"""

import argparse
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen

import colors
from common import iter_stories, load_story_file, rewrite_file
from format import render_file

SAVE_ENDPOINT = "https://web.archive.org/save/"
# limit=-1 returns only the most recent capture; statuscode:200 skips
# captures of redirects and error pages
CDX_ENDPOINT = (
    "https://web.archive.org/cdx/search/cdx"
    "?output=json&limit=-1&filter=statuscode:200&fl=timestamp,original&url="
)
USER_AGENT = "chicagocrashes-relatedstories archive.py (via urllib)"

# Saves can sit in the Wayback capture queue for a while before responding
SAVE_TIMEOUT = 120
AVAILABLE_TIMEOUT = 30


def status(msg):
    """Progress chatter. Always stderr, so stdout carries only the archive link."""
    style = colors.error if msg.startswith("error:") or "failed" in msg else colors.note
    print(style(msg), file=sys.stderr)


def fetch(url, timeout):
    """GET url (following redirects); return the response object."""
    return urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=timeout)


def save_snapshot(url):
    """Submit url to the save endpoint; return the new snapshot's url or None.

    The endpoint redirects (or points via Content-Location) to the freshly
    captured /web/<timestamp>/<url> page.
    """
    with fetch(SAVE_ENDPOINT + url, SAVE_TIMEOUT) as resp:
        final = resp.geturl()
        if "/web/" in final:
            return final
        location = resp.headers.get("Content-Location")
        if location:
            return urljoin("https://web.archive.org/", location)
    return None


def existing_snapshot(url):
    """Latest existing snapshot url from the CDX index, or None.

    Uses the CDX API rather than the simpler availability API because the
    latter is flaky: the same query can alternate between finding a snapshot
    and finding nothing.

    `:` and `/` are left unencoded in the query (matching what the endpoints
    expect); `?`/`&`/`=` in the target url are encoded so they don't split
    the CDX query string.
    """
    with fetch(CDX_ENDPOINT + quote(url, safe=":/"), AVAILABLE_TIMEOUT) as resp:
        rows = json.load(resp)
    if len(rows) > 1:  # rows[0] is the header row; empty result is just []
        timestamp, original = rows[-1]
        return f"https://web.archive.org/web/{timestamp}/{original}"
    return None


def archive_link(url):
    """Archive link for one url: the latest existing snapshot when there is
    one, else a freshly saved one, else None. Progress goes to stderr.
    """
    status(f"checking for an existing snapshot: {url}")
    link = None
    try:
        link = existing_snapshot(url)
    except (HTTPError, URLError, TimeoutError) as exc:
        status(f"availability lookup failed: {exc}")

    if link:
        status("using latest existing snapshot")
    else:
        status("none found; submitting to Wayback Machine")
        try:
            link = save_snapshot(url)
        except HTTPError as exc:
            status(f"save failed: HTTP {exc.code} {exc.reason}")
        except (URLError, TimeoutError) as exc:
            status(f"save failed: {exc}")
        if link:
            status("saved")

    if not link:
        status(f"no archive link available for {url}")
    return link


def archive_story(url):
    """Print an archive link for one url to stdout. Returns exit status."""
    link = archive_link(url)
    if link:
        print(link)
        return 0
    return 1


def archive_stories(path):
    """Add an `archive_url` to every story item in one yaml file that has a
    url but lacks one, rewriting the file in place. Returns exit status.
    """
    path = Path(path).resolve()
    if not path.is_file():
        status(f"error: no such file: {path}")
        return 2
    data = load_story_file(path)
    if data is None:  # load_story_file already printed the skip reason
        return 2

    missing = [
        story
        for _, story in iter_stories(data)
        if not story.get("archive_url")
        and isinstance(story.get("url"), str)
        and story["url"].strip()
    ]
    if not missing:
        status("all stories already have an archive_url")
        return 0

    status(f"{len(missing)} story item(s) missing an archive_url")
    failed = 0
    for story in missing:
        link = archive_link(story["url"].strip())
        if link:
            story["archive_url"] = link
        else:
            failed += 1

    if len(missing) - failed:
        rewrite_file(path, render_file(data), "archived")
    status(f"{len(missing) - failed} archive_url(s) added, {failed} failed")
    return 1 if failed else 0


def add_arguments(parser):
    """Register archive's `story`/`stories` subcommands on parser.

    The single definition of archive's command line: both the main() below and
    the repo-root ./cli dispatcher call this, so the two can't drift. Each
    subcommand carries the function that runs it as the `_run` default; the
    underscore keeps it out of the kwargs both dispatchers build from the
    parsed namespace.
    """
    # Not required: bare `archive` prints this parser's help (see _help below)
    # rather than erroring out with a bare usage line.
    parser.set_defaults(_help=parser.print_help)
    sub = parser.add_subparsers(dest="_archive_command", metavar="<subcommand>")

    p_story = sub.add_parser(
        "story",
        help="submit one url to the Wayback Machine and print its archive link",
    )
    p_story.add_argument("url", help="the story url to archive")
    p_story.set_defaults(_run=archive_story)

    p_stories = sub.add_parser(
        "stories",
        help="add an archive_url to every story in one yaml file that lacks one",
    )
    p_stories.add_argument(
        "path", help="path to a stories/<year>/<year-month>.yaml file"
    )
    p_stories.set_defaults(_run=archive_stories)

    return parser


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_arguments(parser)
    args = parser.parse_args(argv)
    if not hasattr(args, "_run"):  # no subcommand given
        args._help()
        return 0
    return args._run(**{k: v for k, v in vars(args).items() if not k.startswith("_")})


if __name__ == "__main__":
    sys.exit(main())
