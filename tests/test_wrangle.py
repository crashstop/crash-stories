"""wrangle.py: the two CSVs — columns, ordering, and what stays out of them."""

import csv
from datetime import date, datetime

import pytest

import common
import wrangle


def rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def header(path):
    with open(path, newline="", encoding="utf-8") as f:
        return next(csv.reader(f))


class TestToCell:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (None, ""),
            ("text", "text"),
            (3, "3"),
            (date(2026, 1, 5), "2026-01-05"),
            (datetime(2026, 1, 5, 10, 30), "2026-01-05T10:30:00"),
        ],
    )
    def test_rendering(self, value, expected):
        assert wrangle.to_cell(value) == expected


class TestCountRecords:
    def test_none_when_absent(self, tmp_path):
        assert wrangle.count_records(tmp_path / "nope.csv") is None

    def test_excludes_the_header(self, tmp_path):
        path = tmp_path / "x.csv"
        path.write_text("a,b\n1,2\n3,4\n")
        assert wrangle.count_records(path) == 2

    def test_header_only_is_zero(self, tmp_path):
        path = tmp_path / "x.csv"
        path.write_text("a,b\n")
        assert wrangle.count_records(path) == 0


class TestChangeNote:
    @pytest.mark.parametrize(
        "before,after,expected",
        [
            (None, 5, "new file"),
            (5, 5, "unchanged from previous 5"),
            (5, 8, "was 5, +3"),
            (8, 5, "was 8, -3"),
        ],
    )
    def test_wording(self, before, after, expected):
        assert wrangle.change_note(before, after) == expected


class TestMain:
    def test_writes_both_csvs(self, sandbox):
        sandbox.write(
            "2026-01",
            "abc:\n  notes: a public note\n  stories:\n"
            "    - url: https://ex.com/a\n      title: T\n      date: 2026-01-05\n",
        )
        assert wrangle.main() == 0
        assert rows(sandbox.stories_csv) == [
            {
                "crash_record_id": "abc",
                "date": "2026-01-05",
                "url": "https://ex.com/a",
                "title": "T",
                "site": "",
                "description": "",
            }
        ]
        assert rows(sandbox.notes_csv) == [
            {
                "crash_record_id": "abc",
                "crash_yearmonth": "2026-01",
                "content": "a public note",
            }
        ]

    def test_column_order_is_id_then_preferred_then_extras(self, sandbox):
        sandbox.write(
            "2026-01",
            "abc:\n  stories:\n    - url: u\n      priority: 2\n      archive_url: a\n",
        )
        wrangle.main()
        assert header(sandbox.stories_csv) == [
            "crash_record_id",
            *wrangle.PREFERRED,
            "priority",
            "archive_url",
        ]

    def test_private_notes_never_reach_either_csv(self, sandbox):
        sandbox.write("2026-01", "abc:\n  private_notes: internal only\n")
        wrangle.main()
        assert "internal only" not in sandbox.stories_csv.read_text()
        assert "internal only" not in sandbox.notes_csv.read_text()
        assert rows(sandbox.notes_csv) == []

    def test_comments_are_ignored(self, sandbox):
        sandbox.write("2026-01", f"{common.COMMENTS_KEY}:\n  - a documenter note\n")
        wrangle.main()
        assert rows(sandbox.stories_csv) == []
        assert "a documenter note" not in sandbox.stories_csv.read_text()

    def test_general_stories_get_a_blank_crash_id(self, sandbox):
        sandbox.write(
            "2026-01",
            f"{common.GENERAL_KEY}:\n  - url: https://ex.com/g\n    date: 2026-01-05\n",
        )
        wrangle.main()
        assert rows(sandbox.stories_csv)[0]["crash_record_id"] == ""

    def test_stories_sort_by_date_then_id(self, sandbox):
        sandbox.write(
            "2026-01",
            "zzz:\n  stories:\n    - url: https://ex.com/late\n      date: 2026-01-20\n\n"
            "aaa:\n  stories:\n    - url: https://ex.com/early\n      date: 2026-01-02\n",
        )
        wrangle.main()
        assert [r["url"] for r in rows(sandbox.stories_csv)] == [
            "https://ex.com/early",
            "https://ex.com/late",
        ]

    def test_notes_sort_by_month_then_id(self, sandbox):
        sandbox.write("2026-02", "bbb:\n  notes: feb\n")
        sandbox.write("2026-01", "zzz:\n  notes: jan z\n\naaa:\n  notes: jan a\n")
        wrangle.main()
        assert [r["content"] for r in rows(sandbox.notes_csv)] == [
            "jan a",
            "jan z",
            "feb",
        ]

    def test_warns_about_a_duplicated_crash_and_url_pair(self, sandbox, capsys):
        sandbox.write(
            "2026-01",
            "abc:\n  stories:\n    - url: https://ex.com/a\n      date: 2026-01-05\n",
        )
        sandbox.write(
            "2026-02",
            "abc:\n  stories:\n    - url: https://ex.com/a\n      date: 2026-02-05\n",
        )
        wrangle.main()
        err = capsys.readouterr().err
        assert "WARNING: Duplicate crash id + url: abc: https://ex.com/a" in err

    def test_same_url_under_different_crashes_is_not_a_duplicate(self, sandbox, capsys):
        sandbox.write(
            "2026-01",
            "abc:\n  stories:\n    - url: https://ex.com/a\n      date: 2026-01-05\n\n"
            "xyz:\n  stories:\n    - url: https://ex.com/a\n      date: 2026-01-05\n",
        )
        wrangle.main()
        assert "WARNING" not in capsys.readouterr().err

    def test_dry_writes_nothing(self, sandbox, capsys):
        sandbox.write("2026-01", "abc:\n  stories:\n    - url: u\n")
        assert wrangle.main(dry=True) == 0
        assert not sandbox.stories_csv.exists()
        assert not sandbox.notes_csv.exists()
        assert "(dry)" in capsys.readouterr().out

    def test_reports_the_change_against_the_previous_run(self, sandbox, capsys):
        sandbox.write("2026-01", "abc:\n  stories:\n    - url: u1\n")
        wrangle.main()
        capsys.readouterr()
        sandbox.write("2026-01", "abc:\n  stories:\n    - url: u1\n    - url: u2\n")
        wrangle.main()
        assert "was 1, +1" in capsys.readouterr().out

    def test_always_scans_every_file(self, sandbox):
        """wrangle rewrites stories.csv, so a changed-only scan would go blind."""
        import os

        sandbox.write("2026-01", "abc:\n  stories:\n    - url: u1\n")
        wrangle.main()
        os.utime(sandbox.stories / "2026" / "2026-01.yaml", (1, 1))
        sandbox.write("2026-02", "xyz:\n  stories:\n    - url: u2\n")
        wrangle.main()
        assert len(rows(sandbox.stories_csv)) == 2
