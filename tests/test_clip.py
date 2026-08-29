"""clip.py: url sourcing, rendering, and the failure paths. Never hits the network."""

import io
import sys

import pytest

import clip
import common
import format as fmt

URL_A = "https://abc7chicago.com/post/a"  # older
URL_B = "https://chi.streetsblog.org/2026/06/09/b"  # newer


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


def feed(monkeypatch, text):
    """Pipe text in as stdin (not a tty)."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))


class TestUrlsToClip:
    def test_the_argument_wins(self, monkeypatch):
        feed(monkeypatch, "https://from-stdin.example/\n")
        assert clip.urls_to_clip(URL_A) == [URL_A]

    def test_no_argument_reads_stdin(self, monkeypatch):
        feed(monkeypatch, f"{URL_A}\n{URL_B}\n")
        assert clip.urls_to_clip(None) == [URL_A, URL_B]

    def test_dash_reads_stdin(self, monkeypatch):
        feed(monkeypatch, f"{URL_A}\n")
        assert clip.urls_to_clip("-") == [URL_A]

    def test_strips_whitespace_and_drops_blank_lines(self, monkeypatch):
        feed(monkeypatch, f"\n  {URL_A}  \n\n\t\n{URL_B}\n\n")
        assert clip.urls_to_clip(None) == [URL_A, URL_B]

    def test_none_when_nothing_is_piped_in(self, monkeypatch):
        """A terminal has nothing to read; blocking on it would look like a hang."""
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        assert clip.urls_to_clip(None) is None

    def test_empty_stdin_is_an_empty_list(self, monkeypatch):
        feed(monkeypatch, "")
        assert clip.urls_to_clip(None) == []


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
        assert clip.main(URL_A) == 0
        out = capsys.readouterr().out
        assert out.startswith(f"- url: {URL_A}\n")
        assert "  title: A story\n" in out

    def test_reads_a_url_from_stdin(self, pages, monkeypatch, capsys):
        feed(monkeypatch, f"{URL_A}\n")
        assert clip.main() == 0
        assert URL_A in capsys.readouterr().out

    def test_indent_shifts_the_whole_entry(self, pages, capsys):
        clip.main(URL_A, indent=4)
        assert capsys.readouterr().out.startswith(f"    - url: {URL_A}\n")

    def test_multiple_urls_come_out_oldest_first(self, pages, monkeypatch, capsys):
        feed(monkeypatch, f"{URL_B}\n{URL_A}\n")  # newest first on the way in
        assert clip.main() == 0
        out = capsys.readouterr().out
        assert out.index(URL_A) < out.index(URL_B)

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
        assert clip.main(URL_A) == 2
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


class TestFormatStability:
    """The reason clip renders through format.py instead of echoing qlip's YAML."""

    CRASH_ID = "abc123"

    def paste_under_stories(self, entries):
        return f"{self.CRASH_ID}:\n  stories:\n{entries}\n"

    def test_one_entry_survives_format_untouched(self, pages, capsys):
        clip.main(URL_A, indent=4)
        pasted = self.paste_under_stories(capsys.readouterr().out.rstrip("\n"))
        assert fmt.render_file(common.yaml_load(pasted)) == pasted

    def test_several_entries_survive_format_untouched(self, pages, monkeypatch, capsys):
        feed(monkeypatch, f"{URL_B}\n{URL_A}\n")
        clip.main(indent=4)
        pasted = self.paste_under_stories(capsys.readouterr().out.rstrip("\n"))
        assert fmt.render_file(common.yaml_load(pasted)) == pasted

    def test_a_one_line_description_is_a_plain_scalar_not_a_block(self, pages, capsys):
        """qlip's own renderer forces `|-` here, which format would rewrite."""
        clip.main(URL_A)
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
        clip.main("https://multi.example/")
        assert "description: |" in capsys.readouterr().out
