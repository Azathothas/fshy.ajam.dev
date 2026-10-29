# site

The public wiki, and its read-only API and MCP endpoint. Everything it serves comes from `data/`, through
`publish/build.py`.

| path | what it is |
| --- | --- |
| `wrangler.jsonc` | the Worker `fshy`: static assets from `dist/`, the custom domain `fshy.ajam.dev`, the API and MCP routes |
| `worker/` | the Worker: sql.js (SQLite in WebAssembly) over the store's Worker copy, the API, the MCP server |
| `worker/test/` | the Worker's tests: `run.mjs` runs under node with fake bindings; `smoke.mjs` runs the Worker on workerd with `wrangler dev` |
| `static/` | the stylesheet, the browser script, vendored MiniSearch 7.2.0 (MIT), `_headers` |
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
python publish/test_publish.py
```

`smoke.mjs` starts `wrangler dev` on port 8791, or on the port in `FSHY_SMOKE_PORT`. It asks the API, the SQL
route and the MCP endpoint, and it stops wrangler by the PID that it started.

## The pages

[`../publish/pages.py`](../publish/pages.py) writes every HTML page. `static/assets/style.css` and
`static/assets/app.js` are the only shared files that a page loads. There is no framework, no CSS or JS build
step, no web font and no request to another host. Light and dark follow `prefers-color-scheme`. The colour
tokens are at the top of the stylesheet.

| what a reader scans | where |
| --- | --- |
| verdict, name, parsed price, summary, then identity, card, phone, binding limit, evidence rung and freshness | every offer row: topic pages, rejected pages, best-per-need lists, the graveyard, search results |
| verdict, parsed price, identity, binding limit, evidence, freshness | the six facts at the top of each record, above the detail table |

Freshness and the filter chips are computed in the browser against today, so a page built today stays correct
tomorrow. Both asset URLs carry `?v=` and the first ten hex digits of the file's SHA-256. A deploy that changes
either file thus reaches a browser that holds the old copy, because `_headers` caches `/assets/*` for a day.

⚠ The page shell (header, topic bar, footer) repeats on about 2,900 provider pages, so each byte added to it is
paid on each of them. Keep markup that only the script uses, such as the ARIA state of the search box, in the
script. The footer links to the licence and to the report section of the about page with relative links, which
are short. Each record has a "report an error" link that opens the Correction form of the source repository with
the record filled in.

## Files for agents: llms.txt, llms-full.txt and Markdown pages

The same build writes a Markdown copy of the wiki for language models and agents that read files rather than call
the API. [`../publish/llms.py`](../publish/llms.py) generates each of these files from the public store, the same
store the HTML comes from. None is written by hand, and the leak scan reads them with the rest of `dist/`.

| path | what it holds |
| --- | --- |
| `/llms.txt` | the [llmstxt.org](https://llmstxt.org/) index: summary, how to read the files, every topic, every need, the API and the MCP endpoint |
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
date is the data's own. A version, the first 12 hex digits of the SHA-256 of every record's Markdown, changes
when a record changes.

**Serving.** `.md` is served as `text/markdown; charset=utf-8` and `.txt` as `text/plain; charset=utf-8`, with
`Cache-Control: public, max-age=300` and `Access-Control-Allow-Origin: *` from `static/_headers`. The paths there
do not overlap, because a second matching rule appends to a header instead of replacing it.

## Fork

A fork that serves the site on its own domain changes these settings, and nothing else:

| where | what |
| --- | --- |
| the environment of the build | `FSHY_ORIGIN`, the origin of the site, and `FSHY_REPO`, the URL of the source repository ([`../publish/README.md`](../publish/README.md)) |
| `wrangler.jsonc` | `routes`, the custom domain, and `vars.FSHY_HOST`, the host that the MCP endpoint accepts |

The MCP endpoint accepts its own host, `localhost`, `127.0.0.1`, `[::1]` and `*.workers.dev`. It refuses other
hosts with 403.

## Deploy

⚠ **The site is not deployed.** When it is, the deploy is a Cloudflare Workers Builds trigger on this
repository's `main`, with root directory `site/`, the build command
`npm ci --no-audit --no-fund && python3 ../publish/build.py --site dist`, and the deploy command
`npx wrangler deploy`. A publish pull request that merges then deploys the new data. A failed build, for
example a leak hit, keeps the previous version live.

## What the Worker serves

Static files are served without running the Worker. The Worker runs only for `/api/v1/search`,
`/api/v1/records`, `/api/v1/sql`, `/api/v1/need/*`, `/api/v1/worklist/*`, `/api/v1/record/*`,
`/api/v1/entity-search`, `/mcp` and `/r/*`. It loads the store's Worker copy once per isolate. That copy is the
public store without record JSON, leaves and evidence quotes, which are served as static files.

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
4. The rate limits: 30 SQL requests a minute for each address.

**Why `cpu_ms` is 2,500.** It is at least three times the costliest request that the Worker accepts. Measured on
2026-10-29 with `wrangler dev` (wrangler 4.154.0, sql.js 1.15.2) on the operator's computer. Each time is the
wall time of the request at the client, the largest of three. The CPU time is lower, because the cold load waits
on the assets.

| request | ms |
| --- | --- |
| the first request of an isolate, a search: the store load (107 ms) and the search | 260 |
| the first request, `need` or the MCP `get` of 5 full records | 158 to 165 |
| the first request, the costliest accepted statement that completes (below) | 574 |
| the first request, the costliest accepted statement: `count(DISTINCT ...)` over 1.5 million rows, stopped by the heap limit | 718 |
| a warm statement: `sum(length(printf('%1000s%1000s%1000s', ...)))` over `limit_row` x `fx` | 432 |
| a warm statement at the budget: `LIKE`, `strftime()`, `lower()`, 20 calls a row, `||` | 146 to 286 |
| the heaviest warm API request: `search` with offset 1,000 | 41 |
| every other warm API request and MCP tool (`records`, `need`, `worklist`, `get`, `entity`, `help`) | 22 or less |
| a refusal of the guard or the budget | 8 or less |

The costliest request is 718 ms, so 2,500 ms is a margin of 3.5. The hardware of the platform can be slower than
this computer. A statement that the budget accepts can still run longer: the weight does not see a long value
that a row builds. The platform stops that statement.

**Headers.** `static/_headers` sets a Content-Security-Policy on every page: scripts, styles, images and requests
come from the site itself only. `smoke.mjs` checks that `wrangler dev` sends it. A response of the Worker, for
example of the API, carries `nosniff` and `no-referrer` too.
