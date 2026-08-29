#!/usr/bin/env python3
"""ANSI styling for the scripts' terminal output.

Colour is applied only when the destination stream is a terminal, so anything
piped or redirected stays plain text: `./cli clip <url> | pbcopy`, `./cli info
<id> >> notes.md`, and the test suite's captured output all come out with no
escape codes in them. `NO_COLOR` (any value, https://no-color.org) turns it off
even on a terminal; `FORCE_COLOR` turns it on even off one.

The palette is deliberately small — three meanings, not a rainbow:

    bold green   a run finished
    magenta      something was written; the reason to look at this run
    red/yellow   an error / a warning
    dim          scan noise: files nothing happened to, "pass --all" hints
"""

import os
import sys

RESET = "\033[0m"
CODES = {
    "bold": "1",
    "dim": "2",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "magenta": "35",
    "cyan": "36",
}


def enabled(stream=None):
    """Whether to emit escape codes for stream (default: the current stdout)."""
    stream = sys.stdout if stream is None else stream
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    try:
        return stream.isatty()
    except (AttributeError, ValueError):  # detached or closed stream
        return False


def paint(text, *styles, stream=None):
    """text wrapped in the named styles, or returned unchanged when colour is off."""
    if not text or not enabled(stream):
        return text
    codes = ";".join(CODES[style] for style in styles)
    return f"\033[{codes}m{text}{RESET}"


def done(label, stats=None, changed=False):
    """The '<label> DONE[: <stats>]' line every script signs off with.

    The sign-off is always bold green. The stats after it go magenta only when
    the run actually wrote something — an unremarkable "0 reformatted" run
    stays plain, so a wall of them doesn't drown out the one that mattered.
    """
    line = paint(f"{label} DONE", "bold", "green")
    if stats:
        line += ": " + (paint(stats, "magenta") if changed else stats)
    return line


def changed(text):
    """A file this run wrote."""
    return paint(text, "magenta")


def quiet(text):
    """Scan noise: files nothing happened to, and the --all hints."""
    return paint(text, "dim")


def path(text):
    """A story-file path inside a longer line."""
    return paint(text, "cyan")


def heading(text):
    """A section header, e.g. `./cli make`'s per-step banner."""
    return paint(text, "bold", "cyan")


def error(text):
    return paint(text, "red", stream=sys.stderr)


def warning(text):
    return paint(text, "yellow", stream=sys.stderr)


def note(text):
    return paint(text, "dim", stream=sys.stderr)
