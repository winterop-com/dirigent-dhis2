# DHIS2 examples: the native adapter

These pipelines use the `dhis2.*` blocks the `dirigent-dhis2` pack contributes -- the
adapter that speaks DHIS2's asynchronous jobs, import summaries and completeness
registrations as first-class steps, rather than composing them out of raw HTTP. Installing
the pack is what puts the blocks in the catalog; an instance without it refuses these at
the block preflight.

Each file here is one operation, small enough to read in a sitting and to lift into a real
pipeline unchanged. Find yours by its file name: the exports, the imports and their
strategies, the sign-off gate, the analytics reads and rebuilds, the three tracker
collections, and the metadata reads.

Two neighbours hold what this shelf deliberately does not. The generic-HTTP way of talking
to DHIS2 -- what you reach for when no adapter is installed, or for a call the adapter does
not yet cover, such as a CSV export, a period range, a completion registration or a
stage-scoped event read -- lives in [`../dhis2-http/`](../dhis2-http). Documents that put a
`dhis2.*` block beside one of the engine's own -- a schema gate, a jq reshape, a fan-out, or
the `storage.write` and `storage.read` steps that are the only way a value becomes a file and
comes back -- live in [`../dhis2-compose/`](../dhis2-compose).

Each document carries the connection it uses so it runs standalone; an instance you own
names its connections instead, and a server refuses a document that embeds one, so applying
these to an instance means creating a `dhis2` connection first and letting the document name
it. They run against the public play demo, resolved to a versioned host (see
[`../dhis2-http/README.md`](../dhis2-http/README.md) for the redirect lore the connection
url depends on).

The demo shifts its data era from release to release, and every document that reads data
takes the period as a parameter for that reason. An empty answer is usually a period outside
the era rather than a wrong read.

Nothing here writes to the demo: every import in this directory is a `dry_run`.

## Data value sets

| File | The operation |
| --- | --- |
| [dhis2-export-data-values.yaml](dhis2-export-data-values.yaml) | Export one data set, for one period, at one organisation unit. |
| [dhis2-export-with-children.yaml](dhis2-export-with-children.yaml) | The same export widened to the org unit's descendants with `children`. |
| [dhis2-import-dry-run.yaml](dhis2-import-dry-run.yaml) | Send a hand-written data value set with `dry_run` on and read the summary. |
| [dhis2-import-create.yaml](dhis2-import-create.yaml) | `import_strategy: CREATE` -- fill the gaps, revise nothing. |
| [dhis2-import-update.yaml](dhis2-import-update.yaml) | `import_strategy: UPDATE` -- revise what is there, invent nothing. |
| [dhis2-import-create-and-update.yaml](dhis2-import-create-and-update.yaml) | `import_strategy: CREATE_AND_UPDATE` -- the file is the truth. |
| [dhis2-import-delete.yaml](dhis2-import-delete.yaml) | `import_strategy: DELETE` -- remove the values a document names. |
| [dhis2-import-partial.yaml](dhis2-import-partial.yaml) | `atomic_mode: NONE` -- take the good values, report the rest as conflicts. |
| [dhis2-rehearse-import.yaml](dhis2-rehearse-import.yaml) | The round trip: export a month, then hand it straight back as a dry run. |

## Completeness

| File | The operation |
| --- | --- |
| [dhis2-wait-for-complete.yaml](dhis2-wait-for-complete.yaml) | Hold the run until a data set is signed off for a period and org unit. |
| [dhis2-complete-then-export.yaml](dhis2-complete-then-export.yaml) | The sign-off gate, with the export that reads the month behind it. |

## Analytics

| File | The operation |
| --- | --- |
| [dhis2-analytics-query.yaml](dhis2-analytics-query.yaml) | One indicator over the last twelve months, as an aggregate query. |
| [dhis2-analytics-data-elements.yaml](dhis2-analytics-data-elements.yaml) | Several data elements broken down by the districts under an org unit. |
| [dhis2-analytics-pivot.yaml](dhis2-analytics-pivot.yaml) | The pivot shape: `dimension` for the axes shown, `filter` for the axis pinned. |
| [dhis2-analytics-event-query.yaml](dhis2-analytics-event-query.yaml) | `mode: event` -- a line list of events for one program. |
| [dhis2-analytics-enrollment-query.yaml](dhis2-analytics-enrollment-query.yaml) | `mode: enrollment` -- one row per enrollment, its stages folded in. |
| [dhis2-native-analytics.yaml](dhis2-native-analytics.yaml) | `dhis2.analytics_run` submits the job and streams its notifications into the log. |
| [dhis2-analytics-resource-tables.yaml](dhis2-analytics-resource-tables.yaml) | The same job with every data table skipped: the run to make after a metadata change. |
| [dhis2-rebuild-then-query.yaml](dhis2-rebuild-then-query.yaml) | Rebuild, then read -- the edge that makes the query wait for the job to finish. |
| [dhis2-analytics.yaml](dhis2-analytics.yaml) | The production-shaped nightly: sign-off gate, rebuild, export, with a nightly's deadlines and retries. |

## Tracker

| File | The operation |
| --- | --- |
| [dhis2-tracker-events.yaml](dhis2-tracker-events.yaml) | A page of events for one program and org-unit subtree. |
| [dhis2-tracker-entities.yaml](dhis2-tracker-entities.yaml) | The people enrolled in a program, read with `ou_mode: DESCENDANTS`. |
| [dhis2-tracker-enrollments.yaml](dhis2-tracker-enrollments.yaml) | The open enrollments in a program, by `status` and `updated_after`. |
| [dhis2-tracker-paged.yaml](dhis2-tracker-paged.yaml) | One page of a large collection, with `page` and `page_size` as parameters. |
| [dhis2-tracker-events-filtered.yaml](dhis2-tracker-events-filtered.yaml) | Status, change window and a data element `filter`, at once. |

## Metadata

| File | The operation |
| --- | --- |
| [dhis2-metadata-data-elements.yaml](dhis2-metadata-data-elements.yaml) | The `dataElements` collection through the version-bound accessor. |
| [dhis2-metadata-data-elements-filtered.yaml](dhis2-metadata-data-elements-filtered.yaml) | The same read narrowed by `filter` and projected by `fields`. |
| [dhis2-metadata-org-units.yaml](dhis2-metadata-org-units.yaml) | The organisation units directly under one parent, with their paths. |
| [dhis2-metadata-data-set.yaml](dhis2-metadata-data-set.yaml) | One data set's period type, data elements and disaggregations. |
| [dhis2-metadata-paged.yaml](dhis2-metadata-paged.yaml) | One page of a collection, and the pager that says how many there are. |

The instance's own version and system information is not a metadata collection, so it is read
directly: [`../dhis2-http/dhis2-system-info.yaml`](../dhis2-http/dhis2-system-info.yaml).
