"""common.py: the duplicate-key loader, the schema gate, and the shared plumbing."""

import pytest
import yaml

import common


class TestYamlLoad:
    def test_parses_like_safe_load(self):
        assert common.yaml_load("a: 1\nb: [2, 3]\n") == {"a": 1, "b": [2, 3]}

    def test_rejects_duplicate_top_level_keys(self):
        # plain safe_load keeps only the last value, silently dropping an entry
        with pytest.raises(yaml.constructor.ConstructorError, match="duplicate key"):
            common.yaml_load("abc:\n  notes: one\nabc:\n  notes: two\n")

    def test_reports_both_line_numbers(self):
        with pytest.raises(yaml.constructor.ConstructorError) as exc:
            common.yaml_load("abc: 1\nxyz: 2\nabc: 3\n")
        assert "lines 1 and 3" in str(exc.value)

    def test_rejects_duplicates_at_any_depth(self):
        with pytest.raises(yaml.constructor.ConstructorError, match="duplicate key"):
            common.yaml_load("abc:\n  stories:\n    - url: u\n      url: v\n")


class TestValidStructure:
    def test_accepts_a_plain_crash_mapping(self):
        assert common.valid_structure({"abc": {"stories": [{"url": "u"}]}})

    def test_accepts_a_crash_with_no_stories_key(self):
        assert common.valid_structure({"abc": {"private_notes": "looked"}})

    @pytest.mark.parametrize(
        "data",
        [
            ["not", "a", "mapping"],
            {"abc": "not a mapping"},
            {"abc": {"stories": "not a list"}},
            {"abc": {"stories": ["not a mapping"]}},
            {common.COMMENTS_KEY: "not a list"},
            {common.COMMENTS_KEY: [1, 2]},
            {common.GENERAL_KEY: "not a list"},
            {common.GENERAL_KEY: ["not a mapping"]},
        ],
    )
    def test_rejects(self, data):
        assert not common.valid_structure(data)

    def test_accepts_the_special_keys_when_well_formed(self):
        assert common.valid_structure(
            {
                common.COMMENTS_KEY: ["a note"],
                common.GENERAL_KEY: [{"url": "u"}],
                "abc": {"stories": []},
            }
        )

    def test_treats_empty_special_keys_as_empty_lists(self):
        assert common.valid_structure(
            {common.COMMENTS_KEY: None, common.GENERAL_KEY: None}
        )


class TestStoryPaths:
    def test_exits_when_there_are_no_story_files(self, sandbox):
        with pytest.raises(SystemExit) as exc:
            common.story_paths()
        assert exc.value.code == 1

    def test_returns_every_file_when_stories_csv_is_absent(self, sandbox):
        sandbox.write("2026-01", "{}\n")
        sandbox.write("2025-12", "{}\n")
        assert len(common.story_paths()) == 2

    def test_changed_only_keeps_files_newer_than_stories_csv(self, sandbox):
        old = sandbox.write("2026-01", "{}\n")
        sandbox.stories_csv.write_text("crash_record_id\n")
        import os

        os.utime(old, (1, 1))  # comfortably older than the csv
        fresh = sandbox.write("2026-02", "{}\n")
        assert common.story_paths(changed_only=True) == [fresh]

    def test_all_ignores_the_cutoff(self, sandbox):
        import os

        old = sandbox.write("2026-01", "{}\n")
        sandbox.stories_csv.write_text("crash_record_id\n")
        os.utime(old, (1, 1))
        assert len(common.story_paths(changed_only=False)) == 1


class TestLoadStoryFile:
    def test_reads_a_valid_file(self, sandbox):
        path = sandbox.write("2026-01", "abc:\n  stories: []\n")
        assert common.load_story_file(path) == {"abc": {"stories": []}}

    def test_skips_invalid_yaml(self, sandbox, capsys):
        path = sandbox.write("2026-01", "abc: [unclosed\n")
        assert common.load_story_file(path) is None
        assert "invalid YAML" in capsys.readouterr().err

    def test_skips_unexpected_structure(self, sandbox, capsys):
        path = sandbox.write("2026-01", "- just\n- a list\n")
        assert common.load_story_file(path) is None
        assert "unexpected structure" in capsys.readouterr().err


class TestRewriteFile:
    def test_writes_and_counts_a_change(self, sandbox, capsys):
        path = sandbox.write("2026-01", "old\n")
        assert common.rewrite_file(path, "new\n", "formatted") == 1
        assert path.read_text() == "new\n"
        assert "formatted" in capsys.readouterr().out

    def test_leaves_an_identical_file_alone(self, sandbox, capsys):
        path = sandbox.write("2026-01", "same\n")
        assert common.rewrite_file(path, "same\n", "formatted") == 0
        assert "unchanged" in capsys.readouterr().out

    def test_dry_reports_without_writing(self, sandbox):
        path = sandbox.write("2026-01", "old\n")
        assert common.rewrite_file(path, "new\n", "formatted", dry=True) == 1
        assert path.read_text() == "old\n"


class TestIterStories:
    def test_yields_crash_stories_with_their_id(self):
        data = {"abc": {"stories": [{"url": "u1"}, {"url": "u2"}]}}
        assert list(common.iter_stories(data)) == [
            ("abc", {"url": "u1"}),
            ("abc", {"url": "u2"}),
        ]

    def test_general_stories_carry_a_blank_id(self):
        data = {common.GENERAL_KEY: [{"url": "g"}]}
        assert list(common.iter_stories(data)) == [("", {"url": "g"})]

    def test_skips_comments(self):
        data = {common.COMMENTS_KEY: ["a note"], "abc": {"stories": [{"url": "u"}]}}
        assert [i for i, _ in common.iter_stories(data)] == ["abc"]

    def test_tolerates_a_crash_with_no_stories(self):
        assert list(common.iter_stories({"abc": {"private_notes": "x"}})) == []


class TestCrashDate:
    def test_returns_the_date_and_caches_it(self, sandbox):
        sandbox.add_crash("abc", "2026-05-01 10:00")
        con = sandbox.connect()
        cache = {}
        assert common.crash_date(con, "abc", cache) == "2026-05-01 10:00"
        assert cache == {"abc": "2026-05-01 10:00"}

        con.close()  # a second lookup must come from the cache, not the db
        assert common.crash_date(con, "abc", cache) == "2026-05-01 10:00"

    def test_returns_none_for_an_unknown_crash(self, sandbox):
        with sandbox.connect() as con:
            assert common.crash_date(con, "nope", {}) is None
