"""info.py: the summary's exact shape, and the data traps behind it."""

import pytest

import info

CRASH_ID = "abc123"

FATAL = "FATAL"
INCAP = "INCAPACITATING INJURY"
NONINCAP = "NONINCAPACITATING INJURY"
REPORTED = "REPORTED, NOT EVIDENT"
NONE = "NO INDICATION OF INJURY"


def crash_row(**overrides):
    row = {
        "crash_date": "2026-08-02 21:33",
        "address": "159 E 63RD ST",
        "neighborhood_id": "grand-crossing",
        "category": "VEHICLE-TO-VEHICLE",
        "hit_and_run_i": 0,
        "fatal_tally": 0,
        "incap_tally": 0,
        "injured_tally": 0,
    }
    row.update(overrides)
    return row


def person(age, sex, injury):
    return {"age": age, "sex": sex, "injury_classification": injury}


class TestCell:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (None, "?"),
            ("", "?"),
            (0, "0"),  # an infant's age, not a missing one
            (3, "3"),
            (41, "41"),
            ("M", "M"),
            ("X", "X"),
        ],
    )
    def test_rendering(self, value, expected):
        assert info.cell(value) == expected

    def test_age_zero_is_not_treated_as_absent(self):
        """A falsy check here would hide every infant casualty."""
        assert info.cell(0) == "0"


class TestSummarize:
    def test_the_whole_block(self):
        out = info.summarize(
            crash_row(incap_tally=2, injured_tally=6),
            [person(41, "M", INCAP), person(3, "F", INCAP)],
        )
        assert out == (
            "2026-08-02 21:33\n"
            "159 E 63RD ST, grand-crossing\n"
            "VEHICLE-TO-VEHICLE\n"
            "incap: 2 injured: 6\n"
            "- 41 M INCAPACITATING INJURY\n"
            "- 3 F INCAPACITATING INJURY"
        )

    def test_hit_and_run_prefixes_the_category(self):
        out = info.summarize(crash_row(hit_and_run_i=1), [])
        assert out.splitlines()[2] == "hit-and-run VEHICLE-TO-VEHICLE"

    def test_no_prefix_when_not_a_hit_and_run(self):
        out = info.summarize(crash_row(), [])
        assert out.splitlines()[2] == "VEHICLE-TO-VEHICLE"

    def test_a_null_neighborhood_leaves_no_trailing_comma(self):
        out = info.summarize(crash_row(neighborhood_id=None), [])
        assert out.splitlines()[1] == "159 E 63RD ST"

    def test_a_missing_address_shows_a_question_mark(self):
        out = info.summarize(crash_row(address=None), [])
        assert out.splitlines()[1] == "?, grand-crossing"

    @pytest.mark.parametrize(
        "tallies,expected",
        [
            ({}, "injured: 0"),
            ({"injured_tally": 6}, "injured: 6"),
            ({"incap_tally": 2, "injured_tally": 6}, "incap: 2 injured: 6"),
            ({"fatal_tally": 1, "injured_tally": 3}, "fatalities: 1 injured: 3"),
            (
                {"fatal_tally": 1, "incap_tally": 1, "injured_tally": 1},
                "fatalities: 1 incap: 1 injured: 1",
            ),
        ],
    )
    def test_zero_counts_are_omitted_but_injured_always_shows(self, tallies, expected):
        out = info.summarize(crash_row(**tallies), [])
        assert out.splitlines()[3] == expected

    def test_no_casualties_means_no_person_lines(self):
        assert len(info.summarize(crash_row(), []).splitlines()) == 4

    def test_unknown_age_and_sex_render_as_question_marks(self):
        out = info.summarize(crash_row(injured_tally=1), [person(None, "", NONINCAP)])
        assert out.splitlines()[-1] == "- ? ? NONINCAPACITATING INJURY"


class TestMain:
    def test_lists_the_fatality_even_though_injured_tally_excludes_it(
        self, sandbox, capsys
    ):
        """injured_tally counts only the survivors; the list must still show the dead."""
        sandbox.add_crash(
            CRASH_ID,
            "2026-04-05 01:08",
            address="6300 S KEDZIE AVE",
            neighborhood_id="chicago-lawn",
            category="VEHICLE-TO-VEHICLE",
            hit_and_run_i=1,
            fatal_tally=1,
            incap_tally=1,
            injured_tally=1,
        )
        sandbox.add_person(CRASH_ID, None, "M", FATAL)
        sandbox.add_person(CRASH_ID, 22, "F", INCAP)
        assert info.main(CRASH_ID) == 0
        assert capsys.readouterr().out == (
            "2026-04-05 01:08\n"
            "6300 S KEDZIE AVE, chicago-lawn\n"
            "hit-and-run VEHICLE-TO-VEHICLE\n"
            "fatalities: 1 incap: 1 injured: 1\n"
            "- ? M FATAL\n"
            "- 22 F INCAPACITATING INJURY\n"
        )

    def test_people_come_out_most_severe_first(self, sandbox, capsys):
        sandbox.add_crash(CRASH_ID, "2026-01-01 00:00", fatal_tally=1, injured_tally=3)
        for age, injury in [
            (10, REPORTED),
            (20, NONINCAP),
            (30, INCAP),
            (40, FATAL),
        ]:  # inserted least-severe first
            sandbox.add_person(CRASH_ID, age, "M", injury)
        info.main(CRASH_ID)
        listed = [l for l in capsys.readouterr().out.splitlines() if l.startswith("- ")]
        assert listed == [
            "- 40 M FATAL",
            "- 30 M INCAPACITATING INJURY",
            "- 20 M NONINCAPACITATING INJURY",
            "- 10 M REPORTED, NOT EVIDENT",
        ]

    def test_uninjured_people_are_left_out(self, sandbox, capsys):
        sandbox.add_crash(CRASH_ID, "2026-01-01 00:00", injured_tally=1)
        sandbox.add_person(CRASH_ID, 50, "M", NONE)
        sandbox.add_person(CRASH_ID, 60, "F", NONINCAP)
        info.main(CRASH_ID)
        out = capsys.readouterr().out
        assert "- 60 F NONINCAPACITATING INJURY" in out
        assert "50" not in out

    def test_people_with_a_blank_classification_are_left_out(self, sandbox, capsys):
        sandbox.add_crash(CRASH_ID, "2026-01-01 00:00", injured_tally=0)
        sandbox.add_person(CRASH_ID, 50, "M", "")
        sandbox.add_person(CRASH_ID, 51, "M", None)
        info.main(CRASH_ID)
        assert "- " not in capsys.readouterr().out

    def test_only_this_crashs_people_are_listed(self, sandbox, capsys):
        sandbox.add_crash(CRASH_ID, "2026-01-01 00:00", injured_tally=1)
        sandbox.add_crash("other", "2026-01-01 00:00", injured_tally=1)
        sandbox.add_person(CRASH_ID, 30, "M", NONINCAP)
        sandbox.add_person("other", 99, "F", NONINCAP)
        info.main(CRASH_ID)
        assert "99" not in capsys.readouterr().out

    def test_an_age_zero_casualty_shows_as_zero(self, sandbox, capsys):
        sandbox.add_crash(CRASH_ID, "2026-01-01 00:00", injured_tally=1)
        sandbox.add_person(CRASH_ID, 0, "F", NONINCAP)
        info.main(CRASH_ID)
        assert "- 0 F NONINCAPACITATING INJURY" in capsys.readouterr().out

    def test_unknown_crash_id(self, sandbox, capsys):
        assert info.main("nope") == 1
        captured = capsys.readouterr()
        assert "no crash nope" in captured.err
        assert captured.out == ""

    def test_missing_database(self, sandbox, capsys):
        sandbox.db.unlink()
        assert info.main(CRASH_ID) == 2
        assert "database not found" in capsys.readouterr().err

    def test_notes_on_stderr_when_person_rows_dont_match_the_tallies(
        self, sandbox, capsys
    ):
        """A tripwire for crash_meta going stale against the person table."""
        sandbox.add_crash(CRASH_ID, "2026-01-01 00:00", fatal_tally=1, injured_tally=2)
        sandbox.add_person(CRASH_ID, 30, "M", FATAL)
        assert info.main(CRASH_ID) == 0
        captured = capsys.readouterr()
        assert "only 1 of 3 hurt people" in captured.err
        assert "note:" not in captured.out  # stdout stays clean summary text

    def test_no_note_when_the_counts_line_up(self, sandbox, capsys):
        sandbox.add_crash(CRASH_ID, "2026-01-01 00:00", fatal_tally=1, injured_tally=1)
        sandbox.add_person(CRASH_ID, 30, "M", FATAL)
        sandbox.add_person(CRASH_ID, 40, "F", INCAP)
        info.main(CRASH_ID)
        assert capsys.readouterr().err == ""
