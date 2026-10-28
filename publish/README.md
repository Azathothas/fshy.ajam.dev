# publish

The tools that write the published corpus and build everything that serves it. Python 3.9 or later, standard
library only.

## The two stages

| stage | command | input | output | who runs it |
| --- | --- | --- | --- | --- |
| export | `python publish/export.py --source ../f-research` | a checkout of the private research repository | `data/` | a merge session only |
| build | `python publish/build.py --site site/dist` | `data/` only | `.tmp/fshy/public.db`, `.tmp/fshy/worker.db`, `site/dist/` | anyone; CI; the deploy |

**Export.** It runs the research repository's own build of the public store:
`python ../f-research/scripts/fshy/build.py --repo ../f-research --public TMP`. The projection and its rules stay
in the research repository, because they name what they remove. Then it writes each record as
`data/records/<topic>/<slug>.json` and each other table as `data/tables/<table>.jsonl`. Rows are sorted and carry
no row numbers, so the diff of a publish shows exactly which records changed. Last, it scans every written file
with this repository's leak rules and with the research repository's leak rules. With one hit, `data/` does not
change.

**Build.** It loads `data/` into a SQLite store with `schema.sql`, rebuilds the leaf table and the full-text
index from the record files, and scans every text value of every table. With `--site`, it writes the wiki, the
API files and the Worker copy, then scans the site too. One leak hit fails the build.

## Files

| file | what it does |
| --- | --- |
| `export.py` | stage one, as above |
| `build.py` | stage two, as above; also `make_worker_db` and the leak scan |
| `site_gen.py` | the store to the data files of the site: the Worker copy in chunks, record and entity JSON, names, needs, vocabularies |
| `pages.py` | the HTML pages, the sitemap and `robots.txt` |
| `llms.py` | `llms.txt`, `llms-full.txt` and the Markdown versions of the pages, for agents ([`../site/README.md`](../site/README.md)) |
| `test_llms.py` | the selftest of `llms.py`, over the store that `build.py` writes |
| `primer.py` | the text primer of the store: schema, vocabularies, worked queries |
| `schema.sql` | the store schema, shared by the Worker |
| `rules/needs.json` | the best-per-need queries |
| `rules/leak.json` | the public leak rules: generic shapes only |

## Exit codes

0 done, 1 a check failed (a leak, a refused source build), 2 usage, 3 the source is not a research checkout.
