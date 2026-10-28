# fshy

fshy is a catalogue of free, nearly free and cheapest-paid technical resources: storage, compute, GPU time,
model inference, crawling, egress, email, databases, DNS, CI runners, proxies, debrid services and netdisks.
Each record states what a service offers, what it costs, what a signup needs, which limit binds first, and the
evidence for each value.

⚠ **For research and education only.** The catalogue records technical facts about third-party services. It is
not legal advice, and it makes no statement about whether a use is permitted. The rules that each provider
publishes for its service apply to its use.

## What is here

| path | what it is |
| --- | --- |
| `data/records/<topic>/<slug>.json` | one record per offer: the published corpus |
| `data/tables/*.jsonl` | derived tables: entities, aliases, evidence, limits, claims, history and others |
| `data/meta.json` | the date the data is valid for, the source commit, and the counts |
| `publish/` | the tools that write `data/` and build the store and the site from it ([`publish/README.md`](publish/README.md)) |
| `site/` | the static wiki, the read-only HTTP API and the MCP endpoint ([`site/README.md`](site/README.md)) |
| `docs/` | how a reviewed change reaches this repository, and how to write here |

⛔ **Nothing in `data/` is edited by hand.** `publish/export.py` writes it. To correct a record, open an issue
(below).

## Use the data

Read a record directly, for example `data/records/inference/groq.json`. To query the whole corpus with SQL,
build the store:

```bash
python publish/build.py --check
```

This writes `.tmp/fshy/public.db`, a SQLite file. `python publish/primer.py .tmp/fshy/public.db` prints its
schema, its vocabularies and worked queries. To build the wiki and serve it locally, see
[`site/README.md`](site/README.md).

## Report an error or a missing offer

Open an issue with the **Correction** form or the **New offer** form. Give the record and a link to the
provider's own page. A report is a lead, not evidence: a research lane checks it against the provider's pages
before a record changes. The issue closes when a publish carries the result. See
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## How the data is made

The research happens in a separate, private repository. Every change there lands as a pull request. A merge
session that did not do the research reviews it and merges it. Then it exports the technical projection of the
corpus to this repository. The projection removes process notes, personal details and terms text. See
[`docs/merge-protocol.md`](docs/merge-protocol.md).

## Licence

[0BSD](LICENSE), for the data and the code. The records restate public facts in their own words and cite each
source by URL. A short quote identifies the sentence that proves a value.
