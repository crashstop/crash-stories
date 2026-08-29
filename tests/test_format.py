"""format.py: key ordering, story ordering, and the renderer's exact output."""

from datetime import date, datetime, timezone

import pytest

import common
import format as fmt


class TestOrderStory:
    def test_puts_the_known_keys_in_canonical_order(self):
        story = {"date": "2026-01-01", "title": "T", "url": "u"}
        assert list(fmt.order_story(story)) == ["url", "title", "date"]

    def test_keeps_unknown_keys_after_the_known_ones(self):
        story = {"priority": 1, "url": "u", "title": "T"}
        assert list(fmt.order_story(story)) == ["url", "title", "priority"]

    def test_preserves_values(self):
        story = {"url": "u", "archive_url": "a"}
        assert fmt.order_story(story) == story


class TestStorySortKey:
    def test_orders_chronologically(self):
        stories = [{"date": "2026-03-01"}, {"date": "2026-01-01"}]
        assert [s["date"] for s in sorted(stories, key=fmt.story_sort_key)] == [
            "2026-01-01",
            "2026-03-01",
        ]

    def test_dateless_stories_sort_last(self):
        stories = [{"url": "u"}, {"date": "2026-01-01", "url": "v"}]
        assert [s["url"] for s in sorted(stories, key=fmt.story_sort_key)] == ["v", "u"]

    def test_url_breaks_a_date_tie(self):
        stories = [
            {"date": "2026-01-01", "url": "b"},
            {"date": "2026-01-01", "url": "a"},
        ]
        assert [s["url"] for s in sorted(stories, key=fmt.story_sort_key)] == ["a", "b"]

    def test_compares_aware_and_naive_dates(self):
        aware = {"date": "2026-01-01T23:00:00Z", "url": "aware"}
        naive = {"date": date(2026, 1, 2), "url": "naive"}
        assert [s["url"] for s in sorted([naive, aware], key=fmt.story_sort_key)] == [
            "aware",
            "naive",
        ]

    def test_unparseable_dates_sort_last_rather_than_raising(self):
        stories = [
            {"date": "not a date", "url": "bad"},
            {"date": "2026-01-01", "url": "ok"},
        ]
        assert [s["url"] for s in sorted(stories, key=fmt.story_sort_key)] == [
            "ok",
            "bad",
        ]


class TestToNaiveUtc:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (None, None),
            ("", None),
            ("   ", None),
            ("garbage", None),
            (date(2026, 1, 2), datetime(2026, 1, 2)),
            ("2026-01-02", datetime(2026, 1, 2)),
            ("2026-01-02T05:00:00+00:00", datetime(2026, 1, 2, 5)),
            (datetime(2026, 1, 2, 5, tzinfo=timezone.utc), datetime(2026, 1, 2, 5)),
        ],
    )
    def test_coercion(self, value, expected):
        assert fmt._to_naive_utc(value) == expected

    def test_falls_back_to_the_date_prefix(self):
        assert fmt._to_naive_utc("2026-01-02 nonsense") == datetime(2026, 1, 2)


class TestRenderStory:
    def test_renders_a_block_sequence_item_at_the_given_indent(self):
        rendered = fmt.render_story({"url": "u", "title": "T"}, indent="    ")
        assert rendered == "    - url: u\n      title: T"

    def test_defaults_to_four_space_indent(self):
        assert fmt.render_story({"url": "u"}).startswith("    - url: u")

    def test_single_line_description_stays_a_plain_scalar(self):
        rendered = fmt.render_story({"url": "u", "description": "one line"}, indent="")
        assert "description: one line" in rendered
        assert "|" not in rendered

    def test_multi_line_description_becomes_a_literal_block(self):
        rendered = fmt.render_story({"url": "u", "description": "a\nb\n"}, indent="")
        assert "description: |" in rendered

    def test_does_not_wrap_long_values(self):
        long_title = "x" * 500
        rendered = fmt.render_story({"url": "u", "title": long_title}, indent="")
        assert long_title in rendered


class TestRenderFile:
    def test_general_goes_first_and_comments_last(self):
        data = {
            common.COMMENTS_KEY: ["a comment"],
            "abc": {"stories": [{"url": "u"}]},
            common.GENERAL_KEY: [{"url": "g"}],
        }
        out = fmt.render_file(data)
        assert out.index("- url: g") < out.index("abc:") < out.index("a comment")

    def test_separates_crashes_with_a_blank_line(self):
        data = {"abc": {"private_notes": "x"}, "xyz": {"private_notes": "y"}}
        assert "\n\nxyz:" in fmt.render_file(data)

    def test_separates_stories_with_a_blank_line(self):
        data = {"abc": {"stories": [{"url": "a"}, {"url": "b"}]}}
        assert "\n\n    - url: b" in fmt.render_file(data)

    def test_orders_crash_keys_notes_private_notes_stories(self):
        data = {"abc": {"stories": [{"url": "u"}], "private_notes": "p", "notes": "n"}}
        out = fmt.render_file(data)
        assert out.index("notes:") < out.index("private_notes:") < out.index("stories:")

    def test_orders_stories_within_a_crash_by_date(self):
        data = {
            "abc": {
                "stories": [
                    {"url": "late", "date": "2026-06-01"},
                    {"url": "early", "date": "2026-01-01"},
                ]
            }
        }
        out = fmt.render_file(data)
        assert out.index("url: early") < out.index("url: late")

    def test_ends_with_exactly_one_newline(self):
        out = fmt.render_file({"abc": {"private_notes": "x"}})
        assert out.endswith("x\n") and not out.endswith("\n\n")

    def test_is_idempotent(self):
        data = {
            common.GENERAL_KEY: [{"url": "g", "date": "2026-01-01"}],
            "abc": {
                "notes": "n",
                "stories": [{"url": "u", "description": "multi\nline\n"}],
            },
            common.COMMENTS_KEY: ["c"],
        }
        once = fmt.render_file(data)
        assert fmt.render_file(common.yaml_load(once)) == once


class TestMain:
    MESSY = "abc:\n  stories:\n  - title: T\n    url: u\n"

    def test_reformats_a_file(self, sandbox):
        sandbox.add_crash("abc", "2026-01-05 08:00")
        sandbox.write("2026-01", self.MESSY)
        assert fmt.main(changed_only=False) == 0
        assert (
            sandbox.read("2026-01")
            == "abc:\n  stories:\n    - url: u\n      title: T\n"
        )

    def test_dry_leaves_the_file_alone(self, sandbox, capsys):
        sandbox.write("2026-01", self.MESSY)
        assert fmt.main(changed_only=False, dry=True) == 0
        assert sandbox.read("2026-01") == self.MESSY
        assert "(dry)" in capsys.readouterr().out

    def test_reports_how_many_it_touched(self, sandbox, capsys):
        sandbox.write("2026-01", self.MESSY)
        sandbox.write("2026-02", "xyz:\n  private_notes: fine\n")
        fmt.main(changed_only=False)
        out = capsys.readouterr().out
        assert "2 file(s) scanned, 1 reformatted" in out

    def test_skips_a_broken_file_without_dying(self, sandbox, capsys):
        sandbox.write("2026-01", "abc: [unclosed\n")
        sandbox.write("2026-02", self.MESSY.replace("abc", "xyz"))
        assert fmt.main(changed_only=False) == 0
        assert "invalid YAML" in capsys.readouterr().err
