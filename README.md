# dirigent-dhis2

The DHIS2 adapter pack for [dirigent](https://github.com/winterop-com/dirigent). It
contributes the `dhis2` connection kind, two JSON Schema formats (`dhis2-uid` and
`dhis2-period`), and the blocks that speak DHIS2's asynchronous jobs, import summaries,
completeness registrations, metadata, tracker and analytics reads as first-class steps,
rather than composing them out of raw HTTP:

| Block | Kind | What it does |
| --- | --- | --- |
| `dhis2.analytics_run` | operator | Submits the analytics tables job and follows its task notifications to the end. |
| `dhis2.analytics_query` | operator | Runs one analytics query, aggregate or event/enrollment, and hands the grid on. |
| `dhis2.data_value_set_export` | operator | Reads a data value set for a data set, period and org unit, inline or to storage. |
| `dhis2.data_value_set_import` | operator | Imports a data value set, parsing the import summary and its conflicts. |
| `dhis2.metadata` | operator | Reads one metadata collection through the version-bound generic accessor. |
| `dhis2.tracker` | operator | Reads a page of tracked entities, enrollments or events from `/api/tracker`. |
| `dhis2.data_set_complete` | sensor | Holds a run until a data set is marked complete for the period. |

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

## Develop

```bash
uv sync --locked
uv run ruff format --check . && uv run ruff check .
uv run mypy && uv run pyright
uv run pytest
```

That is what CI runs. The lock file is committed and CI syncs against it, so a pack build is
reproducible; the ecosystem's nightly integration is what proves the pack against the
current tips of its git dependencies.

`tests/` exercises every block against a mocked DHIS2 instance, and `tests/test_examples.py`
validates the example documents against the pack's own catalog. The examples run standalone,
each carrying the connection it uses.

## Examples

One file per operation, grouped by how it is built:

| Shelf | What is in it |
| --- | --- |
| [`examples/dhis2/`](examples/dhis2) | The native adapter: exports and their import strategies, the sign-off gate, the analytics reads and rebuilds, the three tracker collections, the metadata reads. |
| [`examples/dhis2-compose/`](examples/dhis2-compose) | A `dhis2.*` block beside one of the engine's own: a schema gate, a jq reshape, a fan-out over org units. |
| [`examples/dhis2-http/`](examples/dhis2-http) | The generic-HTTP way, for what no adapter covers: a CSV export, a period range, a completion registration, a stage-scoped event read. |
| [`examples/schemas/`](examples/schemas) | The JSON Schemas that pin the reads the DHIS2 series makes, applied on their own. |

Each shelf's README lists its files one line each.

## Licence

Copyright (c) 2026 Morten Olav Hansen. All rights reserved. See [LICENSE](LICENSE).

The source is published for reference only: no licence to use, copy, modify or distribute it
is granted, and any use beyond reading requires written permission.
