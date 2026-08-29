"""lint.py: one test per documented validation rule, plus the exit codes."""

from datetime import date, datetime

import pytest

import common
import lint

CRASH_ID = "abc123"


@pytest.fixture
def linted(sandbox):
    """Lint one file's text against a db that knows CRASH_ID; returns (counts, errors)."""

    def run(text, stem="2026-01", crash_date="2026-01-05 08:00"):
        if crash_date:
            sandbox.add_crash(CRASH_ID, crash_date)
        path = sandbox.write(stem, text)
        con = sandbox.connect()
        try:
            return lint.validate_file(path, con, {})
        finally:
            con.close()

    return run


def story(**overrides):
    """A story block that passes every rule, with fields overridden/removed."""
    fields = {"url": "https://ex.com/a", "title": "T", "date": "2026-01-05"}
    fields.update(overrides)
    lines = [f"      {k}: {v}" for k, v in fields.items() if v is not None]
    return "\n".join(lines)


def crash_file(story_block, crash_id=CRASH_ID):
    return f"{crash_id}:\n  stories:\n    -\n{story_block}\n"


class TestValidStoryDate:
    @pytest.mark.parametrize(
        "value",
        [
            date(2026, 1, 5),
            datetime(2026, 1, 5, 10, 30),
            "2026-01-05",
            "2026-01-05T10:30:00",
            "2026-01-05T10:30:00Z",
            "2026-01-05T10:30:00+00:00",
            "2026-01-05T10:30:00.866Z",
        ],
    )
    def test_accepts(self, value):
        assert lint.valid_story_date(value)

    @pytest.mark.parametrize(
        "value", ["20260105", "2026-1-5", "Jan 5 2026", "2026-01", "", 20260105, None]
    )
    def test_rejects(self, value):
        assert not lint.valid_story_date(value)


class TestStoryYearmonth:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (date(2026, 1, 5), "2026-01"),
            (datetime(2026, 12, 5), "2026-12"),
            ("2026-01-05T10:30:00Z", "2026-01"),
            ("  2026-07-05  ", "2026-07"),
        ],
    )
    def test_extracts_the_month(self, value, expected):
        assert lint.story_yearmonth(value) == expected


class TestCleanFile:
    def test_reports_no_errors(self, linted):
        counts, errors = linted(crash_file(story()))
        assert errors == []
        assert counts == {"crashes": 1, "stories": 1, "notes": 0, "private_notes": 0}

    def test_counts_notes_and_private_notes(self, linted):
        counts, errors = linted(
            f"{CRASH_ID}:\n  notes: public\n  private_notes: internal\n"
        )
        assert errors == []
        assert counts["notes"] == 1 and counts["private_notes"] == 1

    def test_blank_notes_are_not_counted(self, linted):
        counts, _ = linted(f"{CRASH_ID}:\n  notes: '  '\n  private_notes: x\n")
        assert counts["notes"] == 0


class TestStoryRules:
    def test_missing_title(self, linted):
        _, errors = linted(crash_file(story(title=None)))
        assert any("missing title" in e for e in errors)

    def test_blank_title(self, linted):
        _, errors = linted(crash_file(story(title="'   '")))
        assert any("missing title" in e for e in errors)

    def test_missing_url(self, linted):
        _, errors = linted(crash_file(story(url=None)))
        assert any("missing url" in e for e in errors)

    def test_missing_date(self, linted):
        _, errors = linted(crash_file(story(date=None)))
        assert any("missing date" in e for e in errors)

    def test_malformed_date(self, linted):
        _, errors = linted(crash_file(story(date="'20260105'")))
        assert any("must be YYYY-MM-DD" in e for e in errors)

    def test_unexpected_story_key(self, linted):
        _, errors = linted(crash_file(story(autohr="typo")))
        assert any("unexpected key(s) 'autohr'" in e for e in errors)

    def test_archive_url_must_be_a_string(self, linted):
        _, errors = linted(crash_file(story(archive_url="[1, 2]")))
        assert any("`archive_url` must be a string" in e for e in errors)

    @pytest.mark.parametrize("value", ["1", "5", "3"])
    def test_priority_accepts_one_through_five(self, linted, value):
        _, errors = linted(crash_file(story(priority=value)))
        assert errors == []

    @pytest.mark.parametrize("value", ["0", "6", "'3'", "true", "2.5"])
    def test_priority_rejects_everything_else(self, linted, value):
        _, errors = linted(crash_file(story(priority=value)))
        assert any("`priority` must be an integer" in e for e in errors)

    def test_duplicate_url_within_one_crash(self, linted):
        text = (
            f"{CRASH_ID}:\n  stories:\n"
            f"    -\n{story()}\n"
            f"    -\n{story(title='Other')}\n"
        )
        _, errors = linted(text)
        assert any("duplicate url within this crash" in e for e in errors)

    def test_same_url_under_two_crashes_is_fine(self, sandbox):
        other = "def456"
        sandbox.add_crash(CRASH_ID, "2026-01-05 08:00")
        sandbox.add_crash(other, "2026-01-06 08:00")
        text = crash_file(story()) + "\n" + crash_file(story(), crash_id=other)
        path = sandbox.write("2026-01", text)
        con = sandbox.connect()
        try:
            _, errors = lint.validate_file(path, con, {})
        finally:
            con.close()
        assert errors == []

    def test_story_must_be_a_mapping(self, linted):
        _, errors = linted(f"{CRASH_ID}:\n  stories:\n    - just a string\n")
        assert any("must be a mapping" in e for e in errors)


class TestCrashRules:
    def test_crash_id_missing_from_db(self, linted):
        _, errors = linted(crash_file(story()), crash_date=None)
        assert any("not found in db" in e for e in errors)

    def test_crash_in_the_wrong_month_file(self, linted):
        _, errors = linted(crash_file(story()), crash_date="2026-03-05 08:00")
        assert any("belongs in 2026-03.yaml, not 2026-01.yaml" in e for e in errors)

    def test_crash_needs_at_least_one_recognized_key(self, linted):
        _, errors = linted(f"{CRASH_ID}:\n  something_else: x\n")
        assert any(
            "must have a `notes`, `private_notes`, or `stories` key" in e
            for e in errors
        )

    def test_unexpected_crash_key(self, linted):
        _, errors = linted(f"{CRASH_ID}:\n  private_info: typo\n")
        assert any("unexpected key(s) 'private_info'" in e for e in errors)

    def test_crash_value_must_be_a_mapping(self, linted):
        _, errors = linted(f"{CRASH_ID}: just a string\n")
        assert any("value must be a mapping" in e for e in errors)

    def test_notes_must_be_a_string(self, linted):
        _, errors = linted(f"{CRASH_ID}:\n  notes:\n    - a list\n")
        assert any("`notes` must be a string" in e for e in errors)

    def test_stories_must_be_a_list(self, linted):
        _, errors = linted(f"{CRASH_ID}:\n  stories: not a list\n")
        assert any("`stories` must be a list" in e for e in errors)


class TestSpecialKeys:
    def test_comments_must_be_a_list_of_strings(self, linted):
        _, errors = linted(f"{common.COMMENTS_KEY}:\n  - 1\n  - 2\n")
        assert any("must be a list of strings" in e for e in errors)

    def test_comments_are_not_counted_as_crashes(self, linted):
        counts, errors = linted(f"{common.COMMENTS_KEY}:\n  - a note\n")
        assert errors == [] and counts["crashes"] == 0

    def test_general_stories_must_fall_in_the_files_month(self, linted):
        text = f"{common.GENERAL_KEY}:\n  -\n{story(date='2026-09-05')}\n"
        _, errors = linted(text)
        assert any("belongs in 2026-09.yaml" in e for e in errors)

    def test_general_stories_in_month_are_fine(self, linted):
        counts, errors = linted(f"{common.GENERAL_KEY}:\n  -\n{story()}\n")
        assert errors == [] and counts["stories"] == 1 and counts["crashes"] == 0

    def test_crash_stories_may_be_published_any_month(self, linted):
        """Only __GENERAL__ gets the in-month check."""
        _, errors = linted(crash_file(story(date="2026-09-05")))
        assert errors == []

    def test_general_must_be_a_list(self, linted):
        _, errors = linted(f"{common.GENERAL_KEY}: nope\n")
        assert any(f"`{common.GENERAL_KEY}` must be a list" in e for e in errors)


class TestFileLevel:
    def test_duplicate_crash_id_is_a_yaml_error(self, linted):
        counts, errors = linted(
            f"{CRASH_ID}:\n  private_notes: one\n{CRASH_ID}:\n  private_notes: two\n"
        )
        assert counts is None
        assert any("duplicate key" in e for e in errors)

    def test_empty_file(self, linted):
        counts, errors = linted("")
        assert errors == ["file is empty"] and counts["crashes"] == 0

    def test_top_level_must_be_a_mapping(self, linted):
        counts, errors = linted("- a\n- b\n")
        assert counts is None
        assert any("top level must be a mapping" in e for e in errors)


class TestMain:
    def test_returns_zero_on_a_clean_tree(self, sandbox, capsys):
        sandbox.add_crash(CRASH_ID, "2026-01-05 08:00")
        sandbox.write("2026-01", crash_file(story()))
        assert lint.main(changed_only=False) == 0
        assert "0 errors" in capsys.readouterr().out

    def test_returns_one_when_a_file_has_errors(self, sandbox):
        sandbox.write("2026-01", crash_file(story()))  # crash id not in db
        assert lint.main(changed_only=False) == 1

    def test_returns_two_without_a_database(self, sandbox, capsys):
        sandbox.db.unlink()
        sandbox.write("2026-01", crash_file(story()))
        assert lint.main(changed_only=False) == 2
        assert "database not found" in capsys.readouterr().err

    def test_summary_totals_every_file(self, sandbox, capsys):
        sandbox.add_crash(CRASH_ID, "2026-01-05 08:00")
        sandbox.add_crash("def456", "2026-02-05 08:00")
        sandbox.write("2026-01", crash_file(story()))
        sandbox.write("2026-02", crash_file(story(), crash_id="def456"))
        lint.main(changed_only=False)
        assert "2 files, 2 crashes, 2 stories" in capsys.readouterr().out
