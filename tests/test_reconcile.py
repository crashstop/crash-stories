"""reconcile.py: site derivation, the domain-lookup swap, chronological reordering."""

import pytest

import common
import reconcile


class TestDeriveSite:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://blockclubchicago.org/2026/01/a", "blockclubchicago.org"),
            ("https://www.fox32chicago.com/news/x", "fox32chicago.com"),
            ("http://chi.streetsblog.org/a", "chi.streetsblog.org"),
            ("not a url", None),
            ("", None),
        ],
    )
    def test_domain(self, url, expected):
        assert reconcile.derive_site(url) == expected


class TestNormalizeDomain:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("  ABC7Chicago.com ", "abc7chicago.com"),
            ("www.Example.ORG", "example.org"),
            ("example.org", "example.org"),
        ],
    )
    def test_normalization(self, value, expected):
        assert reconcile.normalize_domain(value) == expected


class TestLoadLookup:
    def test_reads_and_normalizes_keys(self, sandbox):
        sandbox.write_lookup([("WWW.ABC7chicago.com", "ABC 7 Chicago")])
        assert reconcile.load_lookup() == {"abc7chicago.com": "ABC 7 Chicago"}

    def test_skips_rows_missing_either_column(self, sandbox):
        sandbox.lookup_csv.write_text("domain,site_name\nex.com,\n,Name\nok.com,OK\n")
        assert reconcile.load_lookup() == {"ok.com": "OK"}

    def test_warns_and_degrades_when_absent(self, sandbox, capsys):
        assert reconcile.load_lookup() == {}
        assert "no lookup table" in capsys.readouterr().err


class TestFillSites:
    def test_fills_a_missing_site_from_the_url(self):
        data = {"abc": {"stories": [{"url": "https://www.ex.com/a"}]}}
        reconcile.fill_sites(data, {})
        assert data["abc"]["stories"][0]["site"] == "ex.com"

    def test_applies_the_lookup_display_name(self):
        data = {"abc": {"stories": [{"url": "https://ex.com/a"}]}}
        reconcile.fill_sites(data, {"ex.com": "Example News"})
        assert data["abc"]["stories"][0]["site"] == "Example News"

    def test_force_upgrades_a_site_still_holding_a_raw_domain(self):
        data = {"abc": {"stories": [{"url": "https://ex.com/a", "site": "ex.com"}]}}
        reconcile.fill_sites(data, {"ex.com": "Example News"})
        assert data["abc"]["stories"][0]["site"] == "Example News"

    def test_no_force_leaves_a_raw_domain_alone(self):
        data = {"abc": {"stories": [{"url": "https://ex.com/a", "site": "ex.com"}]}}
        reconcile.fill_sites(
            data, {"ex.com": "Example News"}, force_domain_lookup=False
        )
        assert data["abc"]["stories"][0]["site"] == "ex.com"

    def test_never_overwrites_a_display_name(self):
        data = {
            "abc": {"stories": [{"url": "https://ex.com/a", "site": "Example News"}]}
        }
        reconcile.fill_sites(data, {"ex.com": "Something Else"})
        assert data["abc"]["stories"][0]["site"] == "Example News"

    def test_leaves_a_urlless_story_alone(self):
        data = {"abc": {"stories": [{"title": "T"}]}}
        reconcile.fill_sites(data, {})
        assert "site" not in data["abc"]["stories"][0]

    def test_covers_general_stories_too(self):
        data = {common.GENERAL_KEY: [{"url": "https://ex.com/a"}]}
        reconcile.fill_sites(data, {"ex.com": "Example News"})
        assert data[common.GENERAL_KEY][0]["site"] == "Example News"


class TestReorderCrashes:
    def test_sorts_by_crash_date(self, sandbox):
        sandbox.add_crash("later", "2026-01-20 10:00")
        sandbox.add_crash("earlier", "2026-01-02 10:00")
        data = {"later": {"private_notes": "x"}, "earlier": {"private_notes": "y"}}
        with sandbox.connect() as con:
            assert list(reconcile.reorder_crashes(data, con, {})) == [
                "earlier",
                "later",
            ]

    def test_crashes_unknown_to_the_db_go_last_ordered_by_id(self, sandbox):
        sandbox.add_crash("known", "2026-01-20 10:00")
        data = {
            "zzz_unknown": {"private_notes": "x"},
            "aaa_unknown": {"private_notes": "y"},
            "known": {"private_notes": "z"},
        }
        with sandbox.connect() as con:
            ordered = list(reconcile.reorder_crashes(data, con, {}))
        assert ordered == ["known", "aaa_unknown", "zzz_unknown"]

    def test_special_keys_are_carried_through(self, sandbox):
        data = {
            common.COMMENTS_KEY: ["c"],
            "abc": {"private_notes": "x"},
            common.GENERAL_KEY: [{"url": "u"}],
        }
        with sandbox.connect() as con:
            ordered = reconcile.reorder_crashes(data, con, {})
        assert ordered[common.COMMENTS_KEY] == ["c"]
        assert ordered[common.GENERAL_KEY] == [{"url": "u"}]


class TestMain:
    FILE = (
        "later:\n  stories:\n    - url: https://ex.com/b\n      date: 2026-01-20\n\n"
        "earlier:\n  stories:\n    - url: https://ex.com/a\n      date: 2026-01-02\n"
    )

    def _seed(self, sandbox):
        sandbox.add_crash("later", "2026-01-20 10:00")
        sandbox.add_crash("earlier", "2026-01-02 10:00")
        sandbox.write_lookup([("ex.com", "Example News")])
        sandbox.write("2026-01", self.FILE)

    def test_reorders_and_fills_sites(self, sandbox):
        self._seed(sandbox)
        assert reconcile.main(changed_only=False) == 0
        out = sandbox.read("2026-01")
        assert out.index("earlier:") < out.index("later:")
        assert out.count("site: Example News") == 2

    def test_dry_writes_nothing(self, sandbox, capsys):
        self._seed(sandbox)
        assert reconcile.main(changed_only=False, dry=True) == 0
        assert sandbox.read("2026-01") == self.FILE
        assert "(dry)" in capsys.readouterr().out

    def test_returns_two_without_a_database(self, sandbox, capsys):
        self._seed(sandbox)
        sandbox.db.unlink()
        assert reconcile.main(changed_only=False) == 2
        assert "database not found" in capsys.readouterr().err

    def test_output_is_already_formatted(self, sandbox):
        """Files go out through format.py's renderer, so format has nothing left to do."""
        import format as fmt

        self._seed(sandbox)
        reconcile.main(changed_only=False)
        reconciled = sandbox.read("2026-01")
        assert fmt.render_file(common.yaml_load(reconciled)) == reconciled
