# Worker tests

Run from the repository root, after `npm ci` in `site/`:

    node site/worker/test/run.mjs
    node site/worker/test/smoke.mjs

`run.mjs` runs the Worker under node with fake bindings, and needs no wrangler. It loads `.tmp/fshy/worker.db`
(override with `FSHY_DB`) and reads record and entity files from `site/dist` (override with `FSHY_DIST`). Without
`site/dist`, the record file tests are skipped.

`smoke.mjs` runs the Worker on workerd with `wrangler dev` on port 8791 (override with `FSHY_SMOKE_PORT`). It needs
`site/dist`, asks the API, the SQL route, the MCP endpoint, the route patterns of `wrangler.jsonc` and the download
of the store, and stops wrangler by its PID. Then it runs `strand.mjs`.

`strand.mjs` runs `wrangler dev` on port 8792 (override with `FSHY_STRAND_PORT`) with the settings of
`wrangler.jsonc` and the entry point `strand.js`. It ends a request while the store loads, and checks that the
next requests answer (issue #26). It takes about 40 s, because one case waits `LOAD_WAIT_MS` of `worker/db.js`.

`live.mjs ORIGIN` asks the live site. The job deploy runs it after each deploy: no request to a route that opens
the store may wait longer than `LOAD_WAIT_MS` plus 5 s for its status. `site/README.md`, section Deploy, says what
it sends.
