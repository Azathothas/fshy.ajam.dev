# Contributing

## Report an error in a record

Open an issue with the **Correction** form. Give:

- the record, for example `inference/groq` (the path under `data/records/` without `.json`);
- what is wrong: the field, what the record says, and what the provider says now;
- the source: a link to the provider's own page, and the date you read it.

## Report an offer that is missing

Open an issue with the **New offer** form. Give the topic, the name of the provider, what it offers, and a link
to the provider's own page.

## What happens to a report

1. A merge session reads the issue. If it is a report about the corpus, it queues a question for the research
   lanes and labels the issue `queued`.
2. A research lane reads the provider's own pages and records what they say, with a capture and a quote. Your
   report is a lead: a record changes only when the provider's page supports the change.
3. A merge session reviews that research, merges it, and publishes it here. The issue then closes, with a link
   to the record.

## Pull requests

⛔ A pull request that changes `data/` is not merged. `data/` is written by `publish/export.py` from the
research repository, and a hand edit would be lost at the next publish. Report the correction with an issue.

A pull request that improves the site, the API or the publish tools is welcome. Follow
[`AGENTS.md`](AGENTS.md) and [`docs/conventions.md`](docs/conventions.md), and make
`python publish/build.py --site site/dist` and `node site/worker/test/run.mjs` pass.

## Scope

The catalogue is for research and education. It records technical facts. It does not give legal advice, and an
issue that asks whether a use is permitted is closed with a pointer to the provider's own rules.
