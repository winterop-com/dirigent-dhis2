# DHIS2 examples: a metadata read held to a shape

A metadata read is a contract with a system you do not control. These documents make the
contract explicit: each asks DHIS2 for a `fields=` projection with `http.request`, and gates
the answer with `validate.schema` before anything downstream reads it. A payload that moved
is refused where it enters, naming the path that is wrong, rather than surfacing as a
confusing error further down. A mismatch is `rejected`, so the same value against the same
schema is never retried.

They are built from the engine's own `http.request` and `validate.schema` blocks -- no
`dhis2.*` step, nothing to install beyond dirigent itself -- so they are the shape-checking
counterpart to [`../dhis2-http/`](../dhis2-http). The documents that put a `dhis2.*` block
beside an engine block live in [`../dhis2-compose/`](../dhis2-compose).

A gate never writes a schema inline: it names one by `code`, and the code resolves one of two
ways.

- **Carried in the document.** The shape sits in the document's own top-level `schemas:`
  section, keyed by its code, exactly the way a document carries its own `connections:`. A
  server refuses a document that carries a schema, so a carried schema is for a standalone or
  `--local` run.
- **A named instance schema.** The code names a schema the instance holds, applied on its own
  from [`../schemas/`](../schemas) with `dg schema create`. The document declares it under
  `requires.schemas`, so an instance that does not hold it refuses the document. A `--local`
  run holds no instance schema until one is handed to it with `--schema FILE`; each such
  document's top-of-file comment shows the invocation.

`data-elements-carried` and `data-elements-named` are the same check supplied both ways: only
the schema's location differs.

| File | Technique | What it demonstrates |
| --- | --- | --- |
| [org-units-shape.yaml](org-units-shape.yaml) | references the `dhis2-org-units` instance schema | `fields=id,displayName,level` on organisation units, validated as an array of typed records. |
| [data-elements-carried.yaml](data-elements-carried.yaml) | schema carried in the document | `fields=id,name,valueType,domainType` on data elements, with the shape carried in the document. |
| [data-elements-named.yaml](data-elements-named.yaml) | references the `dhis2-data-elements` instance schema | The same check, against the schema the instance holds rather than a carried one. |
| [numbers-only.yaml](numbers-only.yaml) | references the `dhis2-number-data-elements` instance schema | A `filter` narrows the read to NUMBER-valued elements; the schema sharpens, proving none of another type slipped through. |
| [system-info-shape.yaml](system-info-shape.yaml) | references the `dhis2-system-info` instance schema | `/api/system/info` validated as a top-level object -- a schema needs no list to gate on. |
