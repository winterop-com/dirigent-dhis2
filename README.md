# dirigent-dhis2

[![PyPI](https://img.shields.io/pypi/v/dirigent-dhis2?label=pypi)](https://pypi.org/project/dirigent-dhis2/)
[![Python](https://img.shields.io/badge/python-3.13%2B-2b2f38)](https://pypi.org/project/dirigent-dhis2/)
[![CI](https://github.com/winterop-com/dirigent-dhis2/actions/workflows/ci.yaml/badge.svg?branch=main)](https://github.com/winterop-com/dirigent-dhis2/actions/workflows/ci.yaml)
[![Release](https://img.shields.io/github/v/release/winterop-com/dirigent-dhis2?label=release)](https://github.com/winterop-com/dirigent-dhis2/releases)
[![Docs](https://img.shields.io/badge/docs-winterop--com.github.io%2Fdirigent--dhis2-2b2f38)](https://winterop-com.github.io/dirigent-dhis2/)

Documentation: <https://winterop-com.github.io/dirigent-dhis2/>. New to dirigent and DHIS2
together? [**The tutorial**](https://winterop-com.github.io/dirigent-dhis2/tutorial/) is one
read, one schema gate and one rehearsed write against the public play demo, end to end.

The DHIS2 adapter pack for [dirigent](https://github.com/winterop-com/dirigent). It
contributes the `dhis2` connection kind, three JSON Schema formats (`dhis2-uid`,
`dhis2-period` and `dhis2-code`), and the blocks that speak DHIS2's asynchronous jobs, import
summaries, completeness registrations, metadata, tracker and analytics reads as first-class
steps, rather than composing them out of raw HTTP:

| Block | Kind | What it does |
| --- | --- | --- |
| `dhis2.analytics_run` | operator | Submits the analytics tables job and follows its task notifications to the end. |
| `dhis2.analytics_query` | operator | Runs one analytics query, aggregate or event/enrollment, and hands the grid on. |
| `dhis2.data_set_completion` | operator | Marks a data set complete, or reopens it, for a period and org unit, reading the import summary. |
| `dhis2.data_value` | operator | Gets, sets or deletes one data value; a dry run is rehearsed as a one-value data value set import. |
| `dhis2.data_value_set_export` | operator | Reads a data value set for a data set, period and org unit, and hands the document on. |
| `dhis2.data_value_set_import` | operator | Imports a data value set, parsing the import summary and its conflicts. |
| `dhis2.message` | operator | Sends a DHIS2 message to users, user groups or org units, which the instance also emails where SMTP is configured. |
| `dhis2.metadata` | operator | Reads one metadata collection through the version-bound generic accessor, whole or one page; a page of one counts it. |
| `dhis2.metadata_export` | operator | Reads several metadata collections in one `/api/metadata` request, every row of each, keyed by collection. |
| `dhis2.metadata_import` | operator | Creates, updates or deletes metadata from a bundle through `/api/metadata`, one object or many, reading the import report. |
| `dhis2.system_info` | operator | Reads `/api/system/info`: version, build, server clock and analytics state as named fields. |
| `dhis2.tracker` | operator | Reads a page of tracked entities, enrollments or events from `/api/tracker`. |
| `dhis2.tracker_import` | operator | Imports tracked entities, enrollments, events and relationships as a job it follows to the report. |
| `dhis2.data_set_complete` | sensor | Holds a run until a data set is marked complete for the period. |

Every write takes `dry_run`, which the instance validates and stores nothing for. It defaults
to off, as DHIS2's own flag does, and every example that writes turns it on.

Where a block takes DHIS2's own query terms, either shape does: `fields`, `filter` and `order`
each accept one string, spelled as the API spells it -- `id,name,valueType`, `level:eq:2`,
`name:asc` -- or a list, which the pack comma-joins or repeats as the resource wants.

Every block classifies its failures the dhis2w-client way: an instance whose version the
client does not speak is refused rather than retried, and a transport failure is transient.

An instance discovers the pack by installing it: the `dirigent.plugins.v1` entry point in
`pyproject.toml` is the whole registration.

## Install

Install the pack into the dirigent image:

```bash
uv pip install dirigent-dhis2
```

or add it to a project:

```bash
uv add dirigent-dhis2
```

or beside a tool-installed `dg`, or once without installing anything:

```bash
uv tool install dirigent-cli --with dirigent-dhis2
uvx --from dirigent-cli --with dirigent-dhis2 dg dev
```

The command is in `dirigent-cli`, so `uvx` always takes `--from dirigent-cli`. The pack pins its
dirigent packages at its own version, so a pinned install names the same release for both.

## Develop

```bash
uv sync --locked
uv run ruff format --check . && uv run ruff check .
uv run mypy && uv run pyright
uv run pytest
NO_MKDOCS_2_WARNING=1 uv run mkdocs build --strict
```

That block is what CI runs on every push and pull request. The variable silences Material's
notice about MkDocs 2.0. The lock file is committed and CI syncs against it, so a pack build is
reproducible; the ecosystem's nightly integration is what proves the pack still composes with
every other pack in one catalog.

The tutorial is published as a page and as paper. The PDF is printed from the built site with
headless Chromium, lands in `site/`, and is never committed. The `pages` workflow prints it on
every push to main, from the site it has just built; locally it is both steps:

```bash
uv run --with playwright playwright install chromium
uv run --with playwright python scripts/docs_pdf.py
```

The tutorial's pictures are taken from a throwaway `dg dev` with the pack installed. `catalog`
is the Blocks and Examples screens and needs no DHIS2; `walk` runs the tutorial's own documents
against the public play demo, reads and dry runs only. Both when neither is named:

```bash
uv run --with dirigent-cli --with playwright python scripts/docs_shots.py [catalog|walk]
```

`tests/` exercises every block against a mocked DHIS2 instance, and `tests/test_examples.py`
validates the example documents against the pack's own catalog. Every document runs standalone,
carrying the connection it uses.

## Examples

The shelves are installed with the pack: `dirigent_dhis2` contributes them through the
`examples()` hook, so an instance with the pack installed lists them with

```bash
dg examples list --plugin dhis2
dg examples list --plugin dhis2 --starter
```

They live in [`src/dirigent_dhis2/shelves/`](src/dirigent_dhis2/shelves), and the root
`examples/` is a symlink to it so `dg run --local examples/...` reads from a checkout.

One file per operation, grouped by how it is built:

| Shelf | What is in it |
| --- | --- |
| [`dhis2/`](src/dirigent_dhis2/shelves/dhis2) | The native adapter: exports and their import strategies, the sign-off gate, the analytics reads and rebuilds, the three tracker collections, the metadata reads, a system report. |
| [`dhis2-compose/`](src/dirigent_dhis2/shelves/dhis2-compose) | A `dhis2.*` block beside one of the engine's own: a schema gate, a jq reshape, a fan-out over org units, a write to storage and the read back. |
| [`dhis2-http/`](src/dirigent_dhis2/shelves/dhis2-http) | The generic-HTTP way, for what no adapter covers: a CSV export, a period range, a completion registration, a stage-scoped event read. |
| [`validate/`](src/dirigent_dhis2/shelves/validate) | A metadata read held to a shape: a `fields=` projection gated on `validate.schema`, with the schema carried and named. |
| [`schemas/`](src/dirigent_dhis2/shelves/schemas) | The JSON Schemas that pin the reads the DHIS2 series makes, applied on their own. |

Each shelf's README lists its files one line each. Every document carries the connection it
uses, coded `dhis2-demo`, so it runs standalone; a server refuses a carried connection, so what
an instance applies is a copy that names it instead. The seven documents tagged `starter` are
the flows `dg pipeline new` makes that copy from, dropping the `connections:` block and naming
`dhis2-demo` under `requires.connections`.

## Licence

Copyright (c) 2026 Morten Olav Hansen. All rights reserved. See [LICENSE](LICENSE).

The source is published for reference only: no licence to use, copy, modify or distribute it
is granted, and any use beyond reading requires written permission.
