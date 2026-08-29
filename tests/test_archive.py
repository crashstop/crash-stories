"""archive.py: snapshot lookup, saving, and the in-place file rewrite.

Never touches the network — `wayback` replaces archive.urlopen.
"""

from urllib.error import HTTPError, URLError

import pytest

import archive
import common
import format as fmt

URL = "https://ex.com/a"


class FakeResponse:
    """Enough of an http.client.HTTPResponse for archive.py's two call sites."""

    def __init__(self, body=b"", final_url="", headers=None):
        self._body = body
        self._final = final_url
        self.headers = headers or {}

    def read(self, *args):
        return self._body

    def geturl(self):
        return self._final

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Wayback:
    """Scripted stand-in for web.archive.org."""

    def __init__(self):
        self.cdx = []  # rows json.load should see, or an exception to raise
        self.save = None  # FakeResponse to return, or an exception to raise
        self.requests = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.requests.append(url)
        if url.startswith("https://web.archive.org/cdx/"):
            return self._respond(self.cdx, lambda rows: FakeResponse(body=_json(rows)))
        if url.startswith(archive.SAVE_ENDPOINT):
            return self._respond(self.save, lambda resp: resp)
        raise AssertionError(f"unexpected request: {url}")

    @staticmethod
    def _respond(scripted, build):
        if isinstance(scripted, Exception):
            raise scripted
        return build(scripted)

    @property
    def cdx_requests(self):
        return [u for u in self.requests if "/cdx/" in u]

    @property
    def save_requests(self):
        return [u for u in self.requests if u.startswith(archive.SAVE_ENDPOINT)]


def _json(rows):
    import json

    return json.dumps(rows).encode()


@pytest.fixture
def wayback(monkeypatch):
    fake = Wayback()
    monkeypatch.setattr(archive, "urlopen", fake)
    return fake


def http_error(code=503, reason="Service Unavailable"):
    return HTTPError(URL, code, reason, None, None)


class TestExistingSnapshot:
    def test_builds_the_snapshot_url_from_the_last_row(self, wayback):
        wayback.cdx = [
            ["timestamp", "original"],
            ["20240101000000", URL],
            ["20250601123000", URL],
        ]
        assert archive.existing_snapshot(URL) == (
            f"https://web.archive.org/web/20250601123000/{URL}"
        )

    def test_none_when_the_index_is_empty(self, wayback):
        wayback.cdx = []
        assert archive.existing_snapshot(URL) is None

    def test_none_when_only_the_header_row_comes_back(self, wayback):
        wayback.cdx = [["timestamp", "original"]]
        assert archive.existing_snapshot(URL) is None

    def test_encodes_query_characters_but_not_the_scheme_separators(self, wayback):
        wayback.cdx = []
        archive.existing_snapshot("https://ex.com/a?id=1&p=2")
        requested = wayback.cdx_requests[0]
        assert "https://ex.com/a" in requested  # ':' and '/' left alone
        assert "%3F" in requested and "%26" in requested and "%3D" in requested


class TestSaveSnapshot:
    def test_returns_the_redirect_target(self, wayback):
        final = f"https://web.archive.org/web/20260101000000/{URL}"
        wayback.save = FakeResponse(final_url=final)
        assert archive.save_snapshot(URL) == final

    def test_falls_back_to_the_content_location_header(self, wayback):
        wayback.save = FakeResponse(
            final_url="https://web.archive.org/save/" + URL,
            headers={"Content-Location": f"/web/20260101000000/{URL}"},
        )
        assert archive.save_snapshot(URL) == (
            f"https://web.archive.org/web/20260101000000/{URL}"
        )

    def test_none_when_neither_is_present(self, wayback):
        wayback.save = FakeResponse(final_url="https://web.archive.org/save/" + URL)
        assert archive.save_snapshot(URL) is None


class TestArchiveLink:
    def test_an_existing_snapshot_short_circuits_the_save(self, wayback, capsys):
        wayback.cdx = [["timestamp", "original"], ["20250601123000", URL]]
        assert archive.archive_link(URL).endswith(f"/20250601123000/{URL}")
        assert wayback.save_requests == []
        assert "using latest existing snapshot" in capsys.readouterr().err

    def test_saves_when_nothing_is_indexed_yet(self, wayback, capsys):
        wayback.cdx = []
        final = f"https://web.archive.org/web/20260101000000/{URL}"
        wayback.save = FakeResponse(final_url=final)
        assert archive.archive_link(URL) == final
        assert len(wayback.save_requests) == 1
        assert "saved" in capsys.readouterr().err

    def test_a_failed_lookup_still_falls_through_to_saving(self, wayback, capsys):
        wayback.cdx = URLError("connection reset")
        final = f"https://web.archive.org/web/20260101000000/{URL}"
        wayback.save = FakeResponse(final_url=final)
        assert archive.archive_link(URL) == final
        assert "availability lookup failed" in capsys.readouterr().err

    def test_reports_a_save_http_error_with_its_status(self, wayback, capsys):
        wayback.cdx = []
        wayback.save = http_error(429, "Too Many Requests")
        assert archive.archive_link(URL) is None
        assert "save failed: HTTP 429 Too Many Requests" in capsys.readouterr().err

    def test_reports_a_save_timeout(self, wayback, capsys):
        wayback.cdx = []
        wayback.save = TimeoutError("timed out")
        assert archive.archive_link(URL) is None
        assert "save failed: timed out" in capsys.readouterr().err

    def test_says_so_when_nothing_worked(self, wayback, capsys):
        wayback.cdx = URLError("down")
        wayback.save = URLError("down")
        assert archive.archive_link(URL) is None
        assert f"no archive link available for {URL}" in capsys.readouterr().err


class TestArchiveStory:
    def test_prints_the_link_to_stdout_and_exits_zero(self, wayback, capsys):
        wayback.cdx = [["timestamp", "original"], ["20250601123000", URL]]
        assert archive.archive_story(URL) == 0
        captured = capsys.readouterr()
        assert (
            captured.out.strip() == f"https://web.archive.org/web/20250601123000/{URL}"
        )
        assert "checking for an existing snapshot" in captured.err  # chatter is stderr

    def test_exits_one_with_empty_stdout_when_there_is_no_link(self, wayback, capsys):
        wayback.cdx = []
        wayback.save = FakeResponse(final_url="https://web.archive.org/save/" + URL)
        assert archive.archive_story(URL) == 1
        assert capsys.readouterr().out == ""


class TestArchiveStories:
    FILE = (
        "abc:\n  stories:\n"
        "    - url: https://ex.com/a\n      title: A\n      date: 2026-01-05\n"
    )

    def test_missing_file(self, sandbox, capsys):
        assert archive.archive_stories(sandbox.root / "nope.yaml") == 2
        assert "no such file" in capsys.readouterr().err

    def test_unparseable_file(self, sandbox, capsys):
        path = sandbox.write("2026-01", "abc: [unclosed\n")
        assert archive.archive_stories(path) == 2
        assert "invalid YAML" in capsys.readouterr().err

    def test_nothing_to_do_when_every_story_has_a_link(self, sandbox, wayback, capsys):
        text = self.FILE + "      archive_url: https://web.archive.org/web/1/u\n"
        path = sandbox.write("2026-01", text)
        assert archive.archive_stories(path) == 0
        assert path.read_text() == text
        assert wayback.requests == []
        assert "all stories already have an archive_url" in capsys.readouterr().err

    def test_fills_in_a_missing_link_and_rewrites_the_file(self, sandbox, wayback):
        path = sandbox.write("2026-01", self.FILE)
        wayback.cdx = [
            ["timestamp", "original"],
            ["20260101000000", "https://ex.com/a"],
        ]
        assert archive.archive_stories(path) == 0
        assert (
            "archive_url: https://web.archive.org/web/20260101000000/"
            in path.read_text()
        )

    def test_the_rewritten_file_is_formatted(self, sandbox, wayback):
        path = sandbox.write(
            "2026-01", "abc:\n  stories:\n  - title: A\n    url: https://ex.com/a\n"
        )
        wayback.cdx = [
            ["timestamp", "original"],
            ["20260101000000", "https://ex.com/a"],
        ]
        archive.archive_stories(path)
        text = path.read_text()
        assert fmt.render_file(common.yaml_load(text)) == text

    def test_covers_general_stories_too(self, sandbox, wayback):
        path = sandbox.write(
            "2026-01",
            f"{common.GENERAL_KEY}:\n  - url: https://ex.com/g\n    date: 2026-01-05\n",
        )
        wayback.cdx = [
            ["timestamp", "original"],
            ["20260101000000", "https://ex.com/g"],
        ]
        assert archive.archive_stories(path) == 0
        assert "archive_url:" in path.read_text()

    def test_skips_stories_that_have_no_url(self, sandbox, wayback, capsys):
        path = sandbox.write("2026-01", "abc:\n  stories:\n    - title: no url here\n")
        assert archive.archive_stories(path) == 0
        assert wayback.requests == []
        assert "already have an archive_url" in capsys.readouterr().err

    def test_a_partial_failure_still_writes_the_successes(
        self, sandbox, monkeypatch, capsys
    ):
        path = sandbox.write(
            "2026-01",
            "abc:\n  stories:\n"
            "    - url: https://ex.com/good\n      date: 2026-01-05\n\n"
            "    - url: https://ex.com/bad\n      date: 2026-01-06\n",
        )
        monkeypatch.setattr(
            archive,
            "archive_link",
            lambda url: "https://web.archive.org/web/1/good" if "good" in url else None,
        )
        assert archive.archive_stories(path) == 1
        text = path.read_text()
        assert text.count("archive_url:") == 1
        assert "1 archive_url(s) added, 1 failed" in capsys.readouterr().err

    def test_leaves_the_file_alone_when_every_url_fails(self, sandbox, monkeypatch):
        path = sandbox.write("2026-01", self.FILE)
        monkeypatch.setattr(archive, "archive_link", lambda url: None)
        assert archive.archive_stories(path) == 1
        assert path.read_text() == self.FILE  # not even reformatted


class TestCommandLine:
    def test_story_subcommand(self, monkeypatch):
        monkeypatch.setattr(
            archive, "archive_story", lambda url: 0 if url == URL else 9
        )
        assert archive.main(["story", URL]) == 0

    def test_stories_subcommand(self, monkeypatch):
        monkeypatch.setattr(
            archive, "archive_stories", lambda path: 0 if path == "p" else 9
        )
        assert archive.main(["stories", "p"]) == 0

    def test_bare_invocation_prints_help(self, capsys):
        assert archive.main([]) == 0
        out = capsys.readouterr().out
        assert "story" in out and "stories" in out

    def test_unknown_subcommand(self, capsys):
        with pytest.raises(SystemExit) as exc:
            archive.main(["bogus"])
        assert exc.value.code == 2
