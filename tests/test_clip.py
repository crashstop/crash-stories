"""clip.py: url sourcing, rendering, and the failure paths. Never hits the network."""

import io
import sys

import pytest

import clip
import common
import format as fmt

URL_A = "https://abc7chicago.com/post/a"  # older
URL_B = "https://chi.streetsblog.org/2026/06/09/b"  # newer

CRASH_ID = "c" * 8
CRASH_DATE = "2026-06-05 14:30"  # -> stories/2026/2026-06.yaml


@pytest.fixture
def pages(fake_qlip):
    fake_qlip.page(
        URL_A,
        title="A story",
        site="abc7chicago.com",
        date="2025-11-07T23:07:00Z",
        description="One line of description.",
    )
    fake_qlip.page(
        URL_B,
        title="B story",
        site="chi.streetsblog.org",
        date="2026-06-09T12:07:19+00:00",
        description="Another line.",
    )
    return fake_qlip


@pytest.fixture
def crashfile(sandbox):
    """One crash known to the db, with a stub entry in its month file."""
    sandbox.add_crash(CRASH_ID, CRASH_DATE)
    sandbox.write("2026-06", f"{CRASH_ID}:\n  private_notes: a stub\n")
    return sandbox


def feed(monkeypatch, text):
    """Pipe text in as stdin (not a tty)."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))


def urls_under(sandbox, stem, crash_id):
    """The story urls recorded for one crash in stories/<year>/<stem>.yaml."""
    entry = common.yaml_load(sandbox.read(stem))[crash_id]
    return [story["url"] for story in entry.get("stories") or []]


class TestUrlsToClip:
    def test_the_arguments_win(self, monkeypatch):
        feed(monkeypatch, "https://from-stdin.example/\n")
        assert clip.urls_to_clip([URL_A]) == [URL_A]

    def test_several_arguments_keep_their_order(self, monkeypatch):
        feed(monkeypatch, "https://from-stdin.example/\n")
        assert clip.urls_to_clip([URL_B, URL_A]) == [URL_B, URL_A]

    def test_no_arguments_reads_stdin(self, monkeypatch):
        feed(monkeypatch, f"{URL_A}\n{URL_B}\n")
        assert clip.urls_to_clip([]) == [URL_A, URL_B]

    def test_dash_reads_stdin(self, monkeypatch):
        feed(monkeypatch, f"{URL_A}\n")
        assert clip.urls_to_clip(["-"]) == [URL_A]

    def test_dash_splices_stdin_in_among_the_arguments(self, monkeypatch):
        feed(monkeypatch, "https://piped.example/\n")
        assert clip.urls_to_clip([URL_A, "-", URL_B]) == [
            URL_A,
            "https://piped.example/",
            URL_B,
        ]

    def test_a_repeated_dash_reads_stdin_once(self, monkeypatch):
        feed(monkeypatch, "https://piped.example/\n")
        assert clip.urls_to_clip(["-", "-"]) == ["https://piped.example/"]

    def test_strips_whitespace_and_drops_blank_lines(self, monkeypatch):
        feed(monkeypatch, f"\n  {URL_A}  \n\n\t\n{URL_B}\n\n")
        assert clip.urls_to_clip([]) == [URL_A, URL_B]

    def test_none_when_nothing_is_piped_in(self, monkeypatch):
        """A terminal has nothing to read; blocking on it would look like a hang."""
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        assert clip.urls_to_clip([]) is None

    def test_none_when_dash_asks_for_a_terminal_stdin(self, monkeypatch):
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        assert clip.urls_to_clip([URL_A, "-"]) is None

    def test_stdin_is_not_touched_when_no_argument_asks_for_it(self, monkeypatch):
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        assert clip.urls_to_clip([URL_A]) == [URL_A]

    def test_empty_stdin_is_an_empty_list(self, monkeypatch):
        feed(monkeypatch, "")
        assert clip.urls_to_clip([]) == []


class TestFetchStory:
    def test_returns_the_extracted_mapping(self, pages):
        story = clip.fetch_story(pages, URL_A)
        assert story["url"] == URL_A and story["title"] == "A story"

    def test_returns_none_and_reports_a_failure(self, pages, capsys):
        assert clip.fetch_story(pages, "https://unreachable.example/") is None
        err = capsys.readouterr().err
        assert err.startswith("error: https://unreachable.example/:")

    def test_notes_missing_required_fields(self, pages, capsys):
        pages.page("https://bare.example/", title=None, date=None)
        clip.fetch_story(pages, "https://bare.example/")
        assert "no title, date found on the page" in capsys.readouterr().err

    def test_no_note_when_everything_is_present(self, pages, capsys):
        clip.fetch_story(pages, URL_A)
        assert capsys.readouterr().err == ""


class TestMain:
    def test_renders_one_entry_from_an_argument(self, pages, capsys):
        assert clip.main([URL_A]) == 0
        out = capsys.readouterr().out
        assert out.startswith(f"- url: {URL_A}\n")
        assert "  title: A story\n" in out

    def test_reads_a_url_from_stdin(self, pages, monkeypatch, capsys):
        feed(monkeypatch, f"{URL_A}\n")
        assert clip.main() == 0
        assert URL_A in capsys.readouterr().out

    def test_indent_shifts_the_whole_entry(self, pages, capsys):
        clip.main([URL_A], indent=4)
        assert capsys.readouterr().out.startswith(f"    - url: {URL_A}\n")

    def test_multiple_urls_come_out_oldest_first(self, pages, monkeypatch, capsys):
        feed(monkeypatch, f"{URL_B}\n{URL_A}\n")  # newest first on the way in
        assert clip.main() == 0
        out = capsys.readouterr().out
        assert out.index(URL_A) < out.index(URL_B)

    def test_multiple_url_arguments_render_one_entry_each(self, pages, capsys):
        assert clip.main([URL_B, URL_A]) == 0
        out = capsys.readouterr().out
        assert out.count("- url: ") == 2
        assert out.index(URL_A) < out.index(URL_B)  # oldest first, as from stdin

    def test_multiple_entries_are_blank_line_separated(
        self, pages, monkeypatch, capsys
    ):
        feed(monkeypatch, f"{URL_A}\n{URL_B}\n")
        clip.main()
        assert f"\n\n- url: {URL_B}" in capsys.readouterr().out

    def test_a_bad_url_skips_but_the_rest_still_print(self, pages, monkeypatch, capsys):
        feed(monkeypatch, f"{URL_A}\nhttps://unreachable.example/\n")
        assert clip.main() == 1
        captured = capsys.readouterr()
        assert URL_A in captured.out
        assert "unreachable.example" not in captured.out
        assert "error:" in captured.err

    def test_returns_two_with_no_url_and_nothing_piped_in(
        self, pages, monkeypatch, capsys
    ):
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        assert clip.main() == 2
        assert "no url given" in capsys.readouterr().err

    def test_returns_two_on_empty_stdin(self, pages, monkeypatch, capsys):
        feed(monkeypatch, "\n  \n")
        assert clip.main() == 2
        assert "no urls on stdin" in capsys.readouterr().err

    def test_returns_two_when_qlip_is_not_installed(self, no_qlip, capsys):
        assert clip.main([URL_A]) == 2
        err = capsys.readouterr().err
        assert "needs qlip" in err
        assert sys.executable in err  # names the interpreter to install it for

    def test_a_missing_url_is_reported_before_qlip_is_even_imported(
        self, no_qlip, monkeypatch, capsys
    ):
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        assert clip.main() == 2
        err = capsys.readouterr().err
        assert "no url given" in err and "needs qlip" not in err


class TestInsertMode:
    """`clip <url> --id <crash_record_id>`: write the entry into the crash's file."""

    def test_a_stub_with_no_stories_key_gets_one(self, pages, crashfile):
        assert clip.main([URL_A], CRASH_ID) == 0
        assert urls_under(crashfile, "2026-06", CRASH_ID) == [URL_A]

    def test_the_stubs_other_keys_survive(self, pages, crashfile):
        clip.main([URL_A], CRASH_ID)
        entry = common.yaml_load(crashfile.read("2026-06"))[CRASH_ID]
        assert entry["private_notes"] == "a stub"

    def test_the_fetched_metadata_is_written_out(self, pages, crashfile):
        clip.main([URL_A], CRASH_ID)
        story = common.yaml_load(crashfile.read("2026-06"))[CRASH_ID]["stories"][0]
        assert story["title"] == "A story"
        assert story["description"] == "One line of description."

    def test_a_new_url_joins_an_existing_stories_list(self, pages, crashfile):
        crashfile.write(
            "2026-06",
            f"{CRASH_ID}:\n  stories:\n    - url: {URL_B}\n      title: B story\n"
            "      date: '2026-06-09T12:07:19+00:00'\n",
        )
        assert clip.main([URL_A], CRASH_ID) == 0
        # A (2025-11) is older than B, so format's chronological order puts it first
        assert urls_under(crashfile, "2026-06", CRASH_ID) == [URL_A, URL_B]

    def test_a_url_already_in_the_crash_is_refused(self, pages, crashfile, capsys):
        crashfile.write(
            "2026-06",
            f"{CRASH_ID}:\n  stories:\n    - url: {URL_A}\n      title: A story\n"
            "      date: '2025-11-07T23:07:00Z'\n",
        )
        before = crashfile.read("2026-06")
        assert clip.main([URL_A], CRASH_ID) == 1
        assert crashfile.read("2026-06") == before
        assert URL_A in capsys.readouterr().err

    def test_several_url_arguments_all_go_in(self, pages, crashfile):
        assert clip.main([URL_B, URL_A], CRASH_ID) == 0
        assert urls_under(crashfile, "2026-06", CRASH_ID) == [URL_A, URL_B]

    def test_a_duplicate_does_not_stop_the_other_urls(
        self, pages, crashfile, monkeypatch
    ):
        crashfile.write(
            "2026-06",
            f"{CRASH_ID}:\n  stories:\n    - url: {URL_A}\n      title: A story\n"
            "      date: '2025-11-07T23:07:00Z'\n",
        )
        feed(monkeypatch, f"{URL_A}\n{URL_B}\n")
        assert clip.main(crash_record_id=CRASH_ID) == 1
        assert urls_under(crashfile, "2026-06", CRASH_ID) == [URL_A, URL_B]

    def test_an_unfetchable_url_does_not_stop_the_others(
        self, pages, crashfile, monkeypatch
    ):
        feed(monkeypatch, f"{URL_A}\nhttps://unreachable.example/\n")
        assert clip.main(crash_record_id=CRASH_ID) == 1
        assert urls_under(crashfile, "2026-06", CRASH_ID) == [URL_A]

    def test_stdout_carries_the_status_line_not_the_entry(
        self, pages, crashfile, capsys
    ):
        clip.main([URL_A], CRASH_ID)
        out = capsys.readouterr().out
        assert "2026-06.yaml" in out
        assert "- url:" not in out

    def test_the_entry_is_echoed_to_stderr(self, pages, crashfile, capsys):
        """Insert mode writes the entry out of sight, so show what went in."""
        clip.main([URL_A], CRASH_ID)
        err = capsys.readouterr().err
        assert f"    - url: {URL_A}" in err  # indented as it sits in the file
        assert "      title: A story" in err

    def test_only_what_went_in_is_echoed(self, pages, crashfile, monkeypatch, capsys):
        crashfile.write(
            "2026-06",
            f"{CRASH_ID}:\n  stories:\n    - url: {URL_A}\n      title: A story\n"
            "      date: '2025-11-07T23:07:00Z'\n",
        )
        feed(monkeypatch, f"{URL_A}\n{URL_B}\n")
        clip.main(crash_record_id=CRASH_ID)
        assert f"- url: {URL_A}" not in capsys.readouterr().err  # the refused one

    def test_several_entries_are_echoed_oldest_first(
        self, pages, crashfile, monkeypatch, capsys
    ):
        feed(monkeypatch, f"{URL_B}\n{URL_A}\n")  # newest first on the way in
        clip.main(crash_record_id=CRASH_ID)
        err = capsys.readouterr().err
        assert err.index(URL_A) < err.index(URL_B)

    def test_indent_is_ignored(self, pages, crashfile):
        """render_crash sets the indentation; --indent only shapes stdout output."""
        clip.main([URL_A], CRASH_ID, indent=8)
        assert f"    - url: {URL_A}" in crashfile.read("2026-06")

    def test_the_file_comes_out_formatted(self, pages, crashfile):
        clip.main([URL_A], CRASH_ID)
        text = crashfile.read("2026-06")
        assert fmt.render_file(common.yaml_load(text)) == text

    def test_other_crashes_in_the_file_are_left_alone(self, pages, crashfile):
        other = "d" * 8
        crashfile.add_crash(other, "2026-06-20 09:00")
        crashfile.write(
            "2026-06",
            f"{CRASH_ID}:\n  private_notes: a stub\n\n{other}:\n  notes: untouched\n",
        )
        clip.main([URL_A], CRASH_ID)
        data = common.yaml_load(crashfile.read("2026-06"))
        assert data[other] == {"notes": "untouched"}

    def test_a_story_missing_a_required_field_still_goes_in(self, pages, crashfile):
        """Same as pasting one by hand: it lands, and lint is what catches it."""
        pages.page("https://bare.example/", title=None, date="2026-06-08")
        assert clip.main(["https://bare.example/"], CRASH_ID) == 0
        assert urls_under(crashfile, "2026-06", CRASH_ID) == ["https://bare.example/"]

    def test_a_story_missing_a_required_field_says_lint_will_flag_the_file(
        self, pages, crashfile, capsys
    ):
        pages.page("https://bare.example/", title=None, date="2026-06-08")
        clip.main(["https://bare.example/"], CRASH_ID)
        err = capsys.readouterr().err
        assert "title" in err and "2026-06.yaml" in err and "lint" in err

    def test_no_lint_warning_when_everything_came_back(self, pages, crashfile, capsys):
        clip.main([URL_A], CRASH_ID)
        assert "lint" not in capsys.readouterr().err

    def test_an_unknown_crash_id_is_an_error(self, pages, crashfile, capsys):
        assert clip.main([URL_A], "nosuchcrash") == 1
        assert "no crash nosuchcrash" in capsys.readouterr().err

    def test_a_crash_with_no_entry_in_its_month_file_is_an_error(
        self, pages, crashfile, capsys
    ):
        crashfile.write("2026-06", "e" * 8 + ":\n  notes: someone else\n")
        assert clip.main([URL_A], CRASH_ID) == 1
        err = capsys.readouterr().err
        assert "no entry" in err and CRASH_ID in err

    def test_a_missing_month_file_is_an_error(self, pages, sandbox, capsys):
        sandbox.add_crash(CRASH_ID, CRASH_DATE)
        assert clip.main([URL_A], CRASH_ID) == 1
        assert "2026-06.yaml" in capsys.readouterr().err

    def test_a_missing_database_is_an_environment_error(self, pages, sandbox, capsys):
        sandbox.db.unlink()
        assert clip.main([URL_A], CRASH_ID) == 2
        assert "database not found" in capsys.readouterr().err

    def test_nothing_is_fetched_when_the_crash_has_no_entry(
        self, pages, crashfile, capsys
    ):
        """The entry check comes first, so a bad id costs no network round-trips."""
        crashfile.write("2026-06", "e" * 8 + ":\n  notes: someone else\n")
        assert clip.main(["https://unreachable.example/"], CRASH_ID) == 1
        err = capsys.readouterr().err
        assert "no entry" in err
        assert "unreachable.example" not in err  # never got as far as fetching

    def test_a_missing_url_is_still_reported_first(
        self, crashfile, monkeypatch, capsys
    ):
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        assert clip.main([], CRASH_ID) == 2
        assert "no url given" in capsys.readouterr().err


class TestFormatStability:
    """The reason clip renders through format.py instead of echoing qlip's YAML."""

    CRASH_ID = "abc123"

    def paste_under_stories(self, entries):
        return f"{self.CRASH_ID}:\n  stories:\n{entries}\n"

    def test_one_entry_survives_format_untouched(self, pages, capsys):
        clip.main([URL_A], indent=4)
        pasted = self.paste_under_stories(capsys.readouterr().out.rstrip("\n"))
        assert fmt.render_file(common.yaml_load(pasted)) == pasted

    def test_several_entries_survive_format_untouched(self, pages, monkeypatch, capsys):
        feed(monkeypatch, f"{URL_B}\n{URL_A}\n")
        clip.main(indent=4)
        pasted = self.paste_under_stories(capsys.readouterr().out.rstrip("\n"))
        assert fmt.render_file(common.yaml_load(pasted)) == pasted

    def test_a_one_line_description_is_a_plain_scalar_not_a_block(self, pages, capsys):
        """qlip's own renderer forces `|-` here, which format would rewrite."""
        clip.main([URL_A])
        out = capsys.readouterr().out
        assert "description: One line of description." in out
        assert "|-" not in out

    def test_a_multi_line_description_becomes_a_literal_block(self, pages, capsys):
        pages.page(
            "https://multi.example/",
            title="M",
            date="2026-01-01",
            description="first\nsecond\n",
        )
        clip.main(["https://multi.example/"])
        assert "description: |" in capsys.readouterr().out
