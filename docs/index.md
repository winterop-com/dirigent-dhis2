# dirigent-dhis2

**The DHIS2 adapter pack for dirigent.**

The pack contributes one connection kind, two JSON Schema formats, and seven blocks that speak
DHIS2's asynchronous jobs, import summaries, completeness registrations, metadata, tracker and
analytics reads as first-class steps. A pipeline that names `dhis2.data_value_set_export` says
what it wants of the instance; it does not assemble the call out of raw HTTP, parse the import
summary itself, or invent a way to follow a task feed.

Every block classifies its failures the way DHIS2 means them: an instance whose version the
client does not speak is refused rather than retried, a transport failure is transient, and an
import the instance did not take fails the step with the conflicts it named.

## What is in it

- The [`dhis2` connection kind](connection.md): one instance, its credential, and the client
  built from it.
- Two [formats](formats.md), `dhis2-uid` and `dhis2-period`, that a schema asserts against by
  writing `format:`.
- Seven [blocks](blocks.md): six operators and one sensor, all in the `dhis2` group.
- One [example](examples.md) document per operation, across five shelves.

## Install

Install the pack into a dirigent image:

```bash
uv pip install dirigent-dhis2
```

or add it to a project:

```bash
uv add dirigent-dhis2
```

Installing it is the whole of the configuration. The `dirigent.plugins.v1` entry point in the
pack's `pyproject.toml` is what an instance discovers it by, so after a restart the blocks are
in `dg blocks`, `dhis2` is a connection kind, and the two formats assert. There is no config
file to edit and no registry to touch.

## Its relation to dirigent

Dirigent is a generic pipeline orchestrator: pipelines are documents, blocks arrive as plugin
packages, and the catalog an instance assembles from its installed packs is what validates a
pipeline and renders the builder's forms. This pack is one of those packages and knows nothing
the engine has to know about; the engine knows nothing about DHIS2. What a pipeline is, how a
run is scheduled, what a connection or a schema is, and the whole of the CLI live in
[dirigent's own documentation](https://winterop-com.github.io/dirigent/).

## Licence

Copyright (c) 2026 Morten Olav Hansen. All rights reserved. The source is published for
reference only: no licence to use, copy, modify or distribute it is granted, and any use
beyond reading requires written permission.
