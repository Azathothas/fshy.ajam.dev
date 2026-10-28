# site

The public wiki, and its read-only API and MCP endpoint. Everything it serves comes from `data/`, through
`publish/build.py`.

| path | what it is |
| --- | --- |
| `wrangler.jsonc` | the Worker `fshy`: static assets from `dist/`, the custom domain `fshy.ajam.dev`, the API and MCP routes |
| `worker/` | the Worker: sql.js (SQLite in WebAssembly) over the store's Worker copy, the API, the MCP server |
| `worker/test/` | the Worker's tests; they run under node, with no wrangler |
| `static/` | the stylesheet, the browser script, vendored MiniSearch 7.2.0 (MIT), `_headers` |
| `dist/` | the built site. Generated, never committed |

## Build and preview

From the repository root:

```bash
python publish/build.py --site site/dist
cd site
npm ci --no-audit --no-fund
npx wrangler dev --port 8787
```

Then test the Worker from the repository root:

```bash
node site/worker/test/run.mjs
```

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
