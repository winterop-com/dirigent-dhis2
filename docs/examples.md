# Examples

The pack ships one document per operation, small enough to read in a sitting and to lift into a
real pipeline unchanged. They live in [`src/dirigent_dhis2/shelves/`](https://github.com/winterop-com/dirigent-dhis2/tree/main/src/dirigent_dhis2/shelves),
on six shelves:

| Shelf | What is on it |
| --- | --- |
| [`dhis2/`](#the-native-adapter) | The native adapter: exports and their import strategies, the sign-off gate, the analytics reads and rebuilds, the three tracker collections, the metadata reads. |
| [`dhis2-compose/`](#composed-with-the-engines-own-blocks) | A `dhis2.*` block beside one of the engine's own: a schema gate, a jq reshape, a fan-out over org units, a write to storage and the read back. |
| [`dhis2-http/`](#the-generic-http-way) | The generic-HTTP way, for what no adapter covers: a CSV export, a period range, a completion registration, a stage-scoped event read. |
| [`validate/`](#a-read-held-to-a-shape) | A metadata read held to a shape: a `fields=` projection gated on `validate.schema`, with the schema carried and named. |
| [`schemas/`](#schemas) | The JSON Schemas that pin the reads the DHIS2 series makes, applied on their own. |
| [`starters/`](#starters) | The `starter`-tagged flows: the same work naming a `dhis2` connection rather than carrying one. |

## Reaching them once the pack is installed

The shelves ship inside the distribution and the pack contributes them through the
`examples()` hook, so an instance with the pack installed has the catalogue without a
checkout:

```bash
dg examples list --plugin dhis2
dg examples show dhis2-export-and-import
```

## Running one

Every document carries the connection it uses, in a `connections:` block beside its steps, so
it runs standalone with nothing to set up first:

```bash
dg run --local examples/dhis2/dhis2-export-data-values.yaml
```

`--connections FILE` replaces a carried connection by code, so a document points at your own
DHIS2 without being edited. The connections these carry name the public play demo, resolved to
a versioned host; when DHIS2 moves the stable demo, resolve the alias again and update
`base_url`.

A server refuses to apply a document that embeds a connection, so applying one to an instance
means creating a [`dhis2` connection](connection.md) first and letting the document name it:

```bash
dg connection create dhis2 play --set base_url=... --set basic_username=... --set basic_password=...
dg apply examples/dhis2/dhis2-export-data-values.yaml
dg run dhis2-export-data-values -p period=2026Q1 --watch
```

`dg run` takes the pipeline's `code`, which is the second column below. `--watch` streams step
transitions and block output as the run goes.

Two things to know before a run comes back empty. The demo shifts its data era from release to
release, and every document that reads data takes the period as a parameter for that reason: an
empty answer is usually a period outside the era rather than a wrong read. And nothing in these
examples writes to the demo -- every import is a `dry_run`, and every write in the `dhis2-http`
shelf is posted somewhere harmless.

## The native adapter

`examples/dhis2/`. These use the `dhis2.*` blocks this pack contributes. An instance without
the pack refuses them at the block preflight.

### Data value sets

| File | Code | The operation |
| --- | --- | --- |
| `dhis2-export-data-values.yaml` | `dhis2-export-data-values` | Export one data set, for one period, at one organisation unit. |
| `dhis2-export-with-children.yaml` | `dhis2-export-with-children` | The same export widened to the org unit's descendants with `children`. |
| `dhis2-import-dry-run.yaml` | `dhis2-import-dry-run` | Send a hand-written data value set with `dry_run` on and read the summary. |
| `dhis2-import-create.yaml` | `dhis2-import-create` | `import_strategy: CREATE` -- fill the gaps, revise nothing. |
| `dhis2-import-update.yaml` | `dhis2-import-update` | `import_strategy: UPDATE` -- revise what is there, invent nothing. |
| `dhis2-import-create-and-update.yaml` | `dhis2-import-create-and-update` | `import_strategy: CREATE_AND_UPDATE` -- the file is the truth. |
| `dhis2-import-delete.yaml` | `dhis2-import-delete` | `import_strategy: DELETE` -- remove the values a document names. |
| `dhis2-import-partial.yaml` | `dhis2-import-partial` | `atomic_mode: NONE` -- take the good values, report the rest as conflicts. |
| `dhis2-rehearse-import.yaml` | `dhis2-rehearse-import` | The round trip: export a month, then hand it straight back as a dry run. |

### Completeness

| File | Code | The operation |
| --- | --- | --- |
| `dhis2-wait-for-complete.yaml` | `dhis2-wait-for-complete` | Hold the run until a data set is signed off for a period and org unit. |
| `dhis2-complete-then-export.yaml` | `dhis2-complete-then-export` | The sign-off gate, with the export that reads the month behind it. |

### Analytics

| File | Code | The operation |
| --- | --- | --- |
| `dhis2-analytics-query.yaml` | `dhis2-analytics-query` | One indicator over the last twelve months, as an aggregate query. |
| `dhis2-analytics-data-elements.yaml` | `dhis2-analytics-data-elements` | Several data elements broken down by the districts under an org unit. |
| `dhis2-analytics-pivot.yaml` | `dhis2-analytics-pivot` | The pivot shape: `dimension` for the axes shown, `filter` for the axis pinned. |
| `dhis2-analytics-event-query.yaml` | `dhis2-analytics-event-query` | `mode: event` -- a line list of events for one program. |
| `dhis2-analytics-enrollment-query.yaml` | `dhis2-analytics-enrollment-query` | `mode: enrollment` -- one row per enrollment, its stages folded in. |
| `dhis2-native-analytics.yaml` | `dhis2-native-analytics` | `dhis2.analytics_run` submits the job and streams its notifications into the log. |
| `dhis2-analytics-resource-tables.yaml` | `dhis2-analytics-resource-tables` | The same job with every data table skipped: the run to make after a metadata change. |
| `dhis2-rebuild-then-query.yaml` | `dhis2-rebuild-then-query` | Rebuild, then read -- the edge that makes the query wait for the job to finish. |
| `dhis2-analytics.yaml` | `dhis2-analytics` | The production-shaped nightly: sign-off gate, rebuild, export, with a nightly's deadlines and retries. |

### Tracker

| File | Code | The operation |
| --- | --- | --- |
| `dhis2-tracker-events.yaml` | `dhis2-tracker-events` | A page of events for one program and org-unit subtree. |
| `dhis2-tracker-entities.yaml` | `dhis2-tracker-entities` | The people enrolled in a program, read with `ou_mode: DESCENDANTS`. |
| `dhis2-tracker-enrollments.yaml` | `dhis2-tracker-enrollments` | The open enrollments in a program, by `status` and `updated_after`. |
| `dhis2-tracker-paged.yaml` | `dhis2-tracker-paged` | One page of a large collection, with `page` and `page_size` as parameters. |
| `dhis2-tracker-events-filtered.yaml` | `dhis2-tracker-events-filtered` | Status, change window and a data element `filter`, at once. |

### Metadata

| File | Code | The operation |
| --- | --- | --- |
| `dhis2-metadata-data-elements.yaml` | `dhis2-metadata-data-elements` | The `dataElements` collection through the version-bound accessor. |
| `dhis2-metadata-data-elements-filtered.yaml` | `dhis2-metadata-data-elements-filtered` | The same read narrowed by `filter` and projected by `fields`. |
| `dhis2-metadata-org-units.yaml` | `dhis2-metadata-org-units` | The organisation units directly under one parent, with their paths. |
| `dhis2-metadata-data-set.yaml` | `dhis2-metadata-data-set` | One data set's period type, data elements and disaggregations. |
| `dhis2-metadata-paged.yaml` | `dhis2-metadata-paged` | One page of a collection, and the pager that says how many there are. |

## Composed with the engine's own blocks

`examples/dhis2-compose/`. A `dhis2.*` step is rarely the whole pipeline: a DHIS2 read usually
ends up checked, reshaped, repeated once per organisation unit, or left behind as a file.

A file is always a composition. A value moves through step outputs, and storage has two doors:
`storage.write` puts a value out at a URI and `storage.read` brings one back in. No `dhis2.*`
block opens either, so an export that ends in a file is two steps and a month moved between
instances is four.

| File | Code | What it composes |
| --- | --- | --- |
| `dhis2-export-validated.yaml` | `dhis2-export-validated` | An export gated on `validate.schema`, ids and periods held to `dhis2-uid` and `dhis2-period`. |
| `dhis2-export-reshaped.yaml` | `dhis2-export-reshaped` | An export reshaped with `transform.jq`: the envelope's defaults pushed down, values made numeric, cells grouped per data element. |
| `dhis2-export-per-org-unit.yaml` | `dhis2-export-per-org-unit` | One export per organisation unit with `for_each`, `items: continue` so one district's failure costs only that district, and the fan's outputs written out as one bundle. |
| `dhis2-export-to-storage.yaml` | `dhis2-export-to-storage` | An export left behind as a file: `storage.write` takes the export's `body` and reports the URI it landed at. |
| `dhis2-import-from-storage.yaml` | `dhis2-import-from-storage` | A month moved through a file: export, `storage.write`, `storage.read`, import -- both of storage's doors in one document. |

`dhis2-export-validated.yaml` gates on a schema the instance holds rather than one it carries,
so a local run is handed the file:

```bash
dg run --local --schema examples/schemas/dhis2-data-value-set.json \
  examples/dhis2-compose/dhis2-export-validated.yaml
```

## The generic-HTTP way

`examples/dhis2-http/`. These talk to DHIS2 with dirigent's ordinary `http.request` and
`http.ready` -- no adapter, nothing to install. It is the pattern for reaching a system that has
no adapter, or a DHIS2 call this pack does not yet cover.

| File | Code | What it demonstrates |
| --- | --- | --- |
| `dhis2-system-info.yaml` | `dhis2-system-info` | Authentication and a minimal API call. |
| `dhis2-org-unit-levels.yaml` | `dhis2-org-unit-levels` | The configured hierarchy levels. |
| `dhis2-org-units.yaml` | `dhis2-org-units` | A compact snapshot of every organisation unit, written to storage as a file. |
| `dhis2-org-unit-detail.yaml` | `dhis2-org-unit-detail` | One parameterized organisation unit and its children. |
| `dhis2-forward-org-units.yaml` | `dhis2-forward-org-units` | Select, reshape with `transform.jq`, and send an organisation-unit batch to Postman Echo. |
| `dhis2-run-analytics.yaml` | `dhis2-run-analytics` | Start an analytics-table update and poll the asynchronous task with `http.ready` -- what `dhis2.analytics_run` does for you. |
| `dhis2-sync-org-units.yaml` | `dhis2-sync-org-units` | An organisation-unit sync: count before fetching, bound the read, ask for fields, order by `path`. |
| `dhis2-export-data-elements.yaml` | `dhis2-export-data-elements` | A metadata export with `fields=:owner`, and the import vocabulary: `importStrategy`, `atomicMode`, `importMode=VALIDATE`. |
| `dhis2-fhir-to-data-values.yaml` | `dhis2-fhir-to-data-values` | A FHIR `QuestionnaireResponse` translated into a `/api/dataValueSets` import, link id by link id. |
| `dhis2-export-data-values-csv.yaml` | `dhis2-export-data-values-csv` | A data value set as CSV rather than JSON -- the extension is the content negotiation -- written out with `storage.write`. |
| `dhis2-export-data-values-range.yaml` | `dhis2-export-data-values-range` | Every period inside a `startDate`/`endDate` window in one call, instead of a period at a time. |
| `dhis2-data-values-validated.yaml` | `dhis2-data-values-validated` | A data value set gated on a carried schema, every id held to `dhis2-uid` and every period to `dhis2-period`. |
| `dhis2-mark-data-set-complete.yaml` | `dhis2-mark-data-set-complete` | Reading a completion registration, and the POST that signs a period off. |
| `dhis2-mark-data-set-incomplete.yaml` | `dhis2-mark-data-set-incomplete` | Both ways of reopening a signed-off period: `completed: false`, and the outright DELETE. |
| `dhis2-events-by-stage.yaml` | `dhis2-events-by-stage` | Events of a single program stage in an occurrence window, and the `orgUnitMode`/`ouMode` split. |

`dhis2-export-data-elements.yaml` marks the sharpest trap in the DHIS2 API: a dry run is
`importMode=VALIDATE` on `/api/metadata` and `dryRun=true` on `/api/dataValueSets`, and reaching
for the wrong spelling does not fail -- it imports.

## A read held to a shape

`examples/validate/`. Each asks DHIS2 for a `fields=` projection with `http.request` and gates
the answer with `validate.schema` before anything downstream reads it. A mismatch is
`rejected`, so the same value against the same schema is never retried.

| File | Code | What it demonstrates |
| --- | --- | --- |
| `org-units-shape.yaml` | `org-units-shape` | `fields=id,displayName,level` on organisation units, validated as an array of typed records against the `dhis2-org-units` instance schema. |
| `data-elements-carried.yaml` | `data-elements-carried` | `fields=id,name,valueType,domainType` on data elements, with the shape carried in the document's own `schemas:` section. |
| `data-elements-named.yaml` | `data-elements-named` | The same check against the `dhis2-data-elements` schema the instance holds. |
| `numbers-only.yaml` | `numbers-only` | A `filter` narrows the read to NUMBER-valued elements; the schema sharpens, proving none of another type slipped through. |
| `system-info-shape.yaml` | `system-info-shape` | `/api/system/info` validated as a top-level object -- a schema needs no list to gate on. |

A carried schema is for a standalone or `--local` run; a server refuses a document that carries
one. A named schema is declared under `requires.schemas`, so an instance that does not hold it
refuses the document, and a `--local` run is handed the file with `--schema FILE`.

## Schemas

`examples/schemas/`. Each file is a plain JSON Schema (Draft 2020-12): the shape a read is
expected to return, written down once so a pipeline can be refused the moment a payload moves
out from under it. A schema is locally authored, never fetched from the source, which is why
these are applied on their own rather than from inside a pipeline document:

```bash
dg schema create examples/schemas/dhis2-org-units.json
```

A schema carries its own identity in its keywords: `$id` becomes the `code` it is addressed by,
`title` its name, and `description` its body.

| File | Code | The shape it pins |
| --- | --- | --- |
| `dhis2-org-units.json` | `dhis2-org-units` | An object with an `organisationUnits` array of UID/name/level items. |
| `dhis2-data-elements.json` | `dhis2-data-elements` | A `dataElements` array whose `valueType` and `domainType` are held to the DHIS2 enums. |
| `dhis2-system-info.json` | `dhis2-system-info` | A top-level object, not a list: an instance `version` and a `serverDate`. |
| `dhis2-number-data-elements.json` | `dhis2-number-data-elements` | A `dataElements` array whose every `valueType` is `NUMBER`. |
| `dhis2-data-elements-v42.json` | `dhis2-data-elements-v42` | The v42-pinned `dataElements` shape: the 2.42 `valueType` enum and closed rows, so a 2.43 bump is caught. |
| `dhis2-data-value-set.json` | `dhis2-data-value-set` | The `/api/dataValueSets` envelope, every id held to `dhis2-uid` and every period to `dhis2-period`. |

## Starters

`src/dirigent_dhis2/shelves/starters/`. Every other shelf carries the connection it uses so
its documents run standalone; a server refuses a carried connection, so none of them apply to
an instance unedited. This shelf is the other half: the same flows written the way an instance
accepts them, naming a `dhis2` connection and declaring it under `requires.connections`, with
nothing carried. Each is tagged `starter`, which is what `dg pipeline new` copies from:

```bash
dg connection create dhis2 --kind dhis2 --set base_url=... --set basic_username=... --set basic_password=...
dg pipeline new dhis2-export-and-import
```

The copy is verbatim apart from the `code:` line and the dropped `starter` tag, so the
comments come with it, and each document ends with a TO MAKE IT YOURS paragraph naming the
edits a real instance needs -- the uids are the play demo's.

| File | Code | What it starts you with |
| --- | --- | --- |
| `dhis2-export-and-import.yaml` | `dhis2-export-and-import` | The round trip: read a data value set and hand it to an import, rehearsed with `dry_run`. |
| `dhis2-export-through-storage.yaml` | `dhis2-export-through-storage` | The same move with the file kept: export, write, read back, import. |
| `dhis2-export-gated-on-a-schema.yaml` | `dhis2-export-gated-on-a-schema` | An export held to a named schema, so a changed payload stops at the step it arrived in. |
| `dhis2-export-reshaped-to-totals.yaml` | `dhis2-export-reshaped-to-totals` | An export reshaped with `transform.jq` into the shape the next system reads. |
| `dhis2-rebuild-then-report.yaml` | `dhis2-rebuild-then-report` | The analytics ordering: rebuild the tables, then read an indicator out of them. |
| `dhis2-signed-off-then-export.yaml` | `dhis2-signed-off-then-export` | A sensor gate: hold until a month is marked complete, then read it. |
| `dhis2-metadata-snapshot-to-storage.yaml` | `dhis2-metadata-snapshot-to-storage` | A metadata collection read with a fields projection and written to storage. |
