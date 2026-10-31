# publish

The tools that write the published corpus and build everything that serves it. Standard library only.

| tool | version |
| --- | --- |
| Python | 3.9 or later; CI uses 3.13 |
| Node | 22.15 or later, for wrangler and the Worker tests; CI uses 24 |
| git | any recent version, for the export |

Each Monday, Dependabot proposes updates of the actions and of the npm packages of `site/` at 04:00 UTC
([`../.github/dependabot.yml`](../.github/dependabot.yml)), and CI builds `main` at 06:00 UTC. A toolchain that
breaks thus shows before a publish does. The site serves a copy of MiniSearch, `site/static/assets/minisearch.js`.
`run.mjs` fails when that copy is not the npm package of `site/package.json`, so an update of MiniSearch fails
until a person copies its `dist/umd/index.js` there, with the header line. That update is a pull request of its own,
so its failed check holds no other update.

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
4. It checks the contract. The store must have a `schema_version` that `build.py` reads, and the tables and
   the columns of `schema.sql`. A store of an older version (`OLDER` of `build.py`) has the columns of
   `schema.sql` without the ones that the version lacks, and `data/` gets that version. `rules/needs.json` must be
   the same as the research copy. Each topic of the research schema must have a line in `rules/topics.json`.
5. It writes each record as `data/records/<topic>/<slug>.json` and each other table as
   `data/tables/<table>.jsonl`. Rows are sorted and carry no row numbers, so the diff of a publish shows exactly
   which records changed. `data/meta.json` names the commit as `source_commit`.
6. It builds a store from the written files with `build.py` and compares each table, the full-text index and the
   leaves with the research store. A value that the build drops or changes stops the export.
7. It scans every written file with this repository's leak rules, of both levels, and with the research
   repository's leak rules. `data/meta.json` gets `files_sha256`, one digest of every written file.
8. It renames the old `data/` aside, moves the new one in, and only then removes the old one.

With one failed check or one leak hit, `data/` does not change. The export refuses a source that is not a
research checkout. That is a directory that is not a git checkout, or a commit that does not hold `dossier/` and
`scripts/fshy/`. ⚠ The export replaces its target, so it writes only to `data/` of this repository or to a new or
empty directory. It refuses any other `--data` with exit 2, before it reads the source.

| option | what it does |
| --- | --- |
| `--ref REF` | export another commit of the source. It must be on `origin/main`. |
| `--no-fetch` | do not fetch `origin` first, for example with no network |
| `--allow-unmerged` | export a commit that is not on `origin/main`. Only with a `--data` other than `data/`, for a test |
| `--data DIR` | write to DIR instead of `data/`. DIR must be new or empty |

**Build.** It loads `data/` into a SQLite store with `schema.sql`, rebuilds the leaf table and the full-text index
from the record files, and scans every text value of every table. It reads data of `SCHEMA_VERSION` 3 and of the
older versions 2 and 1. Version 1 has no `record.self_hosted`: each record of version 1 is hosted (0). Versions 2
and 1 have no `ledger.op`: the op of each ledger row is NULL, and the site titles the row by its shape. It refuses data whose
`entity.best_vorder` is not the best verdict of the entity's hosted records (of all its records when every one is
self-hosted), with exit 3. A public history entry is its date, status,
title and linked records, so a history row with a body, a supersedes line or a confidence is a leak hit. With
`--site`, it writes the wiki, the API files and the Worker copy, scans every text file of the site, and checks the
size of each file against the static asset limit of Workers (25 MiB). It warns at 70 percent of that limit. It also
checks each page and each file for agents as it writes them, in memory: a list that puts a self-hosted record above
a hosted one, a self-hosted row with a star or a verdict pill, or a Markdown line of a self-hosted record that does not
open with its label, is an order problem
([`selfhosted.py`](selfhosted.py), and `AGENTS.md` rule 8). A dated changelog is not a list of offers: the page
`/changes/`, the feed `changes.xml` and the worklist `changes` keep their date order, and their rows carry no verdict
pill and no star, so the check does not read them. One leak hit, one file over the limit, or one order
problem fails the build. When `data/meta.json` has `files_sha256`, the build
recomputes it and refuses data that changed after the export, with exit 3. The scan of a directory runs in up to 8
processes when its files hold more than 16 MiB.

The store and the site do not name the commit of this repository: the same `data/` gives the same bytes, so a
merge that changes only code changes no page and no store. Only `data/manifest.json` names the commit of the
build, for the live check of the deploy and the header `x-fshy-commit` of the Worker.

## The leak rules

[`rules/leak.json`](rules/leak.json) holds generic shapes only. Each rule has a level:

| level | the build | the export |
| --- | --- | --- |
| `fail`, the default | fails on one hit | fails on one hit |
| `warn` | prints the count of hits of each rule, and passes | fails on one hit |

A `warn` rule is for a shape that the data on `main` still has, while the research repository removes it. The
export refuses the shape at once, so no new publish carries it. After the first publish whose build shows no
warning for the rule, remove its level, so the build fails on the shape too. A rule with a `scope`, for example
`history.title` or `history.hid`, reads only that column.

L15 to L20 (paths and search notes of the research process, its census, the workload of the reader, and
narrative history titles) fail since the publish of 2026-10-28 had no hit. L21 to L26 fail since the publish of
2026-10-29 had no hit: the word for the private record store, a section of an internal document, an earlier
batch of the research, its reasoning steps, a path into a private experiments folder, and a narrative history
id. L27 is `warn`: a phone number with an international prefix. It loses its level after the first publish whose
build shows no warning for it. A name that only the research repository knows, for example the name of a private
project, never goes in this public file; the research repository's own rules hold it.

To check a text before it becomes public, for example the body of a pull request or a comment, scan it:

```bash
python publish/build.py --scan draft.md
```

## Parity with the research repository

The research repository has Python twins of `site/worker/text.js`, `rank.js` and `guard.js`.
[`../site/worker/test/parity.json`](../site/worker/test/parity.json) holds inputs and the output of each JavaScript
rule. `run.mjs` checks the JavaScript against it in CI. The research CI checks the Python against it, at a commit
of this repository that the research repository pins. Its `guard_lists` holds the lists and the caps of `guard.js`
(the write keywords, the white space it refuses, the function allowlist, the words that are not calls, the
`printf()` width and conversions), so the twin reads them from the fixture. Its `rank.hostedFirst` and
`rank.entityOrder` hold the cases of the self-hosted rule: the stable split of a list, and the order of the entities
of a name search. `rank.bestVorder` holds the cases of the best verdict of an entity: of its hosted records, or of all
its records when every one is self-hosted. A case of `entityOrder` with `members` takes its `best_vorder` from them.
`rank.entityResolve` holds the cases of a name lookup, which gives one entity: the best score wins, and a hosted entity
wins only a tie. The twins are `hosted_first()`, `sort_entities()`, `resolve_entity()` and `best_vorder()` of `fr.py`,
and `entity.best_vorder` of the research `build.py`. The statement budget (`plan.js`) and
the heap limit have no twin: they need the Worker's copy of the store.

To change a rule, do these steps in this order:

1. In one pull request here, change the rule, run `node site/worker/test/parity.mjs --write`, and commit the new
   `parity.json`. Merge it.
2. In one pull request in the research repository, move the pin to the merge commit and change the Python twin.

Until step 2, the research CI keeps the old pin, so it stays green.

**The parity pin.** After a pull request here that changes `site/worker/` merges, the research repository moves
`scripts/fshy/public.lock` to its merge commit. It does this in its own pull request, together with any change of
the Python twin.

## The contract between export and build

`data/meta.json` names the `schema_version` of the data. `build.py` reads `SCHEMA_VERSION`, and the older versions
that `OLDER` names with the columns that each one lacks. A lacking column gets its default from `schema.sql`. The
export takes a research store of `SCHEMA_VERSION` or of a version of `OLDER`, and writes the version of the store.
The build refuses data of another version, a table file that `schema.sql` does not have, a missing table file, and an
unknown or missing column. It stops with exit 3 and a message that names the problem. ⚠ Without this check, a load
through the schema drops an unknown column and leaves a missing column empty, and the build still passes.

If the research repository adds a topic, add a line for it to `rules/topics.json` and an option to the New offer
form, in one pull request here, before the next publish. `test_publish.py` checks that the form agrees.

A change of the store schema lands here first. The research repository checks that its `schema.sql` is this one
at its pinned commit, so it follows after this pull request merges. Do these steps in one pull request here:

1. Change `schema.sql`, and the code in `build.py`, `site_gen.py`, `pages.py`, `llms.py` and `site/worker/` that
   reads the changed tables. A new column gets a default, for example `DEFAULT NULL`.
2. Increase `SCHEMA_VERSION` in `build.py`. Add the old version to `OLDER` with the columns that it lacks, and add
   those columns to each older version of `OLDER` too. The export then still takes the research store of the old
   version, so the next publish does not stop.
3. Build and run the tests. Add the new column to the export cases of `test_publish.py`, which check the
   contract on a store of the new version and of the old one.

Then the research repository changes its `schema.sql` and its version, and moves its pin, in its own pull request.
The first publish after that pull request merges gives `data/` of the new version.

## Files

| file | what it does |
| --- | --- |
| `export.py` | stage one, as above |
| `build.py` | stage two, as above; also `make_worker_db`, the leak scan and the asset size check |
| `site_gen.py` | the store to the data files of the site: the Worker copy in chunks, the public store in parts, the name index of the Worker, record and entity JSON, names, needs, vocabularies |
| `pages.py` | the HTML pages, the sitemap and `robots.txt` |
| `selfhosted.py` | the self-hosted rule of every list: the label, the stable split, and the order check of the build |
| `llms.py` | `llms.txt`, `llms-full.txt` and the Markdown versions of the pages, for agents ([`../site/README.md`](../site/README.md)) |
| `test_llms.py` | the selftest of `llms.py`, over the store that `build.py` writes |
| `test_publish.py` | the selftest of the contract and of `files_sha256`, of the export's refusals, of the leak rules and `--scan`, of the lists that are copied by hand, of the helpers that the pages share, of the self-hosted rule and its check, and of the worked queries of the primer |
| `test_weight.py` | the weight budget of the built site: the shared files, the page shell, and each kind of page |
| `fixture_selfhosted.py` | for CI: a copy of `data/` at the version of `build.py` in which some records are self-hosted, while `data/` has none, so that the build, `run.mjs` and `test_llms.py` test the self-hosted order on every pull request |
| `primer.py` | the text primer of the store: schema, vocabularies, worked queries |
| `schema.sql` | the store schema, shared by the Worker |
| `rules/needs.json` | the best-per-need queries |
| `rules/topics.json` | the one list of topics: id, name and description, in the order of the topic bar. `pages.py` and `llms.py` read it; `app.js` reads the topic bar of the page |
| `rules/leak.json` | the public leak rules: generic shapes only, each of level `fail` or `warn` (see "The leak rules") |

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
