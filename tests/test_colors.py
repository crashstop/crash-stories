"""colors.py: when styling is emitted at all, and the two sign-off rules."""

import io
import sys

import pytest

import colors


class Tty(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture
def on(monkeypatch):
    """Colour turned on, via FORCE_COLOR rather than a fake terminal.

    Deliberately not `monkeypatch.setattr(sys, "stdout", Tty())`: pytest's fd
    capture reinstalls sys.stdout between the setup and call phases, so a stream
    swapped in from a fixture is gone by the time the test body runs. Tests that
    need a fake tty patch it inline. An env var survives the phase change.
    """
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")


class TestEnabled:
    def test_on_for_a_terminal(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("FORCE_COLOR", raising=False)
        monkeypatch.setattr(sys, "stdout", Tty())
        assert colors.enabled()

    def test_off_when_the_stream_is_not_a_terminal(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("FORCE_COLOR", raising=False)
        monkeypatch.setattr(sys, "stdout", io.StringIO())
        assert not colors.enabled()

    def test_no_color_wins_over_a_terminal(self, monkeypatch):
        monkeypatch.delenv("FORCE_COLOR", raising=False)
        monkeypatch.setenv("NO_COLOR", "")  # any value, even empty
        monkeypatch.setattr(sys, "stdout", Tty())
        assert not colors.enabled()

    def test_no_color_wins_over_force_color(self, monkeypatch):
        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.setenv("FORCE_COLOR", "1")
        assert not colors.enabled()

    def test_force_color_works_off_a_terminal(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setenv("FORCE_COLOR", "1")
        monkeypatch.setattr(sys, "stdout", io.StringIO())
        assert colors.enabled()

    def test_a_closed_stream_is_not_a_terminal(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("FORCE_COLOR", raising=False)
        closed = io.StringIO()
        closed.close()
        assert not colors.enabled(closed)

    def test_a_stream_without_isatty_is_not_a_terminal(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("FORCE_COLOR", raising=False)
        assert not colors.enabled(object())

    def test_is_decided_per_call_not_at_import(self, monkeypatch):
        """Otherwise a script that swaps stdout mid-run would style the wrong stream."""
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("FORCE_COLOR", raising=False)
        monkeypatch.setattr(sys, "stdout", io.StringIO())
        assert not colors.enabled()
        monkeypatch.setattr(sys, "stdout", Tty())
        assert colors.enabled()


class TestPaint:
    def test_wraps_in_the_named_codes(self, on):
        assert colors.paint("hi", "bold", "green") == "\033[1;32mhi\033[0m"

    def test_returns_the_text_unchanged_when_off(self, monkeypatch):
        monkeypatch.setenv("NO_COLOR", "1")
        assert colors.paint("hi", "bold", "green") == "hi"

    def test_empty_text_is_never_wrapped(self, on):
        """An empty styled string would emit codes around nothing."""
        assert colors.paint("", "red") == ""

    def test_unknown_style_is_a_programming_error(self, on):
        with pytest.raises(KeyError):
            colors.paint("hi", "chartreuse")


class TestDone:
    """The two rules: DONE is bold green; stats go magenta only on a change."""

    def test_the_sign_off_is_bold_green(self, on):
        assert colors.done("lint") == "\033[1;32mlint DONE\033[0m"

    def test_unchanged_stats_keep_their_default_colour(self, on):
        assert colors.done("format", "104 file(s) scanned, 0 reformatted") == (
            "\033[1;32mformat DONE\033[0m: 104 file(s) scanned, 0 reformatted"
        )

    def test_changed_stats_go_magenta(self, on):
        assert colors.done(
            "reconcile", "1 file(s) scanned, 1 reconciled", changed=True
        ) == (
            "\033[1;32mreconcile DONE\033[0m: \033[35m1 file(s) scanned, 1 reconciled\033[0m"
        )

    @pytest.mark.parametrize("changed", [False, True])
    def test_plain_text_is_identical_either_way_when_colour_is_off(
        self, monkeypatch, changed
    ):
        monkeypatch.setenv("NO_COLOR", "1")
        assert colors.done(
            "format", "1 file(s) scanned, 1 reformatted", changed=changed
        ) == ("format DONE: 1 file(s) scanned, 1 reformatted")

    def test_no_stats_means_no_colon(self, monkeypatch):
        monkeypatch.setenv("NO_COLOR", "1")
        assert colors.done("wrangle") == "wrangle DONE"


MAGENTA = "\033[35m"
BOLD_GREEN = "\033[1;32m"
DIM = "\033[2m"
RED = "\033[31m"


class TestScriptOutput:
    """The rules as the scripts actually apply them, end to end."""

    MESSY = "abc:\n  stories:\n  - title: T\n    url: u\n"
    TIDY = "abc:\n  private_notes: nothing to do here\n"

    def test_format_paints_the_stats_magenta_when_it_rewrote_something(
        self, sandbox, on, capsys
    ):
        import format as fmt

        sandbox.write("2026-01", self.MESSY)
        fmt.main(changed_only=False)
        out = capsys.readouterr().out
        assert f"{BOLD_GREEN}format DONE" in out
        assert f"{MAGENTA}1 file(s) scanned, 1 reformatted" in out

    def test_format_leaves_the_stats_plain_when_nothing_changed(
        self, sandbox, on, capsys
    ):
        import format as fmt

        sandbox.write("2026-01", self.TIDY)
        fmt.main(changed_only=False)
        out = capsys.readouterr().out
        assert f"{BOLD_GREEN}format DONE" in out
        assert "1 file(s) scanned, 0 reformatted" in out
        assert MAGENTA not in out

    def test_reconcile_follows_the_same_rule(self, sandbox, on, capsys):
        import reconcile

        sandbox.add_crash("abc", "2026-01-05 08:00")
        sandbox.write("2026-01", self.MESSY.replace("url: u", "url: https://ex.com/a"))
        reconcile.main(changed_only=False)
        out = capsys.readouterr().out
        assert f"{BOLD_GREEN}reconcile DONE" in out
        assert f"{MAGENTA}1 file(s) scanned, 1 reconciled" in out

    def test_a_rewritten_file_line_is_magenta_and_an_untouched_one_is_dim(
        self, sandbox, on, capsys
    ):
        import format as fmt

        sandbox.write("2026-01", self.MESSY)
        sandbox.write("2026-02", self.TIDY)
        fmt.main(changed_only=False)
        out = capsys.readouterr().out
        assert f"{MAGENTA}formatted stories/2026/2026-01.yaml" in out
        assert f"{DIM}unchanged stories/2026/2026-02.yaml" in out

    def test_lint_signs_off_green_and_keeps_a_clean_summary_plain(
        self, sandbox, on, capsys
    ):
        import lint

        sandbox.add_crash("abc", "2026-01-05 08:00")
        sandbox.write("2026-01", "abc:\n  private_notes: checked\n")
        assert lint.main(changed_only=False) == 0
        out = capsys.readouterr().out
        assert f"{BOLD_GREEN}lint DONE" in out
        assert f"{RED}summary:" not in out

    def test_lint_paints_the_summary_red_when_there_are_errors(
        self, sandbox, on, capsys
    ):
        import lint

        sandbox.write("2026-01", "abc:\n  private_notes: checked\n")  # not in db
        assert lint.main(changed_only=False) == 1
        out = capsys.readouterr().out
        assert f"{RED}- error:" in out
        assert f"{RED}summary:" in out

    def test_wrangle_paints_only_the_csv_whose_count_moved(self, sandbox, on, capsys):
        import wrangle

        sandbox.write("2026-01", "abc:\n  notes: n\n  stories:\n    - url: u1\n")
        wrangle.main()
        capsys.readouterr()

        # one more story, same number of notes
        sandbox.write(
            "2026-01", "abc:\n  notes: n\n  stories:\n    - url: u1\n    - url: u2\n"
        )
        wrangle.main()
        out = capsys.readouterr().out
        assert f"{MAGENTA}wrote stories.csv" in out
        assert "wrote notes.csv" in out and f"{MAGENTA}wrote notes.csv" not in out
        assert f"{BOLD_GREEN}wrangle DONE" in out

    def test_info_never_paints_its_summary(self, sandbox, on, capsys):
        """info writes text meant to be pasted into a yaml file, not read once."""
        import info

        sandbox.add_crash("abc", "2026-01-01 00:00", injured_tally=1)
        sandbox.add_person("abc", 30, "M", "NONINCAPACITATING INJURY")
        info.main("abc")
        assert "\033[" not in capsys.readouterr().out

    def test_clip_never_paints_its_yaml(self, on, fake_qlip, capsys):
        import clip

        fake_qlip.page("https://ex.com/a", title="T", date="2026-01-01")
        clip.main("https://ex.com/a")
        assert "\033[" not in capsys.readouterr().out

    def test_the_dry_tag_stays_outside_the_colour(self, sandbox, on, capsys):
        """`(dry) ` prefixes the styled sign-off rather than being swallowed by it."""
        import format as fmt

        sandbox.write("2026-01", self.MESSY)
        fmt.main(changed_only=False, dry=True)
        assert f"(dry) {BOLD_GREEN}format DONE" in capsys.readouterr().out


class TestStderrHelpers:
    """error/warning/note style against stderr, not stdout."""

    def test_they_ignore_whether_stdout_is_a_terminal(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("FORCE_COLOR", raising=False)
        monkeypatch.setattr(sys, "stdout", Tty())  # tty
        monkeypatch.setattr(sys, "stderr", io.StringIO())  # not a tty
        assert colors.error("boom") == "boom"

    def test_they_style_when_stderr_is_a_terminal(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("FORCE_COLOR", raising=False)
        monkeypatch.setattr(sys, "stdout", io.StringIO())  # not a tty
        monkeypatch.setattr(sys, "stderr", Tty())
        assert colors.error("boom") == "\033[31mboom\033[0m"
        assert colors.warning("hmm") == "\033[33mhmm\033[0m"
        assert colors.note("fyi") == "\033[2mfyi\033[0m"
