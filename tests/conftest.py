"""Shared fixtures.

The scripts are meant to be run from the repo root, so they resolve their paths
once at import time into module-level constants — `common.ROOT/STORIES/DB/
STORIES_CSV`, plus the copies `lint`, `reconcile`, `wrangle`, `clip`, and
`info` bind into their own namespaces with `from common import ...`. The
`sandbox` fixture redirects every one of those at a throwaway directory, so no
test can read or write the real stories/ tree, db.sqlite, stories.csv, or
notes.csv.

`pythonpath = scripts` in pytest.ini makes `import lint` work here the same way
running `python3 scripts/lint.py` does.
"""

import importlib.util
import sqlite3
import sys
import types
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

import archive
import clip
import common
import format as fmt
import info
import lint
import reconcile
import wrangle

REPO_ROOT = Path(__file__).resolve().parent.parent

# Only the columns the scripts actually select. crashes_serving is a view in the
# real database; a plain table is indistinguishable from the query side.
#
# Nullability mirrors crash_meta's DDL — crash_date, category and the tallies are
# NOT NULL there, neighborhood_id is not — so a test can't set up a row the real
# database would never produce. The defaults just keep tests from having to spell
# out columns they don't care about.
SCHEMA = """
CREATE TABLE crashes_serving (
    crash_record_id TEXT PRIMARY KEY,
    crash_date      TEXT    NOT NULL,
    address         TEXT,
    neighborhood_id TEXT,
    category        TEXT    NOT NULL DEFAULT 'VEHICLE-TO-VEHICLE',
    hit_and_run_i   INTEGER NOT NULL DEFAULT 0,
    fatal_tally     INTEGER NOT NULL DEFAULT 0,
    incap_tally     INTEGER NOT NULL DEFAULT 0,
    injured_tally   INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE clean_people (
    person_id             TEXT PRIMARY KEY,
    crash_record_id       TEXT,
    age                   INTEGER,
    sex                   TEXT,
    injury_classification TEXT
);
"""


class Sandbox:
    """A throwaway stand-in for the repo: story files, a db, the output CSVs."""

    def __init__(self, root):
        self.root = root
        self.stories = root / "stories"
        self.db = root / "db.sqlite"
        self.stories_csv = root / "stories.csv"
        self.notes_csv = root / "notes.csv"
        self.lookup_csv = root / "reference" / "domain-lookup.csv"
        self._people = 0

    def write(self, stem, text):
        """Write stories/<year>/<stem>.yaml (stem like '2026-05'). Returns the path."""
        path = self.stories / stem[:4] / f"{stem}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def read(self, stem):
        return (self.stories / stem[:4] / f"{stem}.yaml").read_text()

    def connect(self):
        return sqlite3.connect(self.db)

    def add_crash(self, crash_id, crash_date, **columns):
        columns = {"crash_record_id": crash_id, "crash_date": crash_date, **columns}
        placeholders = ", ".join("?" * len(columns))
        with self.connect() as con:
            con.execute(
                f"INSERT INTO crashes_serving ({', '.join(columns)}) "
                f"VALUES ({placeholders})",
                tuple(columns.values()),
            )

    def add_person(self, crash_id, age, sex, injury, person_id=None):
        self._people += 1
        with self.connect() as con:
            con.execute(
                "INSERT INTO clean_people "
                "(person_id, crash_record_id, age, sex, injury_classification) "
                "VALUES (?, ?, ?, ?, ?)",
                (person_id or f"P{self._people:04d}", crash_id, age, sex, injury),
            )

    def write_lookup(self, rows):
        """rows: [(domain, site_name), ...] -> reference/domain-lookup.csv"""
        lines = ["domain,site_name"] + [f"{d},{n}" for d, n in rows]
        self.lookup_csv.write_text("\n".join(lines) + "\n")


# Every module-level path constant, and the module that owns the binding. A
# missing name makes monkeypatch.setattr raise, so this table can't quietly
# drift out of date with the scripts.
REDIRECTS = {
    "common": ("ROOT", "STORIES", "DB", "STORIES_CSV"),
    "lint": ("ROOT", "DB"),
    "reconcile": ("ROOT", "DB", "LOOKUP_CSV"),
    "wrangle": ("ROOT", "STORIES_CSV", "OUT", "NOTES_OUT"),
    "clip": ("ROOT", "STORIES", "DB"),
    "info": ("DB",),
}


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    box = Sandbox(tmp_path)
    box.stories.mkdir()
    box.lookup_csv.parent.mkdir()
    with box.connect() as con:
        con.executescript(SCHEMA)

    values = {
        "ROOT": box.root,
        "STORIES": box.stories,
        "DB": box.db,
        "STORIES_CSV": box.stories_csv,
        "OUT": box.stories_csv,
        "NOTES_OUT": box.notes_csv,
        "LOOKUP_CSV": box.lookup_csv,
    }
    for module_name, names in REDIRECTS.items():
        module = sys.modules[module_name]
        for name in names:
            monkeypatch.setattr(module, name, values[name])
    return box


@pytest.fixture
def q_module():
    """The repo-root `q` dispatcher, imported despite having no .py suffix."""
    loader = SourceFileLoader("q_under_test", str(REPO_ROOT / "q"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def fake_qlip(monkeypatch):
    """A stand-in qlip so clip tests never touch the network.

    Register pages with `fake_qlip.page(url, title=..., ...)`; any url that
    wasn't registered raises from fetch(), the way an unreachable one does.
    """
    module = types.ModuleType("qlip")
    pages = {}

    def page(url, **fields):
        pages[url] = {"site": None, "date": None, "description": None, **fields}

    def fetch(url, **kwargs):
        if url not in pages:
            raise RuntimeError("Failed to perform, curl: (6) Could not resolve host")
        return url  # stands in for html; extract() looks the url back up

    def extract(html, url):
        return {"url": url, **pages[html]}

    module.page = page
    module.fetch = fetch
    module.extract = extract
    monkeypatch.setitem(sys.modules, "qlip", module)
    return module


@pytest.fixture
def no_qlip(monkeypatch):
    """Make `import qlip` fail, as it does on a machine without it installed."""
    import builtins

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "qlip":
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "qlip", raising=False)
    monkeypatch.setattr(builtins, "__import__", blocked)


# archive has no path constants of its own today; it's in the list so the
# leakage guard notices if it grows one.
SCRIPT_MODULES = (common, lint, fmt, reconcile, wrangle, clip, info, archive)
