# DHIS2 examples: composed with the engine's own blocks

A `dhis2.*` step is rarely the whole pipeline. These documents put one beside a block the
engine itself contributes -- a schema gate, a jq reshape, a fan-out, a write to storage --
because that is where a DHIS2 read usually ends up: checked, reshaped, repeated once per
organisation unit, or left behind as a file.

A file is always a composition here. A value moves through step outputs, and storage has two
doors: `storage.write` puts a value out at a URI and `storage.read` brings one back in. No
`dhis2.*` block opens either, so an export that has to end in a file is an export step and a
write step, and a month moved between instances is four hops.

They are kept apart from [`../dhis2/`](../dhis2) for one reason: that shelf is the pack's
own conformance corpus, and every block a step there names must be one this pack
contributes. A document naming `transform.jq` is correct and simply belongs here instead.
The pack's tests still hold the `dhis2.*` half of each document below to the same catalog.

Each carries the connection it uses, so it runs standalone against the public play demo.
Nothing here writes to it.

| File | What it composes |
| --- | --- |
| [dhis2-export-validated.yaml](dhis2-export-validated.yaml) | An export gated on `validate.schema`, against the shape the instance holds -- ids and periods held to the pack's own `dhis2-uid` and `dhis2-period` formats. |
| [dhis2-export-reshaped.yaml](dhis2-export-reshaped.yaml) | An export reshaped with `transform.jq`: the envelope's defaults pushed down, values made numeric, cells grouped per data element. |
| [dhis2-export-per-org-unit.yaml](dhis2-export-per-org-unit.yaml) | One export per organisation unit with `for_each`, each its own run item, `items: continue` so one district's failure costs only that district, and the fan's outputs written out as one bundle. | A second fanned `storage.write` adopts the export's grid and writes one file per district; a manifest lists what landed.
| [dhis2-export-to-storage.yaml](dhis2-export-to-storage.yaml) | An export left behind as a file: `storage.write` takes the export's `body` and reports the URI it landed at. |
| [dhis2-import-from-storage.yaml](dhis2-import-from-storage.yaml) | A month moved through a file: export, `storage.write`, `storage.read`, import -- both of storage's doors in one document. |

`dhis2-export-validated.yaml` reads a schema the instance holds rather than one it carries,
so a local run is handed the file:

```bash
dg run --local --schema examples/schemas/dhis2-data-value-set.json \
  examples/dhis2-compose/dhis2-export-validated.yaml
```
