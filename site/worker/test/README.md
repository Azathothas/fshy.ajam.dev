# Worker tests

Run from the repository root, after `npm install` in `site/`:

    node site/worker/test/run.mjs

They load `.tmp/fshy/worker.db` (override with `FSHY_DB`) and read record and entity files from `site/dist` (override with `FSHY_DIST`); no wrangler is needed.
