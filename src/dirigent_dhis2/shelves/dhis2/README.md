# DHIS2 examples: the native adapter

These pipelines use the `dhis2.*` blocks the `dirigent-dhis2` pack contributes -- the
adapter that speaks DHIS2's asynchronous jobs, import summaries and completeness
registrations as first-class steps, rather than composing them out of raw HTTP. Installing
the pack is what puts the blocks in the catalog; an instance without it refuses these at
the block preflight.

Each file here is one operation, small enough to read in a sitting and to lift into a real
pipeline unchanged. Find yours by its file name: the exports, the imports and their
strategies, one data value, the sign-off and its gate, the analytics reads and rebuilds, the
three tracker collections and the tracker import, the metadata reads and writes, and a system
report.

Two neighbours hold what this shelf deliberately does not. The generic-HTTP way of talking
to DHIS2 -- what you reach for when no adapter is installed, or for a call the adapter does
not yet cover, such as a CSV export, a period range or a stage-scoped event read -- lives in
[`../dhis2-http/`](../dhis2-http). Documents that put a `dhis2.*` block beside one of the
engine's own -- a schema gate, a jq reshape, a fan-out, or the `storage.write` and
`storage.read` steps that are the only way a value becomes a file and comes back -- live in
[`../dhis2-compose/`](../dhis2-compose).

No document carries a credential. Each names the `dhis2` connection `dhis2-play` under
`requires.connections`, and the instance holds it; create it once against the public play demo,
and `dg connection create` asks how to sign in, where the demo takes the login it publishes on
its own sign-in page:

```bash
dg connection create dhis2 dhis2-play --set base_url=https://play.dhis2.org/2.43 --set timeout=2m
dg run examples/dhis2/dhis2-system-report.yaml
```

Create the same code against your own instance, or rename it in a copy, and the documents read
yours. `https://play.dhis2.org/2.43` redirects to a versioned host (see
[`../dhis2-http/README.md`](../dhis2-http/README.md) for the redirect lore the connection url
depends on).

The demo shifts its data era from release to release, and every document that reads data
takes the period as a parameter for that reason. An empty answer is usually a period outside
the era rather than a wrong read.

Nothing here writes data to the demo: every import in this directory is a `dry_run`, and the
predictor run names no group unless it is told one.

## Data value sets

| File | The operation |
| --- | --- |
| [dhis2-export-data-values.yaml](dhis2-export-data-values.yaml) | Read one data set for one period at one organisation unit. |
| [dhis2-export-with-children.yaml](dhis2-export-with-children.yaml) | The same export widened to the org unit's descendants with `children`. |
| [dhis2-export-csv.yaml](dhis2-export-csv.yaml) | Export as CSV, XML or ADX: the whole text to storage at `uri`, its head inlined as `text`. |
| [dhis2-export-incremental.yaml](dhis2-export-incremental.yaml) | Only the values changed within a window, across two data sets and a subtree, deletions included. |
| [dhis2-import-dry-run.yaml](dhis2-import-dry-run.yaml) | Send a hand-written data value set with `dry_run` on and read the summary. |
| [dhis2-import-create.yaml](dhis2-import-create.yaml) | `import_strategy: CREATE` -- fill the gaps, revise nothing. |
| [dhis2-import-update.yaml](dhis2-import-update.yaml) | `import_strategy: UPDATE` -- revise what is there, invent nothing. |
| [dhis2-import-create-and-update.yaml](dhis2-import-create-and-update.yaml) | `import_strategy: CREATE_AND_UPDATE` -- the file is the truth. |
| [dhis2-import-delete.yaml](dhis2-import-delete.yaml) | `import_strategy: DELETE` -- remove the values a document names. |
| [dhis2-import-partial.yaml](dhis2-import-partial.yaml) | `atomic_mode: NONE` -- take the good values, report the rest as conflicts. |
| [dhis2-rehearse-import.yaml](dhis2-rehearse-import.yaml) | Export one month of a data set, then hand it straight back as a dry run. |
| [dhis2-rehearse-csv-import.yaml](dhis2-rehearse-csv-import.yaml) | The same round trip in CSV, the import reading the export's file at `data_values_uri`, by code. |
| [dhis2-data-value.yaml](dhis2-data-value.yaml) | Read one data value, then rehearse setting it with `dhis2.data_value`. |

## Completeness

| File | The operation |
| --- | --- |
| [dhis2-wait-for-complete.yaml](dhis2-wait-for-complete.yaml) | Wait until a data set is marked complete for a period and org unit. |
| [dhis2-complete-then-export.yaml](dhis2-complete-then-export.yaml) | The sign-off gate, with the export that reads the month behind it. |
| [dhis2-mark-complete.yaml](dhis2-mark-complete.yaml) | Sign a data set off for a period and org unit with `dhis2.data_set_completion`, as a dry run. |

## Analytics

| File | The operation |
| --- | --- |
| [dhis2-analytics-query.yaml](dhis2-analytics-query.yaml) | Run an aggregate analytics query for one indicator over the last twelve months. |
| [dhis2-analytics-data-elements.yaml](dhis2-analytics-data-elements.yaml) | Read two data elements broken down by the districts under one organisation unit. |
| [dhis2-analytics-pivot.yaml](dhis2-analytics-pivot.yaml) | The pivot shape: `dimension` for the axes shown, `filter` for the axis pinned. |
| [dhis2-analytics-event-query.yaml](dhis2-analytics-event-query.yaml) | `mode: event` -- a line list of events for one program. |
| [dhis2-analytics-enrollment-query.yaml](dhis2-analytics-enrollment-query.yaml) | `mode: enrollment` -- one row per enrollment, its stages folded in. |
| [dhis2-native-analytics.yaml](dhis2-native-analytics.yaml) | `dhis2.analytics_run` submits the job and streams its notifications into the log. |
| [dhis2-analytics-resource-tables.yaml](dhis2-analytics-resource-tables.yaml) | The same job with every data table skipped: the run to make after a metadata change. |
| [dhis2-rebuild-then-query.yaml](dhis2-rebuild-then-query.yaml) | Rebuild, then read -- the edge that makes the query wait for the job to finish. |
| [dhis2-analytics.yaml](dhis2-analytics.yaml) | The production-shaped nightly: sign-off gate, rebuild, export, with a nightly's deadlines and retries. |
| [dhis2-resource-tables.yaml](dhis2-resource-tables.yaml) | `dhis2.resource_tables_run`: the resource tables as their own job, followed to the end. |

## Data quality and jobs

| File | The operation |
| --- | --- |
| [dhis2-validation-run.yaml](dhis2-validation-run.yaml) | Run validation rule analysis over a facility for a year and read the violations. |
| [dhis2-predictor-run.yaml](dhis2-predictor-run.yaml) | Run the predictors of each named group over a quarter; none is named by default, so nothing is written. |
| [dhis2-task-wait.yaml](dhis2-task-wait.yaml) | Follow one DHIS2 background job by its job type and id until it settles. |

## Tracker

| File | The operation |
| --- | --- |
| [dhis2-tracker-events.yaml](dhis2-tracker-events.yaml) | A page of events for one program and org-unit subtree. |
| [dhis2-tracker-entities.yaml](dhis2-tracker-entities.yaml) | The people enrolled in a program, read with `ou_mode: DESCENDANTS`. |
| [dhis2-tracker-enrollments.yaml](dhis2-tracker-enrollments.yaml) | The open enrollments in a program, by `status` and `updated_after`. |
| [dhis2-tracker-paged.yaml](dhis2-tracker-paged.yaml) | One page of a large collection with its count, then every page of the recent changes with `all_pages`. |
| [dhis2-tracker-events-filtered.yaml](dhis2-tracker-events-filtered.yaml) | Status, change window and a data element `filter`, at once. |
| [dhis2-tracker-import-dry-run.yaml](dhis2-tracker-import-dry-run.yaml) | Validate one event against the tracker importer, followed as a job. |

## Metadata

| File | The operation |
| --- | --- |
| [dhis2-metadata-data-elements.yaml](dhis2-metadata-data-elements.yaml) | The `dataElements` collection through the version-bound accessor. |
| [dhis2-metadata-data-elements-filtered.yaml](dhis2-metadata-data-elements-filtered.yaml) | The same read narrowed by `filter` and projected by `fields`. |
| [dhis2-metadata-org-units.yaml](dhis2-metadata-org-units.yaml) | Read the org units directly beneath one unit, with their hierarchy paths. |
| [dhis2-metadata-data-set.yaml](dhis2-metadata-data-set.yaml) | Read one data set's period type, data elements, and their disaggregations. |
| [dhis2-metadata-paged.yaml](dhis2-metadata-paged.yaml) | Read one page of organisation units and how many there are in total. |
| [dhis2-metadata-create-data-element.yaml](dhis2-metadata-create-data-element.yaml) | Create one data element with `dhis2.metadata_import`, validated only. |
| [dhis2-metadata-round-trip.yaml](dhis2-metadata-round-trip.yaml) | Export a few data elements and validate them straight back as an update. |
| [dhis2-sql-view.yaml](dhis2-sql-view.yaml) | Run the demo's data-element-by-value-type SQL view with a variable, every row keyed by column. |
| [dhis2-data-store.yaml](dhis2-data-store.yaml) | List a data store namespace's keys, then read the first one. |
| [dhis2-system-report.yaml](dhis2-system-report.yaml) | System info, a two-collection `dhis2.metadata_export` and an org unit count, rendered as the run's `report:`. |

The instance's own version and system information is not a metadata collection: it is
`dhis2.system_info`, which `dhis2-system-report.yaml` reads. The same read through the generic
`http.request` is [`../dhis2-http/dhis2-system-info.yaml`](../dhis2-http/dhis2-system-info.yaml).
