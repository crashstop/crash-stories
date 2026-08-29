"""Meta-tests: the sandbox has to actually isolate, or every other test lies."""

from pathlib import Path

from conftest import REPO_ROOT, SCRIPT_MODULES


def test_sandbox_redirects_every_repo_path(sandbox):
    """Guard against a new module-level path constant escaping REDIRECTS.

    Without this, adding (say) a second output file to wrangle.py would leave
    the suite quietly writing into the real repo.
    """
    escaped = [
        f"{module.__name__}.{name} = {value}"
        for module in SCRIPT_MODULES
        for name, value in vars(module).items()
        if isinstance(value, Path)
        and (value == REPO_ROOT or REPO_ROOT in value.parents)
    ]
    assert not escaped, (
        "these still point into the real repo during a sandboxed test; "
        f"add them to REDIRECTS in conftest.py: {escaped}"
    )


def test_sandbox_starts_empty(sandbox):
    assert list(sandbox.stories.rglob("*.yaml")) == []
    assert not sandbox.stories_csv.exists()
    assert sandbox.db.exists()


def test_fake_qlip_raises_for_unregistered_urls(fake_qlip):
    fake_qlip.page("https://example.com/a", title="A")
    assert (
        fake_qlip.extract(
            fake_qlip.fetch("https://example.com/a"), "https://example.com/a"
        )["title"]
        == "A"
    )
    try:
        fake_qlip.fetch("https://example.com/missing")
    except RuntimeError:
        return
    raise AssertionError("unregistered url should have raised")
