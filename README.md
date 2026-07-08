# related-stories for crashstop.org


For [crashstop.org](crashstop.org), I want to augment the raw (and consistently incomplete and narrow) crash record data with actual news stories and articles.


## How to contribute

Look up a crash's `crash_record_id` and `crash_date` and find (or create) its corresponding YAML file.

For example, to add stories to crash whose id is [de9b2a79a715688f...](https://crashcount.org/chicago/crashes/de9b2a79a715688fa212ea74fda5c0c96044924cfc9987adab7c5edddd5df1eba5414796a7e4bdde714c73960284937fa43729c65db1a91c57605f121721dda6):

- Look up its `crash_date`: June 5, 2026
- Look for the year-month YAML file: [stories/2026/2026-06.yaml](stories/2026/2026-06.yaml)
- If an entry for the crash doesn't exist, add it using the `crash_record_id` as key, with a `stories` key under it
- Then add a story entry as a list item under `stories`: at minimum, it should have keys `url` and `title`

    ```yaml
    de9b2a79a715688fa212ea74fda5c0c96044924cfc9987adab7c5edddd5df1eba5414796a7e4bdde714c73960284937fa43729c65db1a91c57605f121721dda6:
      stories:
        - url: https://chi.streetsblog.org/2026/06/09/the-bike-ride-and-die-in-in-memory-of-fallen-complete-streets-planner-riley-oneil-was-a-life-affirming-event
          title: The bike ride and “die-in” in memory of fallen Complete Streets Planner Riley O’Neil was a life-affirming event
      notes: "optional stuff to show to the public site"
      private_notes: "optional documentation meant for other researchers and contributors"
    ```


Crash record entries can optionally have key/value pairs for `notes:STRING` and `private_notes:STRING`
Every entry must have at least one of these keys: `notes`, `private_notes`, `stories`

Many crash records don't have easily findable stories, so `private_notes` is a nice play to mark that record has been investigated and needs followup.

(NOT YET IMPLEMENTED) `notes` should be a place to manually annotate a crash record with unstructured (Markdown) text for public consumption.


## Dev stuff

The scripts expect a `db.sqlite` symlink to the crashstop database, which should have a table named `crashes_serving`

Run [scripts/validate_stories.py](scripts/validate_stories.py) to ensure format correctness.

Run [scripts/lint_stories.py](scripts/lint_stories.py) to format the `stories/**/*.yaml` files into a predictable style and arrangement.

Run [scripts/wrangle_stories.py](scripts/wrangle_stories.py) to compile all the `stories/**/*.yaml` files into two CSV files: [stories.csv](stories.csv) (one row per story) and [notes.csv](notes.csv) (one row per crash-level `notes` entry: `crash_record_id`, `crash_yearmonth`, `content`)
