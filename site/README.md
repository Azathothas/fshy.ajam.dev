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
