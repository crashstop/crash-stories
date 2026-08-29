#!/usr/bin/env python3
"""Print a short summary of one crash from db.sqlite, for research notes.

Output is five kinds of line:

    <crash_date>
    <address>[, <neighborhood_id>]
    [hit-and-run ]<category>
    [fatalities: N ][incap: N ]injured: N
    - <age> <sex> <injury_classification>     (one per hurt person)

A count is omitted when it's zero, except `injured:`, which always shows.
Unknown ages and sexes print as `?`.

On the tallies, which are not additive and don't sum to the list below them:
`incap_tally` is a *subset* of `injured_tally`, and `injured_tally` excludes
the people who died (see the crash_meta DDL). The person list is deliberately
wider than `injured_tally`: it's everyone with a real injury classification,
fatalities included, most severe first — leaving the dead out of a crash
summary would defeat the point.

So the list should always hold exactly fatal_tally + injured_tally people:
crash_meta's tallies are built from the same redaction-filtered population that
clean_people exposes (checked across every crash with a redacted casualty). If
it ever comes up short — crash_meta gone stale against redactions added since
it was built — a note about the gap goes to stderr, leaving stdout clean.

Usage: python3 info.py <crash_record_id>
"""

import argparse
import sqlite3
import sys

import colors
from common import DB

CRASH_SQL = """
SELECT crash_date, address, neighborhood_id, category, hit_and_run_i,
       fatal_tally, incap_tally, injured_tally
FROM crashes_serving
WHERE crash_record_id = ?
"""

# Everyone the report records an actual injury for. A NULL classification drops
# out through the NOT IN, matching how crash_meta counts (verified: the three
# tallies reproduce exactly from these rows across every 2026 crash).
PEOPLE_SQL = """
SELECT age, sex, injury_classification
FROM clean_people
WHERE crash_record_id = ?
  AND injury_classification NOT IN ('NO INDICATION OF INJURY', '')
ORDER BY CASE injury_classification
             WHEN 'FATAL' THEN 0
             WHEN 'INCAPACITATING INJURY' THEN 1
             WHEN 'NONINCAPACITATING INJURY' THEN 2
             WHEN 'REPORTED, NOT EVIDENT' THEN 3
             ELSE 4
         END,
         person_id
"""


def cell(value):
    """A person field for display: '?' when absent — but 0 is an age, not absence."""
    return "?" if value is None or value == "" else str(value)


def summarize(crash, people):
    """Build the summary block for one crash row and its hurt-people rows."""
    place = crash["address"] or "?"
    if crash["neighborhood_id"]:
        place += f", {crash['neighborhood_id']}"

    counts = []
    if crash["fatal_tally"]:
        counts.append(f"fatalities: {crash['fatal_tally']}")
    if crash["incap_tally"]:
        counts.append(f"incap: {crash['incap_tally']}")
    counts.append(f"injured: {crash['injured_tally']}")

    lines = [
        crash["crash_date"],
        place,
        (
            f"hit-and-run {crash['category']}"
            if crash["hit_and_run_i"]
            else crash["category"]
        ),
        " ".join(counts),
    ]
    lines += [
        f"- {cell(p['age'])} {cell(p['sex'])} {p['injury_classification']}"
        for p in people
    ]
    return "\n".join(lines)


def main(crash_record_id):
    if not DB.exists():
        print(colors.error(f"error: database not found at {DB}"), file=sys.stderr)
        return 2

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        crash = con.execute(CRASH_SQL, (crash_record_id,)).fetchone()
        if crash is None:
            print(
                colors.error(f"error: no crash {crash_record_id} in {DB.name}"),
                file=sys.stderr,
            )
            return 1
        people = con.execute(PEOPLE_SQL, (crash_record_id,)).fetchall()
    finally:
        con.close()

    print(summarize(crash, people))

    # Shouldn't happen — see the module docstring. It would mean crash_meta's
    # tallies no longer agree with the person rows they were built from.
    hurt = crash["fatal_tally"] + crash["injured_tally"]
    if len(people) < hurt:
        print(
            colors.warning(
                f"note: only {len(people)} of {hurt} hurt people have person "
                "records; the tallies and clean_people disagree"
            ),
            file=sys.stderr,
        )
    return 0


def add_arguments(parser):
    """Register this script's arguments on parser.

    The single definition of info's command line: both the __main__ block below
    and the repo-root ./q dispatcher call this, so the two can't drift.
    """
    parser.add_argument("crash_record_id", help="the crash to summarize")
    return parser


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_arguments(parser)
    sys.exit(main(**vars(parser.parse_args())))
