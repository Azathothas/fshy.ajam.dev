# publish

The tools that write the published corpus and build everything that serves it. Standard library only.

| tool | version |
| --- | --- |
| Python | 3.9 or later; CI uses 3.13 |
| Node | 22.15 or later, for wrangler and the Worker tests; CI uses 24 |
| git | any recent version, for the export |

Each Monday, Dependabot proposes updates of the actions and of the npm packages of `site/` at 04:00 UTC
([`../.github/dependabot.yml`](../.github/dependabot.yml)), and CI builds `main` at 06:00 UTC. A toolchain that
breaks thus shows before a publish does. MiniSearch is not updated there, because the site serves a copy of it.

## The two stages

| stage | command | input | output | who runs it |
| --- | --- | --- | --- | --- |
| export | `python publish/export.py --source ../f-research` | one commit of the private research repository | `data/` | a merge session only |
| build | `python publish/build.py --site site/dist` | `data/` only | `.tmp/fshy/public.db`, `.tmp/fshy/worker.db`, `site/dist/` | anyone; CI; the deploy |

**Export.** It publishes a commit, not a working tree.

1. It fetches `origin` in the source checkout and resolves `--ref` to one commit. The default ref is
   `origin/main`. It refuses a commit that is not on `origin/main`, because only merged research is published.
2. It clones the source into a temporary directory that shares the objects of the source, and checks out that
   commit with no line-end conversion. ⚠ It never reads the working tree of the source, so an edit that is not
   committed cannot reach `data/`.
3. It runs the research repository's own build of the public store in that clone:
   `python CLONE/scripts/fshy/build.py --repo CLONE --public TMP`. The projection and its rules stay in the
   research repository, because they name what they remove.
4. It checks the contract. The store must have the `schema_version` that `build.py` reads, and the tables and
   the columns of `schema.sql`. `rules/needs.json` must be the same as the research copy. Each topic of the
   research schema must have a line in `rules/topics.json`.
5. It writes each record as `data/records/<topic>/<slug>.json` and each other table as
   `data/tables/<table>.jsonl`. Rows are sorted and carry no row numbers, so the diff of a publish shows exactly
   which records changed. `data/meta.json` names the commit as `source_commit`.
6. It builds a store from the written files with `build.py` and compares each table, the full-text index and the
   leaves with the research store. A value that the build drops or changes stops the export.
7. It scans every written file with this repository's leak rules and with the research repository's leak rules.

With one failed check or one leak hit, `data/` does not change. The export refuses a source that is not a
research checkout. That is a directory that is not a git checkout, or a commit that does not hold `dossier/` and
`scripts/fshy/`.

| option | what it does |
| --- | --- |
| `--ref REF` | export another commit of the source. It must be on `origin/main`. |
| `--no-fetch` | do not fetch `origin` first, for example with no network |
| `--allow-unmerged` | export a commit that is not on `origin/main`. Only with a `--data` other than `data/`, for a test |
| `--data DIR` | write to DIR instead of `data/` |

**Build.** It loads `data/` into a SQLite store with `schema.sql`, rebuilds the leaf table and the full-text index
from the record files, and scans every text value of every table. A public history entry is its date, status,
title and linked records, so a history row with a body, a supersedes line or a confidence is a leak hit. With
`--site`, it writes the wiki, the API files and the Worker copy, scans every text file of the site, and checks the
size of each file against the static asset limit of Workers (25 MiB). It warns at 70 percent of that limit. One
leak hit, or one file over the limit, fails the build.

## The contract between export and build

`data/meta.json` names the `schema_version` of the data. `build.py` reads one version, `SCHEMA_VERSION`. It
refuses data of another version, a table file that `schema.sql` does not have, a missing table file, and an
unknown or missing column. It stops with exit 3 and a message that names the problem. ⚠ Without this check, a load
through the schema drops an unknown column and leaves a missing column empty, and the build still passes.

If the research repository adds a topic, add a line for it to `rules/topics.json` and an option to the New offer
form, in one pull request here, before the next publish. `test_publish.py` checks that the form agrees.

If the research repository changes its store schema, do these steps in one pull request here, before the next
publish:

1. Change `schema.sql`, and the code in `build.py`, `site_gen.py`, `pages.py` and `llms.py` that reads the
   changed tables.
2. Increase `SCHEMA_VERSION` in `build.py` to the version of the research store.
3. Export, build and run the tests.

## Files

| file | what it does |
| --- | --- |
| `export.py` | stage one, as above |
| `build.py` | stage two, as above; also `make_worker_db`, the leak scan and the asset size check |
| `site_gen.py` | the store to the data files of the site: the Worker copy in chunks, record and entity JSON, names, needs, vocabularies |
| `pages.py` | the HTML pages, the sitemap and `robots.txt` |
| `llms.py` | `llms.txt`, `llms-full.txt` and the Markdown versions of the pages, for agents ([`../site/README.md`](../site/README.md)) |
| `test_llms.py` | the selftest of `llms.py`, over the store that `build.py` writes |
| `test_publish.py` | the selftest of the contract, of the export's refusals, of the lists that are copied by hand, and of the worked queries of the primer |
| `primer.py` | the text primer of the store: schema, vocabularies, worked queries |
| `schema.sql` | the store schema, shared by the Worker |
| `rules/needs.json` | the best-per-need queries |
| `rules/topics.json` | the one list of topics: id, name and description, in the order of the topic bar. `pages.py` and `llms.py` read it; `app.js` reads the topic bar of the page |
| `rules/leak.json` | the public leak rules: generic shapes only |

## The origin of the site

`llms.py` reads two settings from the environment of the build. The default is this site.

| variable | default | what it sets |
| --- | --- | --- |
| `FSHY_ORIGIN` | `https://fshy.ajam.dev` | every absolute link: `llms.txt`, the Markdown pages, the sitemap, `robots.txt`, the feed and the MCP command |
| `FSHY_REPO` | `https://github.com/Azathothas/fshy.ajam.dev` | the report link of each record, the about page and `llms.txt` |

## Exit codes

| tool | 0 | 1 | 2 | 3 |
| --- | --- | --- | --- | --- |
| `export.py` | written | a check failed: a leak, a refused build, a contract problem, a commit not on `origin/main` | usage | the source is not a research checkout |
| `build.py` | built | a check failed: a leak, a file over the asset limit | usage | `data/` does not match this build |
