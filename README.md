# related-stories for crashstop.org


For [crashstop.org](crashstop.org), I want to augment the raw (and consistently incomplete and narrow) crash record data with actual news stories and articles.


## How to contribute

Look up a crash's `crash_record_id` and `crash_date` and find (or create) its corresponding YAML file.

For example, to add stories to crash whose id is [de9b2a79a715688f...](https://crashcount.org/chicago/crashes/de9b2a79a715688fa212ea74fda5c0c96044924cfc9987adab7c5edddd5df1eba5414796a7e4bdde714c73960284937fa43729c65db1a91c57605f121721dda6):

- Look up its `crash_date`: June 5, 2026
- Look for the year-month YAML file: [stories/2026/2026-06.yaml](stories/2026/2026-06.yaml)
- If an entry for the crash doesn't exist, add it using the `crash_record_id` as key, with a `stories` key under it
- Then add a story entry as a list item under `stories`: at minimum, it should have keys `url`, `title`, and `date`

    ```yaml
    de9b2a79a715688fa212ea74fda5c0c96044924cfc9987adab7c5edddd5df1eba5414796a7e4bdde714c73960284937fa43729c65db1a91c57605f121721dda6:
      stories:
        - url: https://chi.streetsblog.org/2026/06/09/the-bike-ride-and-die-in-in-memory-of-fallen-complete-streets-planner-riley-oneil-was-a-life-affirming-event
          title: The bike ride and “die-in” in memory of fallen Complete Streets Planner Riley O’Neil was a life-affirming event
          date: 2026-06-09
          site: Chicago Streetsblog
          description: |
            O'Neil was doored in a non-protected bike lane. "No more people should die in the streets because their lives are not valued as much as driver convenience," said one organizer.

      notes: "optional stuff to show to the public site"
      private_notes: "optional documentation meant for other researchers and contributors"
    ```


Crash record entries can optionally have key/value pairs for `notes:STRING` and `private_notes:STRING`
Every entry must have at least one of these keys: `notes`, `private_notes`, `stories`

Many crash records don't have easily findable stories, so `private_notes` is a nice play to mark that record has been investigated and needs followup.

(NOT YET IMPLEMENTED) `notes` should be a place to manually annotate a crash record with unstructured (Markdown) text for public consumption.


## Dev stuff

Everything runs through [`./cli`](cli), the repo's task runner. `./cli --help` lists the subcommands; `./cli <subcommand> --help` explains one in full and lists its flags.

```sh
./cli clip URL              # turn a story url into a pasteable YAML entry
pbpaste | ./cli clip | pbcopy   # ...or take the url straight off the clipboard
./cli info CRASH_ID         # summarize a crash: when, where, who was hurt
./cli lint                  # check the story files
./cli lint --all            # ...every one of them, not just the recently changed
./cli make                  # lint, format, reconcile, wrangle — stops on the first failure
```

To type `cli` instead of `./cli`, add this to your `~/.zshrc` — it runs the `cli` of whatever repo you're standing in:

```sh
cli() {
  if [ -x ./cli ]; then ./cli "$@"; else print -u2 "no ./cli in $PWD"; return 127; fi
}
```

The scripts expect a `db.sqlite` symlink to the crashstop database, which should have a table named `crashes_serving`. `lint` and `reconcile` need it; `format`, `wrangle`, and `archive` don't.

Each subcommand is a script under `scripts/`, still runnable on its own (`python3 scripts/lint.py --all` is what `./cli lint --all` does):

- `./cli clip [<url>]` ([scripts/clip.py](scripts/clip.py)) — fetch a story url and print it as a story entry, ready to paste. Add `--indent 4` to line it up under a crash's `stories:` key. With no url argument (or `-`) it reads urls from stdin, one per line, so a url in the clipboard round-trips in one go: `pbpaste | ./cli clip --indent 4 | pbcopy`. Several urls give several entries, oldest first — the order `format` would put them in anyway. A url that won't fetch is reported on stderr and skipped; the rest still print and the exit code is 1. Needs [qlip](https://github.com/dannguyen/qlip) installed for the same interpreter (`pip install -e /path/to/qlip`) — it does the fetching and metadata extraction; the YAML rendering is `format.py`'s, so the entry comes out already formatted the way this repo wants it. `site` arrives as the bare domain and `./cli reconcile` swaps in the display name from `reference/domain-lookup.csv`.
- `./cli info <crash_record_id>` ([scripts/info.py](scripts/info.py)) — summarize one crash from db.sqlite: date, address and neighborhood, category (prefixed `hit-and-run` when it was one), the fatal/incap/injured counts, and a line per hurt person giving age, sex, and injury. Note the counts aren't additive — `incap` is a subset of `injured`, and `injured` excludes the people who died — while the person list below them covers everyone hurt, fatalities included, most severe first.

    ```
    2026-04-05 01:08
    6300 S KEDZIE AVE, chicago-lawn
    hit-and-run VEHICLE-TO-VEHICLE
    fatalities: 1 incap: 1 injured: 1
    - ? M FATAL
    - 22 F INCAPACITATING INJURY
    ```

- `./cli lint` ([scripts/lint.py](scripts/lint.py)) — ensure format correctness.
- `./cli format` ([scripts/format.py](scripts/format.py)) — format the `stories/**/*.yaml` files into a predictable style and arrangement (self-contained formatting only; no db needed).
- `./cli reconcile` ([scripts/reconcile.py](scripts/reconcile.py)) — apply rewrites that depend on external data: reordering crash records chronologically by their `crash_date` in db.sqlite, and deriving missing `site` values from story urls.
- `./cli wrangle` ([scripts/wrangle.py](scripts/wrangle.py)) — compile all the `stories/**/*.yaml` files into two CSV files: [stories.csv](stories.csv) (one row per story) and [notes.csv](notes.csv) (one row per crash-level `notes` entry: `crash_record_id`, `crash_yearmonth`, `content`).
- `./cli archive story <url>` / `./cli archive stories <path>` ([scripts/archive.py](scripts/archive.py)) — get Wayback Machine links, for one url or for every story in a month file that lacks an `archive_url`.

`lint`, `format`, and `reconcile` only look at files modified since `stories.csv` was last written; pass `--all` to cover every file. `format`, `reconcile`, and `wrangle` take `--dry` to report what they'd rewrite without touching anything. `./cli make [--all] [--dry]` passes each flag to the steps that accept it.

The `Makefile` still works (`make lint` and friends) but is now just a wrapper around `./cli`.

### Tests

```sh
python3 -m pytest        # 284 tests as of 2026-08-28, well under a second
```

They live in [tests/](tests), one module per script plus `test_cli.py` for the dispatcher. Nothing in the suite touches the network, the real `db.sqlite`, or the story files: the `sandbox` fixture in [tests/conftest.py](tests/conftest.py) points every path constant the scripts resolve at import time at a temp directory, and `fake_qlip` / `wayback` stand in for the two things that would otherwise make HTTP requests. `test_fixtures.py` guards that isolation — if a script grows a new module-level path and it isn't added to `REDIRECTS`, that test fails rather than letting the suite write into the repo.



### Random notes

To get a list of all site domain names (when creating the initial domain-lookup.csv list)

```sh
rg 'site: ([^\)]+)' -or '$1' ./stories/**/*.yaml \
  --no-heading --no-line-number --no-filename \
  | sort | uniq
```
