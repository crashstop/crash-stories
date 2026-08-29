"""The repo-root `q` dispatcher: routing, the `make` pipeline, and bare help."""

from pathlib import Path

import pytest


def route(q_module, monkeypatch, module_name, argv, attr="main"):
    """Run argv through q, with one module's entry point swapped for a spy.

    Returns the kwargs the dispatcher handed it.
    """
    seen = {}
    module = getattr(q_module, module_name)

    def spy(**kwargs):
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(module, attr, spy)
    assert q_module.main(argv) == 0
    return seen


class TestSubcommandRouting:
    @pytest.mark.parametrize(
        "argv,module_name,expected",
        [
            (["lint"], "lint", {"changed_only": True}),
            (["lint", "--all"], "lint", {"changed_only": False}),
            (["format"], "format", {"changed_only": True, "dry": False}),
            (
                ["format", "--all", "--dry"],
                "format",
                {"changed_only": False, "dry": True},
            ),
            (
                ["reconcile"],
                "reconcile",
                {"changed_only": True, "dry": False, "force_domain_lookup": True},
            ),
            (
                ["reconcile", "--no-force-domain-lookup"],
                "reconcile",
                {"changed_only": True, "dry": False, "force_domain_lookup": False},
            ),
            (["wrangle"], "wrangle", {"dry": False}),
            (["wrangle", "--dry"], "wrangle", {"dry": True}),
            (
                ["clip", "https://ex.com/a"],
                "clip",
                {"url": "https://ex.com/a", "crash_record_id": None, "indent": 0},
            ),
            (
                ["clip", "https://ex.com/a", "--id", "abc123"],
                "clip",
                {"url": "https://ex.com/a", "crash_record_id": "abc123", "indent": 0},
            ),
            (
                ["clip", "--id", "abc123"],  # url comes from stdin
                "clip",
                {"url": None, "crash_record_id": "abc123", "indent": 0},
            ),
            (
                ["clip", "--indent", "4"],
                "clip",
                {"url": None, "crash_record_id": None, "indent": 4},
            ),
            (["info", "abc123"], "info", {"crash_record_id": "abc123"}),
        ],
    )
    def test_flags_reach_the_right_main(
        self, q_module, monkeypatch, argv, module_name, expected
    ):
        assert route(q_module, monkeypatch, module_name, argv) == expected

    def test_a_second_positional_is_a_usage_error(self, q_module, capsys):
        """The crash id is --id, not a bare second argument."""
        with pytest.raises(SystemExit) as exc:
            q_module.main(["clip", "https://ex.com/a", "abc123"])
        assert exc.value.code == 2
        assert "unrecognized arguments: abc123" in capsys.readouterr().err

    def test_archive_story(self, q_module, monkeypatch):
        seen = route(
            q_module,
            monkeypatch,
            "archive",
            ["archive", "story", "https://ex.com/a"],
            attr="archive_story",
        )
        assert seen == {"url": "https://ex.com/a"}

    def test_archive_stories(self, q_module, monkeypatch):
        seen = route(
            q_module,
            monkeypatch,
            "archive",
            ["archive", "stories", "2026-01.yaml"],
            attr="archive_stories",
        )
        assert seen == {"path": "2026-01.yaml"}

    def test_exit_code_is_passed_through(self, q_module, monkeypatch):
        monkeypatch.setattr(q_module.lint, "main", lambda **kwargs: 3)
        assert q_module.main(["lint"]) == 3

    def test_unknown_subcommand_is_a_usage_error(self, q_module, capsys):
        with pytest.raises(SystemExit) as exc:
            q_module.main(["bogus"])
        assert exc.value.code == 2
        assert "invalid choice: 'bogus'" in capsys.readouterr().err


class TestBareInvocation:
    def test_no_subcommand_prints_the_subcommand_list(self, q_module, capsys):
        assert q_module.main([]) == 0
        out = capsys.readouterr().out
        for name in (
            "lint",
            "format",
            "reconcile",
            "wrangle",
            "clip",
            "info",
            "archive",
            "make",
        ):
            assert name in out

    def test_bare_archive_prints_archives_own_help(self, q_module, capsys):
        assert q_module.main(["archive"]) == 0
        out = capsys.readouterr().out
        assert "Wayback" in out
        assert "story" in out and "stories" in out


class TestMakePipeline:
    def steps(self, calls):
        def step(name, code):
            def run(**kwargs):
                calls.append((name, kwargs))
                return code

            return run

        return step

    def test_runs_every_step_in_order(self, q_module, monkeypatch):
        calls = []
        step = self.steps(calls)
        monkeypatch.setattr(
            q_module,
            "PIPELINE",
            (
                ("lint", step("lint", 0), ("changed_only",)),
                ("format", step("format", 0), ("changed_only", "dry")),
                ("wrangle", step("wrangle", 0), ("dry",)),
            ),
        )
        assert q_module.main(["make"]) == 0
        assert [name for name, _ in calls] == ["lint", "format", "wrangle"]

    def test_stops_at_the_first_failure(self, q_module, monkeypatch, capsys):
        calls = []
        step = self.steps(calls)
        monkeypatch.setattr(
            q_module,
            "PIPELINE",
            (
                ("lint", step("lint", 1), ("changed_only",)),
                ("format", step("format", 0), ("changed_only", "dry")),
            ),
        )
        assert q_module.main(["make"]) == 1
        assert [name for name, _ in calls] == ["lint"]
        assert "lint exited 1; stopping" in capsys.readouterr().err

    def test_each_flag_only_reaches_the_steps_that_take_it(self, q_module, monkeypatch):
        calls = []
        step = self.steps(calls)
        monkeypatch.setattr(
            q_module,
            "PIPELINE",
            (
                ("lint", step("lint", 0), ("changed_only",)),
                ("format", step("format", 0), ("changed_only", "dry")),
                ("wrangle", step("wrangle", 0), ("dry",)),
            ),
        )
        assert q_module.main(["make", "--all", "--dry"]) == 0
        assert dict(calls) == {
            "lint": {"changed_only": False},
            "format": {"changed_only": False, "dry": True},
            "wrangle": {"dry": True},
        }

    def test_the_real_pipeline_lints_first_and_wrangles_last(self, q_module):
        """lint gates the rewriting steps; wrangle rewrites the changed-only cutoff."""
        names = [name for name, _, _ in q_module.PIPELINE]
        assert names == ["lint", "format", "reconcile", "wrangle"]

    def test_every_pipeline_step_accepts_the_flags_it_is_handed(self, q_module):
        import inspect

        for name, main, accepts in q_module.PIPELINE:
            parameters = inspect.signature(main).parameters
            missing = [flag for flag in accepts if flag not in parameters]
            assert not missing, f"{name}.main() has no {missing} parameter"


class TestWiring:
    def test_every_subcommand_module_exposes_the_expected_shape(self, q_module):
        for module in q_module.SUBCOMMANDS:
            assert callable(getattr(module, "add_arguments", None)), module.__name__
            assert callable(getattr(module, "main", None)), module.__name__

    def test_archive_exposes_add_arguments_too(self, q_module):
        assert callable(q_module.archive.add_arguments)

    def test_help_lists_one_entry_per_subcommand(self, q_module, capsys):
        q_module.main([])
        out = capsys.readouterr().out
        expected = [m.__name__ for m in q_module.SUBCOMMANDS] + ["archive", "make"]
        # every subcommand is offered, and nothing else is
        listed = [name for name in expected if f"    {name} " in out]
        assert sorted(listed) == sorted(expected)

    def test_usage_docstring_mentions_every_subcommand(self, q_module):
        """The hand-written usage block at the top of `q` drifts easily."""
        doc = q_module.__doc__
        for module in q_module.SUBCOMMANDS:
            assert f"./q {module.__name__}" in doc, module.__name__
        assert "./q archive" in doc and "./q make" in doc

    def test_usage_docstring_calls_the_dispatcher_by_its_real_name(self, q_module):
        """The name in the docstring is hand-written; renaming the file leaves
        every `./<old name>` line in it pointing at a command that's gone."""
        name = Path(q_module.__file__).name
        stale = [
            line.strip()
            for line in q_module.__doc__.splitlines()
            if line.strip().startswith("./")
            and not line.strip().startswith(f"./{name}")
        ]
        assert not stale, f"usage lines not calling ./{name}: {stale}"
