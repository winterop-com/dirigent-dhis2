# Releases

The pack follows dirigent's version. A release of dirigent is a release here: the pack relocks
its dirigent packages at the tagged commit, moves to the same number, and is tagged `vX.Y.Z`
with a GitHub release of its own. So `dirigent-dhis2` 0.13.0 is the pack built against dirigent
0.13.0, and the two numbers are never read as independent.

Every release, with its notes, is on
[the pack's releases page](https://github.com/winterop-com/dirigent-dhis2/releases). What
changed in the engine under it is in
[dirigent's release notes](https://winterop-com.github.io/dirigent/releases/).

An instance installs a matching pair: the pack's version and the dirigent it was released
with. A pack built against an older dirigent is not supported, because the plugin contract
changes directly before 1.0 rather than through compatibility shims.

## Next release

### Fixed

- `dhis2-period` takes every DHIS2 period type: bi-weekly, the weekly variants starting on
  another day, bi-monthly, six-monthly (and from April or November), quarterly from November,
  and the financial years. It took yearly, monthly, daily, quarterly and weekly alone.

## 0.35.0

The imports answer the same keys, and the metadata export counts its rows as totals.

### This breaks

| Block | Was | Is |
| --- | --- | --- |
| `dhis2.metadata_export` | `output.counts.<resource>` | `output.totals.<resource>`; `counts` is an import's alone |

### New

- `dhis2.data_value_set_import` answers `dry_run` and `objects` beside `status`, `sent`, `counts`
  and `conflicts`, the keys `dhis2.metadata_import` and `dhis2.tracker_import` answer. A data
  value summary names no value it took, so its `objects` is always empty.

## 0.34.0

The read side's gaps are closed, and the read and import blocks answer in one shape per kind of
work, [described on the block reference](blocks.md#how-an-output-is-shaped).

### This breaks

A document that references these outputs needs its references changed. There are no aliases
for the old fields.

| Block | Was | Is |
| --- | --- | --- |
| `dhis2.metadata` | `output.body.<resource>`, `output.body.pager` | `output.rows`, `output.pager` (`page`, `page_size`, `total`, `page_count`, `more`), null when not paged |
| `dhis2.tracker` | `output.body.instances`, the page fields in `output.body` | `output.rows`, `output.pager` |
| `dhis2.analytics_query` | `output.body.rows`, each row a list in header order | `output.rows`, each row an object keyed by header name; the grid as DHIS2 sent it stays under `output.body` |
| `dhis2.data_value_set_import` | `output.imported`, `output.updated`, `output.ignored`, `output.deleted` | `output.counts.imported`, `.updated`, `.ignored`, `.deleted`, beside the new `output.sent` |

The refusals of a job a block follows are coded for any job rather than for analytics alone:
`dhis2.analytics.no_task_reference`, `dhis2.analytics.task_disappeared` and
`dhis2.analytics.no_result` are `dhis2.task.no_reference`, `dhis2.task.disappeared` and
`dhis2.task.no_result`.

The pack's shelves carry no credential. Every document names its connection under
`requires.connections`: `dhis2-play`, a `dhis2` connection, or `dhis2-play-http`, an `http`
one, where they carried `dhis2-demo` before, so create them once with
`dg connection create` and run the documents on the instance.

Three refusals are new, so a step that passed before can fail now:

- An export, a tracker read or an event or enrollment analytics query scoped to a uid the
  instance does not know fails with `dhis2.unknown_uids` instead of answering empty.
  `require_known: false` restores the old behaviour.
- `dhis2.data_value_set_import` refuses `data_values` that is not an object holding a
  `dataValues` list, with `dhis2.import.no_data_values`, before anything is sent. The usual
  cause is `${steps.export.output}` where `${steps.export.output.body}` was meant.
- `dhis2.data_value_set_export` refuses a config without a data, an org unit and a period
  selector at validation; `data_set`, `period` and `org_unit` are no longer each required,
  since a list, a group, a date range or a last-updated bound may stand in for them.

### New

- `dhis2.data_value_set_export` takes several data sets, data elements, periods and org units,
  data element and org unit groups, `start_date` with `end_date`, `last_updated` and
  `last_updated_duration` for an incremental sync, `include_deleted`, and the four id schemes.
- `dhis2.tracker` says in `pager.more` whether rows match past the page read, counts them with
  `total: true`, and reads every page with `all_pages: true`, bounded by `max_rows`,
  `max_pages` and `max_total` and failing with `dhis2.tracker.cap_reached` rather than
  answering part.
- `dhis2.data_value_set_import` answers `sent`, the values the document held, and fails a
  summary that took none with `require_values: true`.
- `dhis2.data_value_set_export` and `dhis2.data_value_set_import` take `format`: `json`, `csv`,
  `xml` or `adx`. An export in text is written to storage at `uri` with its head inlined as
  `text`; an import reads text inline or a stored document at `data_values_uri`, and takes the
  four id schemes. ADX is exported by 2.41 and 2.42 only, and imported by every version.
- New blocks: `dhis2.data_store`, `dhis2.sql_view`, `dhis2.validation_run`,
  `dhis2.predictor_run`, `dhis2.resource_tables_run` and `dhis2.task_wait`, each with an example
  on the `dhis2` shelf.
