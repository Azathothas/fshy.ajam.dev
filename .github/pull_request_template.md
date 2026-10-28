## What this changes

<!-- What the change does, and why. A defect is cited by its file and line, never by a quote of the leak. -->

## Checks

- [ ] `data/` does not change. Only `publish/export.py` writes it, in a publish pull request.
- [ ] `python publish/build.py --site site/dist` passes, with 0 leaks.
- [ ] `node site/worker/test/run.mjs` passes. If the change is in `site/worker/`, `node site/worker/test/smoke.mjs` passes too.
- [ ] `python publish/test_llms.py --site site/dist` and `python publish/test_publish.py` pass.
- [ ] If a rule of `text.js`, `rank.js` or `guard.js` changes, `parity.json` changes with it (`node site/worker/test/parity.mjs --write`).
- [ ] This text, the commits and the files name no person, address, local path or private host, and credit no tool. CI scans this text with the leak rules.
