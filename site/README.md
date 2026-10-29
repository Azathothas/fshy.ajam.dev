# site

The public wiki, and its read-only API and MCP endpoint. Everything it serves comes from `data/`, through
`publish/build.py`.

| path | what it is |
| --- | --- |
| `wrangler.jsonc` | the Worker `fshy`: static assets from `dist/`, the custom domain `fshy.ajam.dev`, the API and MCP routes |
| `worker/` | the Worker: sql.js (SQLite in WebAssembly) over the store's Worker copy, the API, the MCP server |
| `worker/test/` | the Worker's tests: `run.mjs` runs under node with fake bindings; `smoke.mjs` runs the Worker on workerd with `wrangler dev` |
| `static/` | the stylesheet, the browser script, vendored MiniSearch 7.2.0 (MIT), the favicon, `_headers` |
| `dist/` | the built site. Generated, never committed |

## Build and preview

Node 22.15 or later is necessary. From the repository root:

```bash
python publish/build.py --site site/dist
cd site
npm ci --no-audit --no-fund
npx wrangler dev --port 8787
```

With npm 12, `npm ci` reports that the install scripts of `esbuild` and `workerd` are blocked. The build, the tests
and `wrangler dev` do not need them, so the message is safe to ignore.

The preview needs no Cloudflare account. It serves the pages, the API and the MCP endpoint on
`http://127.0.0.1:8787`. ⚠ The local rate limiting binding of `wrangler dev` can throw. The Worker then logs the
error once and allows the request, so the preview does not limit requests. In production the same rule applies:
a limiter that fails does not take the API down.

Then test the Worker and the files for agents from the repository root:

```bash
node site/worker/test/run.mjs
node site/worker/test/smoke.mjs
python publish/test_llms.py --site site/dist
python publish/test_weight.py --site site/dist
python publish/test_publish.py
```

`smoke.mjs` starts `wrangler dev` on port 8791, or on the port in `FSHY_SMOKE_PORT`. It asks the API, the SQL
route, the MCP endpoint, the route patterns of `wrangler.jsonc` and the download of the store, and it stops
wrangler by the PID that it started. `test_weight.py` fails when a page or a shared file is over its budget.

## The pages

[`../publish/pages.py`](../publish/pages.py) writes every HTML page. `static/assets/style.css` and
`static/assets/app.js` are the only shared files that a page loads. There is no framework, no CSS or JS build
step, no web font and no request to another host. Light and dark follow `prefers-color-scheme`. The colour
tokens are at the top of the stylesheet.

| what a reader scans | where |
| --- | --- |
| verdict, name, parsed price, one line, then free tier, identity, card, phone, limit, evidence and the stale date | every offer row: topic pages, paid and rejected pages, best-per-need lists, the graveyard, search results |
| the free allowance, then verdict, cost, identity, binding limit with its value, evidence, freshness | the facts at the top of each record, above the detail table |

A name that two records of one provider share gets the tier, the rest of the slug or the topic in parentheses.
The one line of a row is the summary of the free tier; for a rejected or dead offer, it says why. A topic page
lists the usable and the trial offers; the paid offers are on `/t/<topic>/paid/`. A provider with more than 12
records has a page for each record, `/p/<id>/<topic>--<slug>/`, and its own page lists them. Each run of a
non-Latin script carries its `lang`. The labels of a row are in the markup, so a reader mode, a text browser and
an agent get them. A key under the filter bar says what each word and mark means.

The browser computes freshness and the filter chips against today, so a page built today stays correct tomorrow.
The page says "stale on" a date; the script turns that into "fresh until" or "stale since". The script keeps the
pressed chips in `?f=` and the interface text in `?i=`, so a filtered list is a link. Without JavaScript the
filter bar stays hidden, and the search and compare pages name the API route that answers instead. Both asset
URLs carry `?v=` and the first ten hex digits of the file's SHA-256. A deploy that changes either file thus
reaches a browser that holds the old copy, because `_headers` caches `/assets/*` for a day.

⚠ The page shell (header, topic bar, footer) repeats on about 3,300 pages, so each byte added to it is paid on
each of them. `publish/test_weight.py` holds it under 2,200 bytes, and the shared stylesheet and script under
12,000 bytes gzip. Keep markup that only the script uses, such as the ARIA state of the search box, in the
script. The footer links to the licence and to the report section of the about page with relative links, which
are short. Each record has a "report an error" link that opens the Correction form of the source repository with
the record filled in.

## Files for agents: llms.txt, llms-full.txt and Markdown pages

The same build writes a Markdown copy of the wiki for language models and agents that read files rather than call
the API. [`../publish/llms.py`](../publish/llms.py) generates each of these files from the public store, the same
store the HTML comes from. None is written by hand, and the leak scan reads them with the rest of `dist/`.

| path | what it holds |
| --- | --- |
| `/llms.txt` | the [llmstxt.org](https://llmstxt.org/) index: summary, how to read the files, every topic that has records, every need, the API and the MCP endpoint |
| `/index.md` | the home page's Markdown version: the same text as `/llms.txt` |
| `/llms-full.txt` | how to read a record, and the index of the parts |
| `/t/<topic>/llms-full.txt` | one topic in full when it fits in one file, else the index of its parts |
| `/t/<topic>/llms-full-<group>[-<k>].txt` | a part: one verdict group (usable, trial, paid, rejected, dead), cut into balanced pieces when it is over the budget |
| `/t/<topic>.md`, `/t/<topic>/rejected.md` | the two topic pages: one line per record |
| `/p/<id>.md` | a provider page: every record of that provider in full |
| `/need/<id>.md` | a best-per-need ranking, with its SQL |

Each HTML page that has a Markdown version names it in one `<link rel="alternate" type="text/markdown">` line.

**Size.** A file holds at most 300,000 bytes (`BUDGET` in `llms.py`). The text measures about 3.7 bytes per
token, so that is about 81,000 tokens. One file thus fits a 128K-token context window with room for the question
and the answer. The whole corpus is about 14 MB, more than any window holds. It is split by topic, then by
verdict group, then into balanced parts, and a record is never cut.

**Order and determinism.** One order everywhere: topics in the wiki's order, then verdict, provider name and
record id. The same store gives the same bytes on every build, because no clock and no commit is read. The one
date is the data's own: `meta.as_of` of the data, the date that the manifest, the pages and `help.txt` give. A version, the first 12 hex digits of the SHA-256 of every record's Markdown, changes
when a record changes.

**Serving.** `.md` is served as `text/markdown; charset=utf-8` and `.txt` as `text/plain; charset=utf-8`, with
`Cache-Control: public, max-age=300` and `Access-Control-Allow-Origin: *` from `static/_headers`. The paths there
do not overlap, because a second matching rule appends to a header instead of replacing it. `test_llms.py` checks
that no file gets one header from two rules and that every `.md` and `.txt` file has a charset, and `smoke.mjs`
checks the headers that workerd sends. A topic with no record yet has no page, no Markdown file and no line in
`llms.txt` or the sitemap. The API still accepts it as a topic, with an empty list.

## Fork

A fork that serves the site on its own domain changes these settings, and nothing else:

| where | what |
| --- | --- |
| the environment of the build | `FSHY_ORIGIN`, the origin of the site, and `FSHY_REPO`, the URL of the source repository ([`../publish/README.md`](../publish/README.md)) |
| `wrangler.jsonc` | `routes`, the custom domain, and `vars.FSHY_HOST`, the host that the MCP endpoint accepts |

The MCP endpoint accepts its own host, `localhost`, `127.0.0.1`, `[::1]` and `*.workers.dev`. It refuses other
hosts with 403.

## Deploy

The job `deploy` of [`../.github/workflows/build.yml`](../.github/workflows/build.yml) deploys the site. It runs
after the job `build` passes, on a push to `main` and on a manual run on `main`. So a publish pull request that
merges deploys the new data. A failed build, for example a leak hit, keeps the previous version live.

1. The job `build` keeps `site/dist` as the artifact `site-dist` for 7 days. So the deploy uses the files that
   the checks read.
2. The job `deploy` installs wrangler with an `npm ci` that runs no package script, and runs `npx wrangler
   deploy` with the secrets `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`.
3. It reads `/data/manifest.json` from the live site until the manifest names the commit, for at most five
   minutes. Then the search API must answer with rows and with the commit in its header `x-fshy-commit`, and the
   MCP endpoint must list its tools. If not, the job fails, and the new version can be live.

| setting | where | what |
| --- | --- | --- |
| `FSHY_DEPLOY` | repository variable | the job runs only when it is `on`. Set it to `off` to stop deploys |
| `CLOUDFLARE_API_TOKEN` | secret of the environment `production` | a token for Workers Scripts (edit), Account Settings (read) and Workers Routes (edit) on the zone. It can change every Worker of the account |
| `CLOUDFLARE_ACCOUNT_ID` | secret of the environment `production` | the Cloudflare account. A secret, so the public log does not show it |
| `FSHY_ORIGIN` | repository variable, optional | the origin that the job checks; the default is `https://fshy.ajam.dev` |
| `production` | environment | only `main` can use it, so a pull request never gets the token |

`preview_urls` is `false` in `wrangler.jsonc`, so a deploy makes no public version URL on `workers.dev`.

To deploy again without a change, run the workflow `build` by hand on `main`. To go back to an earlier version:

- revert the commit on `main`, which builds and deploys again;
- or, for 7 days, re-run the job `deploy` of the run of an earlier commit, which deploys that run's artifact;
- or run `npx wrangler rollback` in `site/` with a token that can edit Workers.

⚠ Workers Builds in the Cloudflare dashboard must stay off for this Worker, or two deploys race.

## What the Worker serves

Static files are served without running the Worker. The Worker runs for every path of `/api/v1/`, except the
static files that the build writes there (`entity/*`, `names.json`, `needs.json`, `vocab.json`, `schema.sql`,
`help.txt`), and for `/mcp`, `/r/*` and `/data/fshy-public.sqlite.gz`. `run_worker_first` in `wrangler.jsonc`
lists them, and `smoke.mjs` checks the exceptions. So `/api/v1/` lists the routes, an unknown route gets a JSON
404, and a `.tsv` suffix works on every route. A file of `entity/*` that does not exist is the exception: the
assets answer it with the HTML 404 page, because the Worker does not see it. An unknown topic, verdict, group,
evidence or binding in a filter is a 400 that lists the terms of the vocabulary, and the topics are the ones of
`data/manifest.json`. The Worker loads the store's Worker copy once per isolate. That copy
is the public store without record JSON, leaves and evidence quotes, which are served as static files. The rate
limit runs before the load, so a request that gets 429 costs no load. The first search of an isolate reads the
name index that the build writes (`name_index` in `data/manifest.json`) and does not normalise every alias again.

**The download of the store.** The build writes the gzip of the public store in parts of 10 MiB under `data/w/`, and
`data/manifest.json` names them with the size and the SHA-256 of the whole file. The Worker streams the parts in
order at `/data/fshy-public.sqlite.gz`, so the URL stays one file, and no part nears the 25 MiB limit of a static
asset as the corpus grows. The route loads no store. The answer carries an ETag, the SHA-256 of the file. A request
with a matching `If-None-Match` gets 304 and no body. A request with one `Range` gets 206 and that range of the
joined file, so a client can resume. The route reads only the parts that the range touches, and `part_bytes` in the
manifest gives their size. A list of ranges, another unit and an invalid range are ignored, and the whole file is
sent.

The Worker does not cache an API answer at the edge: Workers Cache would bill the static requests that are free
now, and its key is the full URL, so a crawler that changes `q` or `offset` would gain nothing from it.

**The SQL route and the MCP tool `sql`.** The first two checks refuse a statement before it runs, with a 400
that says why. The platform stops what they miss.

1. The guard (`worker/guard.js`) accepts one statement that starts with SELECT, WITH, VALUES or EXPLAIN. It refuses
   a write or a session keyword outside a literal, a recursive CTE, and a function that is not on
   `ALLOWED_FUNCTIONS`. The functions left out build a value larger than their input (`hex()`, `quote()`, `char()`,
   `zeroblob()`, `randomblob()`, the JSON builders), make rows that the budget cannot size (`json_each()`), or need
   text that the store does not hold (`snippet()`). `printf()` and `format()` need a literal format string, a
   width or a precision of at most 1,000, and no `%q`, `%Q` or `%w`. The guard also refuses, outside a literal, a
   character that JavaScript or Python reads as white space and SQLite does not, for example U+FEFF or U+0085. It
   appends a LIMIT.
2. The statement budget (`worker/plan.js`) reads `EXPLAIN QUERY PLAN`, because sql.js has no progress handler. A
   scan reads a whole table, whatever words follow the name; so does a SEARCH with only a range constraint. A
   SEARCH with `=` reads the rows of the largest key of the column: the build writes it to the `keystat` table of
   the store. A full-text match reads every document. The steps of one loop chain run nested, and the rows of all
   the chains of a statement add up. Each row is weighted by the functions and operators that the statement
   evaluates. The budget refuses a chain with two steps that read over 1,000 rows each, or a statement whose
   weighted rows are over 5,000,000. A join with `=` on a column with small keys passes.
3. The backstops. SQLite may allocate 32 MiB (`PRAGMA hard_heap_limit`, with temporary tables in that memory): a
   statement that needs more gets a 400, and the store stays open. A result over 2,000,000 characters gets a 400.
   A failure of the WebAssembly engine gets a 503, and the next request loads the store again. `limits.cpu_ms`
   in `wrangler.jsonc` stops a request after 2,500 ms of CPU. Then the Worker cannot answer: the caller gets the
   platform's error page "Error 1102: Worker exceeded resource limits", not JSON. Cloudflare's documentation does
   not give its HTTP status. `wrangler dev` does not enforce `cpu_ms`: a statement of 573 ms ran there with
   `cpu_ms` set to 50.
4. The rate limits, for each address: 30 SQL requests a minute, and 120 other requests a minute. Each MCP
   `tools/call` counts one. A batch of MCP messages holds at most 5 messages, and at most 1 of them is a `sql` call.
   A batch over either limit gets a 400 and the JSON-RPC error -32600, before the rate limit counts it. The
   namespace ids of `wrangler.jsonc` (47201, 47202) are not the example values of the documentation, because two
   bindings with one id share their counters across the Workers of an account.

**Why `cpu_ms` is 2,500.** It is about three times the costliest request that the Worker accepts. Measured on
2026-10-29 with `wrangler dev` (wrangler 4.154.0, sql.js 1.15.2) on one computer, which ran other jobs at
the same time. Each time is the wall time of the request at the client, in three runs; a first request ran on a
new `wrangler dev` each time. The CPU column is `process.cpuUsage()` of the Worker's modules under node, after the
first request (a warm isolate). The store load comes from the header `Server-Timing` of the first request.

| request | ms at the client, 3 runs | CPU ms, node |
| --- | --- | --- |
| the first request of an isolate, a search: the store load (110 to 121) and the search | 238 to 246 | |
| the first request, `need` with 200 rows | 185 to 211 | |
| the first request, an MCP batch of 5 searches of 25 words each | 366 to 493 | |
| the first request, the costliest accepted statement that completes: `sum(length(printf('%1000s%1000s%1000s', ...)))` over `limit_row` x `fx` | 674 to 1,130 | |
| the first request, `count(DISTINCT ...)` over 1.5 million rows, stopped by the heap limit | 713 to 1,111 | |
| a warm statement: the `printf()` statement above | 683 to 702 | 547 to 579 |
| a warm statement: the `count(DISTINCT ...)` above | 794 to 800 | 594 to 672 |
| a warm statement at the budget: `strftime()` over `claim` x `capture` | 561 to 659 | |
| a warm MCP batch of 5 searches for `a`, 50 rows each | 256 to 289 | 360 to 375 |
| the heaviest warm API request: `search` for `a` | 57 to 63 | |
| `search` with one word 40 times, after the change that counts it once | 33 to 35 | |
| every other warm API request and MCP tool (`records`, `need`, `worklist`, `record`, `get`, `entity-search`) | 45 or less | |
| a refusal of the guard or the budget | 16 or less | |
| the download of the store, 16.6 MB streamed from 2 parts | 105 to 130 | |

The slowest run of the costliest request took 1,130 ms, and the middle run 700 ms, so 2,500 ms is a margin of 2.2
over the slowest run and 3.6 over the middle one. A wall time includes the wait on the assets, so the CPU time of
the same request is lower.

A `sql` call takes up to 672 ms of CPU and a search of a batch takes 75 ms, which is 360 to 375 ms for 5. A batch
holds at most 5 messages, and at most 1 of them is a `sql` call. So the costliest batch that the Worker accepts
takes 1 x 672 + 4 x 75 = 972 ms, and `cpu_ms` is 2.6 times that. The sum is derived from the table, and `run.mjs`
checks it with a margin of 2. Two `sql` calls would take 1,569 ms and leave 1.6, and five would take 2.7 to 3.4 s,
which is over `cpu_ms`, so the Worker refuses a second `sql` call in a batch.

The hardware of the platform can be slower than this computer. A statement that the budget accepts can still run
longer: the weight does not see a long value that a row builds. The platform stops that statement.

**Headers.** `static/_headers` sets a Content-Security-Policy on every page: scripts, styles, images and requests
come from the site itself only. `smoke.mjs` checks that `wrangler dev` sends it. A response of the Worker, for
example of the API, carries `nosniff` and `no-referrer` too.
