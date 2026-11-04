# Block reference

Every block this pack contributes, with the config it takes and the output it produces. The
tables are the two JSON Schemas each block publishes into the catalog -- the same ones
`GET /blocks` serves, the same ones the UI builds its step form from.

What a block is, and the contract behind these tables, is
[dirigent's own](https://winterop-com.github.io/dirigent/blocks/). The short version:

- An **operator** does work. It either finishes and returns its output, or hands back a handle
  for the engine to probe, which is how `dhis2.analytics_run` waits out a table rebuild without
  holding a worker for the length of it.
- A **sensor** waits for the world. Each poke is one short, read-only observation, and "not
  yet" is the expected answer rather than a failure. `poll`, `deadline` and `on_timeout` are
  step-level engine semantics, uniform across every sensor and never in a block's own config.

Every block here declares the `dhis2` group, and every one takes a `connection` naming a
[`dhis2` connection](connection.md) by its code.

**Idempotent** says whether re-running the block after an unclear failure is safe. The engine
spends the step's retry budget either way, so this is what to read before writing
`max_attempts` above 1. No block in this pack runs code on the worker, so none has to be
allowlisted.

## How an output is shaped

The blocks answer in one shape per kind of work, so a reference reads the same field whichever
sibling produced it:

- **A read of one collection** answers its rows under `rows`, a list of objects, and a `pager`
  when the read is paged: `page`, `page_size`, `total` and `page_count` when the instance
  counted them, and `more`, which says whether rows match past the ones read. That is
  `dhis2.metadata`, `dhis2.tracker`, `dhis2.analytics_query` and `dhis2.sql_view`, and
  `dhis2.data_store` answers a namespace's keys the same way.
- **A read of several collections** answers `collections`, each one's rows under its own name,
  and `totals`, each one's row count under its name, the way a paged read's `pager.total` counts
  its rows. That is `dhis2.metadata_export`, and its `collections` is a metadata bundle as it
  stands, which `dhis2.metadata_import` takes whole.
- **`body`** carries a DHIS2 document as the instance wrote it, and only where the document is
  itself the thing to hand on: the data value set `dhis2.data_value_set_export` reads, which an
  import takes whole, and the analytics grid beside its `rows`, for its `headers` and
  `metaData`.
- **Text** a block does not parse, a data value set exported as CSV, XML or ADX, is written
  whole to the run's storage at `uri`, and its head is inlined as `text`, cut at the instance's
  inline capture size, with `truncated` and `content_bytes` saying how much there is.
- **An import** answers its summary's `status`, whether it was a `dry_run`, how many objects it
  `sent`, `counts` holding `imported`, `updated`, `ignored` and `deleted`, the `objects` the
  summary names, and its `conflicts`. That is `dhis2.data_value_set_import`,
  `dhis2.metadata_import` and `dhis2.tracker_import`; a data value summary names no value it
  took, so the data value import's `objects` is always empty.
- **A job** the block follows, the analytics and resource tables runs and `dhis2.task_wait`,
  answers its `task_id`, `completed_at` and the last few `messages` of its notification feed.
- **Every read** answers `duration_ms`.

A read that names uids to scope itself to -- a data set, data element, org unit or program --
asks the instance whether each exists first, in one metadata lookup, and fails `rejected` with
`dhis2.unknown_uids` naming the ones it does not know, rather than answering an empty read for a
typo. `require_known: false` skips the lookup, for an account that may read the data but not
the metadata describing it.

| Block | Kind | Group | Summary |
| --- | --- | --- | --- |
| [`dhis2.analytics_query`](#dhis2analytics_query) | operator | dhis2 | Run a DHIS2 analytics query. |
| [`dhis2.analytics_run`](#dhis2analytics_run) | operator | dhis2 | Run the DHIS2 analytics tables job. |
| [`dhis2.data_set_completion`](#dhis2data_set_completion) | operator | dhis2 | Mark a DHIS2 data set complete, or reopen it, for a period and org unit. |
| [`dhis2.data_store`](#dhis2data_store) | operator | dhis2 | Get, set or delete a DHIS2 data store key, or list a namespace's keys. |
| [`dhis2.data_value`](#dhis2data_value) | operator | dhis2 | Get, set or delete one DHIS2 data value by data element, period and org unit. |
| [`dhis2.data_value_set_export`](#dhis2data_value_set_export) | operator | dhis2 | Export a DHIS2 data value set as JSON, CSV, XML or ADX. |
| [`dhis2.data_value_set_import`](#dhis2data_value_set_import) | operator | dhis2 | Import a data value set into DHIS2, as JSON, CSV, XML or ADX. |
| [`dhis2.message`](#dhis2message) | operator | dhis2 | Send a DHIS2 message to users, user groups or org units. |
| [`dhis2.metadata`](#dhis2metadata) | operator | dhis2 | Read one DHIS2 metadata collection, whole or one page of it. |
| [`dhis2.metadata_export`](#dhis2metadata_export) | operator | dhis2 | Read several DHIS2 metadata collections, every row of each, in one request. |
| [`dhis2.metadata_import`](#dhis2metadata_import) | operator | dhis2 | Create, update or delete DHIS2 metadata from a bundle, one object or many. |
| [`dhis2.predictor_run`](#dhis2predictor_run) | operator | dhis2 | Run DHIS2 predictors over a date range. |
| [`dhis2.resource_tables_run`](#dhis2resource_tables_run) | operator | dhis2 | Rebuild the DHIS2 resource tables, without the analytics tables. |
| [`dhis2.sql_view`](#dhis2sql_view) | operator | dhis2 | Run a DHIS2 SQL view by uid and read its rows. |
| [`dhis2.system_info`](#dhis2system_info) | operator | dhis2 | Read a DHIS2 instance's version, build, server clock and analytics state. |
| [`dhis2.task_wait`](#dhis2task_wait) | operator | dhis2 | Wait on a DHIS2 background job by its job type and id. |
| [`dhis2.tracker`](#dhis2tracker) | operator | dhis2 | Read DHIS2 tracker objects. |
| [`dhis2.tracker_import`](#dhis2tracker_import) | operator | dhis2 | Create, update or delete DHIS2 tracked entities, enrollments, events and relationships. |
| [`dhis2.validation_run`](#dhis2validation_run) | operator | dhis2 | Run DHIS2 validation rule analysis and answer the violations. |
| [`dhis2.data_set_complete`](#dhis2data_set_complete) | sensor | dhis2 | Wait for a DHIS2 data set to be marked complete. |

## Operators

### `dhis2.analytics_query`

Run a DHIS2 analytics query.

Idempotent.

Runs one query and hands the grid on: `aggregate` reads `/api/analytics`, and `event` or
`enrollment` reads `/api/analytics/{events,enrollments}/query` under one program, which is why
those two modes require a `program`. A `program` that is not a DHIS2 uid fails the step before any
request is sent, so a value from a run param or a source's input stays inside the query path, and
one the instance does not know fails it with `dhis2.unknown_uids` unless `require_known` is off.

`rows` is the grid read by name: each row an object keyed by its header's `name`, so an aggregate
row reads `{dx, pe, ou, value}` rather than a list whose positions follow `dimension`. `body` is
the grid as DHIS2 answered it, for the `metaData` that names every item and the `headers` that
type every column. An event or enrollment query's `pager` comes from the grid's own
`metaData.pager`.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the dhis2 connection naming the instance. |
| `mode` | `"aggregate" or "event" or "enrollment"` | yes |  | Which analytics query to run: `aggregate` over `/api/analytics`, or an `event` or `enrollment` query over `/api/analytics/{events,enrollments}/query`. |
| `dimension` | `string[]` |  | `[]` | The DHIS2 `dimension=` axes, such as `dx:fbfJHSPpUQD` or `pe:LAST_12_MONTHS`. |
| `filter` | `string or string[]` |  | `[]` | The DHIS2 `filter=` axes, fixing a dimension the result is not broken down by: one string such as `ou:ImspTQPwCqd`, or a list such as `[ou:ImspTQPwCqd, pe:2026Q1]` that is sent as one `filter=` each. |
| `program` | `string or null` |  | `null` | The uid of the program an `event` or `enrollment` query reads; unused for aggregate. |
| `start_date` | `string or null` |  | `null` | The ISO start of the query window, for the query kinds that take one. |
| `end_date` | `string or null` |  | `null` | The ISO end of the query window, for the query kinds that take one. |
| `output_id_scheme` | `string or null` |  | `null` | The DHIS2 `outputIdScheme`, such as `UID` or `NAME`, applied to the answer. |
| `page` | `integer or null` |  | `null` | The 1-based page to read, for the event and enrollment queries that page. |
| `page_size` | `integer or null` |  | `null` | How many rows a page holds, for the event and enrollment queries that page. |
| `require_known` | `boolean` |  | `true` | Whether an `event` or `enrollment` query fails when its program is unknown to the instance, rather than answering an empty grid. One metadata lookup asks for it first. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `rows` | `object[]` | yes |  | The grid's rows, each an object keyed by its header's name, such as `dx`, `pe`, `ou` and `value`. |
| `pager` | `object or null` |  | `null` | The page an event or enrollment query read and whether more follow; null for a grid that is not paged. |
| `body` | `any or null` |  | `null` | The grid as DHIS2 answered it: `headers`, `metaData` with the names of every item, `rows` as lists, `height` and `width`. |
| `duration_ms` | `integer` | yes |  | How long the query took. |

### `dhis2.analytics_run`

Run the DHIS2 analytics tables job.

Not idempotent. Polls every 1m unless the step says otherwise.

Asks the instance first whether an analytics job is already running, and follows that one
instead of submitting a second when it is; `join_running: false` always submits, and so does a
user the instance refuses the job listing. Otherwise it submits the job to
`/api/resourceTables/analytics`. A job type or task id in the answer that is not one plain path
segment fails the step with `dhis2.task.no_reference`, before the task is polled. Either
way it then follows the task's notification feed: each
probe streams the messages new since its cursor into the run's log, and the feed's own
completion is what ends the step. A task that has written nothing fifteen minutes after
submission is taken to be gone, because DHIS2 answers a task it never had exactly the way it
answers one that has not spoken yet. A feed that is empty after it had spoken is gone at once:
an instance that restarts drops every task's notifications, and the job with them. Collecting
the result asks for the terminal notification, and a feed without one fails the step as
transient rather than answering an empty story as a success. DHIS2 offers no way to stop a
running analytics job, so a cancelled step leaves the job to finish on the instance.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the dhis2 connection naming the instance. |
| `last_years` | `integer or null` |  | `null` | Limit the tables to this many years back, or leave unset to build them all. |
| `skip_resource_tables` | `boolean` |  | `false` | Whether the resource tables are left as they are. |
| `skip_aggregate` | `boolean` |  | `false` | Whether aggregate data analytics tables are left as they are. |
| `skip_events` | `boolean` |  | `false` | Whether event analytics tables are left as they are. |
| `skip_enrollment` | `boolean` |  | `false` | Whether enrollment analytics tables are left as they are. |
| `skip_org_unit_ownership` | `boolean` |  | `false` | Whether the org unit ownership table is left as it is. |
| `join_running` | `boolean` |  | `true` | Whether an analytics job already running on the instance is followed instead of a second one being submitted. The joined job runs with the options it was started with, not these. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `task_id` | `string` | yes |  | The id the instance gave the job. |
| `completed_at` | `string or null` |  | `null` | When the task said it was done, in the instance's own timestamp. |
| `messages` | `string[]` | yes |  | The last few notification messages, oldest first. |
| `joined` | `boolean` |  | `false` | Whether the step followed a job already running rather than submitting its own. |

### `dhis2.data_set_completion`

Mark a DHIS2 data set complete, or reopen it, for a period and org unit.

Idempotent.

Posts one completion registration to `/api/completeDataSetRegistrations`, the path every supported
version writes registrations through and the one that takes `dryRun`, and reads the import summary
as the instance's verdict. `completed: false` reopens the window rather than deleting the
registration, which is what `dhis2.data_set_complete` reads as a window still open. A summary whose
status is `ERROR`, or one that ignored the registration, fails the step with
`dhis2.data_set_completion.refused` and the instance's reason; an answer with no summary in it
fails with `dhis2.import.no_summary`. Both are `rejected`.

Each conflict carries the instance's `object` and `value`, its `error_code`, and the `indexes` of
the refused registrations.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the dhis2 connection naming the instance. |
| `data_set` | `string` | yes |  | The uid of the data set. |
| `period` | `string` | yes |  | An ISO period identifier, such as 202607 or 2026Q1. |
| `org_unit` | `string` | yes |  | The uid of the organisation unit. |
| `attribute_option_combo` | `string or null` |  | `null` | The uid of the attribute option combo, for a data set with an attribute category combo; the default combo when unset. |
| `completed` | `boolean` |  | `true` | Whether the window is marked complete; false reopens it. |
| `dry_run` | `boolean` |  | `false` | Whether the instance validates the registration without writing anything. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `status` | `string` | yes |  | The summary's own word: SUCCESS or WARNING. |
| `completed` | `boolean` | yes |  | Whether the window was marked complete, or reopened. |
| `dry_run` | `boolean` | yes |  | Whether this was a validation only, with nothing written. |
| `sent` | `integer` | yes |  | How many registrations were sent: one. |
| `counts` | `object` | yes |  | What happened to the registration: imported, updated, ignored or deleted. |
| `conflicts` | `object[]` | yes |  | Every refusal the summary names, empty when the registration was taken. |

### `dhis2.data_store`

Get, set or delete a DHIS2 data store key, or list a namespace's keys.

Idempotent.

Addresses the data store, `/api/dataStore`, or with `user_store` the signed-in user's own,
`/api/userDataStore`. `keys` lists a namespace's keys as `rows`; `get`, `set` and `delete` take
one `key`, and a config missing it is refused at apply with `dhis2.data_store.no_key`, as a `set`
with no `value` is with `dhis2.data_store.no_value`.

Every action reads first, so the output says whether the key was there: a `get` of a key the
namespace does not hold answers `found: false` and a null `value` rather than failing, a
`delete` of one sends nothing, and a `set` creates the key with a POST when it was not there and
replaces it with a PUT when it was, saying which in `created`. The value is read as it is stored,
an object, a list or a scalar. `encrypt` asks the instance to store a `set`'s value encrypted.
DHIS2 has no dry run for the data store. A namespace and a key are each one path segment, escaped,
and one holding a slash is refused.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the dhis2 connection naming the instance. |
| `action` | `"get" or "set" or "delete" or "keys"` |  | `"get"` | What the step does: `get` reads the key, `set` writes `value` to it, creating or replacing it, `delete` removes it, and `keys` lists the namespace's keys. |
| `namespace` | `string` | yes |  | The namespace, such as an app's own or one an integration keeps its state in. |
| `key` | `string or null` |  | `null` | The key in the namespace; every action but `keys` needs one. |
| `value` | `any` |  | `null` | The JSON to store, for `set`: an object, a list, a string, a number or a boolean. |
| `encrypt` | `boolean` |  | `false` | Whether `set` asks the instance to store the value encrypted. |
| `user_store` | `boolean` |  | `false` | Whether the step addresses the signed-in user's own store, `/api/userDataStore`, rather than the shared one. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `action` | `"get" or "set" or "delete" or "keys"` | yes |  | What the step did. |
| `namespace` | `string` | yes |  | The namespace addressed. |
| `key` | `string or null` |  | `null` | The key addressed; null for `keys`. |
| `found` | `boolean` | yes |  | Whether the key, or for `keys` the namespace, was there before the step: a `get` of a key that is not there answers false rather than failing, and so does a `delete`. |
| `value` | `any` |  | `null` | The value read, or the value written; null for `delete`, for `keys`, and for a key that was not there. |
| `rows` | `string[]` |  |  | The namespace's keys, for `keys`; empty for every other action. |
| `created` | `boolean` |  | `false` | Whether `set` made a new key rather than replacing one. |

### `dhis2.data_value`

Get, set or delete one DHIS2 data value by data element, period and org unit.

Not idempotent.

Addresses one cell through `/api/dataValues`: `get` reads it, `set` posts `value` (and
`comment`), `delete` removes it. The attribute option combo is named the way that endpoint names
one, as `attribute_combo` and `attribute_options` together, sent as `cc` and `cp`; the endpoint
takes no attribute option combo uid and files a value under the default combo when given one.
Half the pair is refused at apply with `dhis2.data_value.half_attribute`, and a `set` without a
`value` with `dhis2.data_value.no_value`; a run whose references resolve to either is refused the
same way before anything is sent.

A `get` of an empty cell is not a failure: the output says `found: false`. DHIS2 2.43 and later
answer that read 404, and 2.42 answers 409 with "Data value does not exist"; both are read as
absent, and any other 409 is a refusal.

A dry run never calls `/api/dataValues`, which accepts `dryRun=true` and writes the value anyway.
It sends the cell as a one-value `/api/dataValueSets` import with `dryRun=true` instead, with
`importStrategy=DELETE` for a delete, and an attribute option combo is resolved to its uid by
reading the attribute combo's option combos first. A rehearsal the instance would refuse fails the
step with `dhis2.data_value.refused` and its reason.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the dhis2 connection naming the instance. |
| `action` | `"get" or "set" or "delete"` |  | `"get"` | What the step does: `get` reads the value, `set` writes `value`, `delete` removes it. |
| `data_element` | `string` | yes |  | The uid of the data element. |
| `period` | `string` | yes |  | An ISO period identifier, such as 202607 or 2026Q1. |
| `org_unit` | `string` | yes |  | The uid of the organisation unit. |
| `category_option_combo` | `string or null` |  | `null` | The uid of the category option combo, the disaggregation; the default combo when unset. |
| `attribute_combo` | `string or null` |  | `null` | The uid of the attribute category combo, given together with `attribute_options`; the default attribute option combo when both are unset. |
| `attribute_options` | `string[]` |  | `[]` | The uids of the attribute category options that, with `attribute_combo`, name the attribute option combo. |
| `value` | `string or null` |  | `null` | The value to write, always a string on the wire whatever the value type; `set` needs one. |
| `comment` | `string or null` |  | `null` | A comment to store with the value, for `set`. |
| `dry_run` | `boolean` |  | `false` | Whether a `set` or `delete` is only validated, with nothing written. It is sent as a one-value `/api/dataValueSets` import with `dryRun=true`, because `/api/dataValues` accepts `dryRun` and writes the value anyway. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `action` | `"get" or "set" or "delete"` | yes |  | What the step did. |
| `data_element` | `string` | yes |  | The uid of the data element. |
| `period` | `string` | yes |  | The ISO period. |
| `org_unit` | `string` | yes |  | The uid of the organisation unit. |
| `category_option_combo` | `string or null` |  | `null` | The uid of the category option combo, when one was named. |
| `attribute_option_combo` | `string or null` |  | `null` | The uid of the attribute option combo a dry run resolved, when one was named. |
| `value` | `string or null` |  | `null` | The value read or written; null when a read found none, and for a delete. |
| `found` | `boolean` | yes |  | Whether the value exists: for `get` whether one is stored, otherwise whether the write was taken. |
| `dry_run` | `boolean` | yes |  | Whether this was a validation only, with nothing written. |

### `dhis2.data_value_set_export`

Export a DHIS2 data value set as JSON, CSV, XML or ADX.

Idempotent.

Reads what `/api/dataValueSets` is asked for and answers with the parsed document as its `body`,
which a `dhis2.data_value_set_import` takes whole as `data_values: ${steps.<step>.output.body}`.
A run that has to leave the export behind as a file hands that body to `storage.write`, which is
the only block that puts a value into storage.

Each selector takes one uid or a list. DHIS2 needs one of each kind, and a config missing one is
refused before any request: what to read (`data_set`, `data_element` or `data_element_group`),
where (`org_unit` or `org_unit_group`, with `children` for the descendants), and when (`period`,
`start_date` with `end_date`, `last_updated`, or `last_updated_duration`). An incremental sync
reads `last_updated` from the previous run's start, or `last_updated_duration: 1d` on a daily
schedule. `include_deleted` adds the values deleted since, marked `deleted`, and the id schemes
write the document's identifiers as codes, names or an attribute's values instead of uids.

Every named data set, data element, group and org unit is looked up first, in one request: a uid
the instance does not know fails the step with `dhis2.unknown_uids` instead of exporting an
empty set for it. `require_known: false` skips the lookup.

An answer with no body at all fails the step as `rejected` with `dhis2.export.empty_answer`:
DHIS2 answers 200 and nothing else for an org unit outside the account's data scope, where an
export that found no values still answers with a `dataValues` list. An export of one data set
whose answer names neither the data set nor a `dataValues` list is refused the same way; DHIS2
2.42 leaves the data set out of a `last_updated` read, values or none, so a `dataValues` list
alone is an answer.

Every value in the body carries its own `period`, `orgUnit` and `attributeOptionCombo`. DHIS2
2.43 writes a field once on the set when every value shares it, and a one-unit export's values
then carry no org unit at all, where 2.42 repeats them on every value; the block copies what the
set holds down onto each value that lacks it, never over a value's own, so a step reading
`dataValues[].period` reads the same from either version.

With `children`, the body leaves out the document-level `orgUnit` DHIS2 echoes back. An import
applies that field to every value in place of the value's own, so a body that kept it would
write each descendant's values onto the org unit the export was asked for.

`format` picks the form: `json`, the default, parses the set into `body`; `csv`, `xml` and `adx`
are text, streamed from `/api/dataValueSets.csv`, `/api/dataValueSets.xml`, or
`/api/dataValueSets` with `Accept: application/adx+xml`, into the run's storage as it arrives.
The output then carries `uri`, where the whole export was written and what an import's
`data_values_uri` reads, and `text`, its head cut at the instance's inline capture size, with
`truncated` saying whether it was cut and `content_bytes` its size; `body` is null. Every
selector and id scheme applies in every form. An empty text answer is the same
`dhis2.export.empty_answer` as an empty JSON one.

| DHIS2 | JSON | CSV | XML | ADX |
| --- | --- | --- | --- | --- |
| 2.41 | export, import | export, import | export, import | export, import |
| 2.42 | export, import | export, import | export, import | export, import |
| 2.43 | export, import | export, import | export, import | import |
| 2.44 | export, import | export, import | export, import | import |

DHIS2 2.43 and 2.44 answer an ADX export with JSON, so an `adx` export from them is refused with
`dhis2.export.format_unsupported` before it is asked, and an ADX answer that is JSON is refused
the same way. Their XML export writes the set's period as an ISO interval, `2025-07-01/P1M`,
which their own XML import refuses with a 500; CSV and JSON round-trip on every version.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the dhis2 connection naming the instance. |
| `data_set` | `string or string[] or null` |  | `null` | The uid of a data set to export, or a list of them. |
| `data_element` | `string or string[] or null` |  | `null` | The uid of a data element to export, or a list of them. |
| `data_element_group` | `string or string[] or null` |  | `null` | The uid of a data element group whose members are exported, or a list of them. |
| `period` | `string or string[] or null` |  | `null` | An ISO period identifier such as 2026Q1, or a list of them. |
| `start_date` | `string or null` |  | `null` | The ISO start of a date range read in place of periods, taken with `end_date`. |
| `end_date` | `string or null` |  | `null` | The ISO end of a date range read in place of periods, taken with `start_date`. |
| `last_updated` | `string or null` |  | `null` | Read only values changed at or after this ISO date or instant, for an incremental sync. |
| `last_updated_duration` | `string (humane-duration) or null` |  | `null` | Read only values changed within this long before now, such as `1d` or `2h`. |
| `org_unit` | `string or string[] or null` |  | `null` | The uid of an organisation unit to export for, or a list of them. |
| `org_unit_group` | `string or string[] or null` |  | `null` | The uid of an organisation unit group whose members are exported for, or a list of them. |
| `children` | `boolean` |  | `false` | Whether the org units' descendants are included. The exported document then carries no document-level `orgUnit`, and each value keeps its own. |
| `include_deleted` | `boolean` |  | `false` | Whether values deleted on the instance are exported too, each marked `deleted`. |
| `id_scheme` | `string or null` |  | `null` | How every identifier in the document is written: `UID`, `CODE`, `NAME`, `ID` or `ATTRIBUTE:<uid>`; the instance's own default, UID, when unset. |
| `data_element_id_scheme` | `string or null` |  | `null` | How data elements are written, in place of `id_scheme`. |
| `org_unit_id_scheme` | `string or null` |  | `null` | How org units are written, in place of `id_scheme`. |
| `category_option_combo_id_scheme` | `string or null` |  | `null` | How category option combos are written, in place of `id_scheme`. |
| `format` | `"json" or "csv" or "xml" or "adx"` |  | `"json"` | The form the set is exported in: `json`, parsed into `body`; or `csv`, `xml` or `adx`, written whole to storage at `uri` with its head inlined as `text`. ADX is exported by 2.41 and 2.42 only. |
| `require_known` | `boolean` |  | `true` | Whether the step fails when a named data set, data element, group or org unit is unknown to the instance, rather than answering an empty set for it. One metadata lookup asks for every named uid before the export. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `format` | `"json" or "csv" or "xml" or "adx"` |  | `"json"` | The form the set was exported in. |
| `body` | `any or null` |  | `null` | The exported data value set, for `json`: the document a `dhis2.data_value_set_import` takes whole as its `data_values`. Every value carries its own period, org unit and attribute option combo, whichever version answered. Null for every other form. |
| `text` | `string or null` |  | `null` | The head of the exported text, for `csv`, `xml` and `adx`, cut at the instance's inline capture size; null for `json`. |
| `uri` | `string or null` |  | `null` | Where the whole exported text was written, for `csv`, `xml` and `adx`; never cut, and what an import's `data_values_uri` takes. Null for `json`. |
| `content_bytes` | `integer or null` |  | `null` | How large the exported text is, inlined or not; null for `json`. |
| `truncated` | `boolean` |  | `false` | Whether `text` is short of the export. Only the inline copy is ever cut. |
| `duration_ms` | `integer` | yes |  | How long the export took. |

### `dhis2.data_value_set_import`

Import a data value set into DHIS2, as JSON, CSV, XML or ADX.

Not idempotent.

Sends the document in `data_values`, written in the step or referenced from an upstream
output, or the one stored at `data_values_uri`. A document that is not an object
with a `dataValues` list fails `rejected` with `dhis2.import.no_data_values` before anything is
sent: the usual cause is an export's whole output, `${steps.export.output}`, passed where its
document, `${steps.export.output.body}`, was meant. An empty `dataValues` list is sent, and the
output's `sent: 0` says there was nothing to import; `require_values: true` fails the step with
`dhis2.import.no_values_taken` when the instance took no value at all.

The block reads the import summary as the instance's verdict: a 409 carrying a summary is that
verdict too, not a transport failure. A summary whose status is `ERROR` fails the step with the
first conflicts named, and so does a `WARNING` with ignored values under `atomic_mode: ALL`.
DHIS2 does not honour `ALL` as the rollback it describes: on every supported major the good
values are committed beside the conflicts, so that failure names how many values landed. An
envelope whose own status is `ERROR` fails the same way, whatever its summary says. A 200 without
an import summary in it fails the step too, since nothing then says the import took, and so does a
summary whose status is any word but `SUCCESS` or `WARNING`. A summary is a `response` with
`responseType: ImportSummary`, an `importCount` object, or the counts inline. A 409 with none of
those is an ordinary refusal, `dhis2.answered`. Every one of these failures is `rejected`, so the same document is not retried against the same
instance.

Each conflict carries the instance's `object` and `value`, its `error_code`, and the `indexes`
of the refused values in the document that was sent. DHIS2 2.43 names no `object`, so there
the indexes are what says which value it was, and a failure names it as `value #1`.

A dry run sends the document without its `completeDate`, and says so in the log. DHIS2 2.41 and
2.42 register the data set complete under `dryRun=true`, and a rehearsal must persist nothing.

`format` says what the document is written in, and it is sent in that media type to
`/api/dataValueSets`: `json` takes the object above; `csv`, `xml` and `adx` take the document's
text in `data_values`, and an object or a list there fails `rejected` with
`dhis2.import.not_text`. `data_values_uri` names a storage object to send in place of
`data_values`, such as an export's `uri`, and naming both is refused with
`dhis2.import.two_sources`. `sent` counts a CSV's rows past its header, and the `dataValue`
elements of XML and ADX. A dry run of XML or ADX leaves a `completeDate` attribute out the way
a JSON dry run leaves the field out.

`id_scheme`, `data_element_id_scheme`, `org_unit_id_scheme` and
`category_option_combo_id_scheme` say how the document names things: `UID`, `CODE`, `NAME`, `ID`
or `ATTRIBUTE:<uid>`. ADX is written in codes, which 2.41 and 2.42 assume and 2.43 and later do
not, so an `adx` import is sent with `idScheme=CODE` unless `id_scheme` says otherwise. DHIS2 2.41
to 2.44 import all four forms.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the dhis2 connection naming the instance. |
| `data_values` | `any` |  | `null` | The data value set to send, written in the step or referenced from one. For `json` an object with a `dataValues` list: an export's document is `${steps.<step>.output.body}`, and a document with no `dataValues` list fails the step before anything is sent. For `csv`, `xml` and `adx` the document's text, such as an export's `${steps.<step>.output.text}` when it was not truncated. |
| `data_values_uri` | `string or null` |  | `null` | A storage URI holding the document to send, read in place of `data_values`: an export's `${steps.<step>.output.uri}`, or a file a `storage.write` left. |
| `format` | `"json" or "csv" or "xml" or "adx"` |  | `"json"` | The form the document is written in: `json`, `csv`, `xml` or `adx`. DHIS2 2.41 to 2.44 import all four. |
| `id_scheme` | `string or null` |  | `null` | How every identifier in the document is written: `UID`, `CODE`, `NAME`, `ID` or `ATTRIBUTE:<uid>`; UID when unset, except for `adx`, which is sent as `CODE` unless this says otherwise. |
| `data_element_id_scheme` | `string or null` |  | `null` | How data elements are written, in place of `id_scheme`. |
| `org_unit_id_scheme` | `string or null` |  | `null` | How org units are written, in place of `id_scheme`. |
| `category_option_combo_id_scheme` | `string or null` |  | `null` | How category option combos are written, in place of `id_scheme`. |
| `dry_run` | `boolean` |  | `false` | Whether the instance validates the import without writing anything. A `completeDate` in the document is left out of a dry run: DHIS2 2.41 and 2.42 register the data set complete even under dryRun, and a rehearsal must persist nothing. |
| `import_strategy` | `"CREATE" or "UPDATE" or "CREATE_AND_UPDATE" or "DELETE"` |  | `"CREATE_AND_UPDATE"` | What the import may do to existing values: CREATE, UPDATE, CREATE_AND_UPDATE, or DELETE. |
| `atomic_mode` | `"ALL" or "NONE"` |  | `"ALL"` | ALL asks the instance to refuse the whole import on any conflict; NONE takes what it can. DHIS2 does not always honour ALL and may commit the good values beside the conflicts, so a failure under ALL names what landed. |
| `require_values` | `boolean` |  | `false` | Whether the step fails when the instance took no value at all: none imported, updated or deleted. Off, an empty `dataValues` list is sent and answers zero counts. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `status` | `string` | yes |  | The summary's own word: SUCCESS or WARNING. |
| `dry_run` | `boolean` | yes |  | Whether this was a validation only, with nothing written. |
| `sent` | `integer` | yes |  | How many values the document held; zero says nothing was there to import. |
| `counts` | `object` | yes |  | What happened to the values: imported, updated, ignored and deleted. |
| `objects` | `any[]` | yes |  | Every value the summary names on its own, always empty: DHIS2's data value summary counts values and names only the refused ones, in `conflicts`. |
| `conflicts` | `object[]` | yes |  | Every value the instance refused, empty when the import was clean. |

Each conflict is an object of `object` and `value` in the instance's own words, its `error_code`, and the `indexes` of the refused values.

### `dhis2.message`

Send a DHIS2 message to users, user groups or org units.

Not idempotent.

Starts one message conversation through `POST /api/messageConversations`, the same inbox the
DHIS2 web apps read. DHIS2 also sends it as email to every recipient with an email address
where the instance has SMTP configured; whether the email went out is the instance's to know,
and nothing in the answer says.

A user group reaches its members and an organisation unit the users assigned to it, so one
message can reach many more people than it names. The output counts what was named, not who
the instance expanded it to.

At least one recipient is required, in any of the three lists. A step naming none is refused
at apply with `dhis2.message.no_recipient`, and so is a run whose references resolve to none.
Every recipient is a DHIS2 uid. A 400 or a 409 from the instance -- such as a send whose
recipients name no one it knows -- is `rejected`.

DHIS2 answers a send with the new conversation's uid on the `Location` header only, so the
block reads the conversation back to report it. A send the instance took without saying
where is `rejected`, never retried, because a retry would send the message twice.

If DHIS2 accepts the message but the fetch-back fails, a retry can send it twice, because
dhis2w's `messaging.send` posts and then reads back.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the dhis2 connection naming the instance. |
| `subject` | `string` | yes |  | The subject line, up to 255 characters. |
| `text` | `string` | yes |  | The body of the message, which may be long and may be built from references. |
| `users` | `string[]` |  | `[]` | The uids of the users the message goes to. |
| `user_groups` | `string[]` |  | `[]` | The uids of the user groups whose members the message goes to. |
| `org_units` | `string[]` |  | `[]` | The uids of the organisation units whose assigned users the message goes to. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `conversation_id` | `string` | yes |  | The uid of the message conversation the instance created. |
| `user_count` | `integer` | yes |  | How many users the message named. |
| `user_group_count` | `integer` | yes |  | How many user groups the message named. |
| `org_unit_count` | `integer` | yes |  | How many organisation units the message named. |

### `dhis2.metadata`

Read one DHIS2 metadata collection, whole or one page of it.

Idempotent.

Reads one collection through the version-bound generic accessor, so `resource` is the
collection name as it appears in the API path and a name the instance's version does not
publish is `rejected` rather than retried. `paging` is off by default: a metadata read wants
the whole collection, not its first page.

The rows come back under `rows`, and a paged read's `pager` says where it stands. It is also
how a collection is counted: `paging: true` and `page_size: 1` send one row, and the output's
`pager.total` is how many there are. Several collections read whole are one
[`dhis2.metadata_export`](#dhis2metadata_export) step instead.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the dhis2 connection naming the instance. |
| `resource` | `string` | yes |  | The DHIS2 collection name, as it appears in the API path: `organisationUnits`, `dataElements`, `dataSets`, `indicators`, `programs`, `optionSets`, `trackedEntityTypes`, and the rest the version-bound client knows. |
| `fields` | `string or string[] or null` |  | `null` | The DHIS2 `fields=` selector, as one string such as `id,name,valueType` or a list such as `[id, name, valueType]` that is sent comma-joined; the instance's own default when unset. Inside a YAML flow list a nested selector such as `parent[id,code]` must be quoted, as in `[id, "parent[id,code]"]`, because YAML refuses an unquoted bracket or comma in a flow item. |
| `filter` | `string or string[] or null` |  | `null` | One or more DHIS2 `filter=` expressions: one string such as `level:eq:2`, or a list such as `[level:eq:2, name:like:Bo]` that is sent as one `filter=` each, ANDed unless the resource is told otherwise. |
| `paging` | `boolean` |  | `false` | Whether the read is paged. Off by default: a metadata read wants the whole collection, not the first page of it. |
| `order` | `string or string[] or null` |  | `null` | The DHIS2 `order=` terms: one string such as `name:asc`, or a list such as `[level:asc, name:asc]` that is sent comma-joined, the first term sorting first. |
| `page` | `integer or null` |  | `null` | The 1-based page to read, when `paging` is on. |
| `page_size` | `integer or null` |  | `null` | How many rows a page holds, when `paging` is on. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `rows` | `any[]` | yes |  | The collection's rows, each with the fields `fields` selected. |
| `pager` | `object or null` |  | `null` | The page read, the page size, the collection's total, and whether more pages follow; null when the read is not paged and so answered every row. |
| `duration_ms` | `integer` | yes |  | How long the read took. |

The instance's own version and system information is not a metadata collection, so it is read
with [`dhis2.system_info`](#dhis2system_info) rather than with this block.

### `dhis2.metadata_export`

Read several DHIS2 metadata collections, every row of each, in one request.

Idempotent.

Reads every collection `resources` names in one `GET /api/metadata`, and answers with each under
its own name in `collections` and its row count in `totals`. Each name is checked against the
version-bound client first, so a name the instance's version does not publish is `rejected`
before any export is sent. `fields`, `filter` and `order` are shared by every collection; a
collection written as a mapping key may name its own, which replace the shared ones for it alone.
Every term is sent scoped to its collection, as `<resource>:fields`, `<resource>:filter` and
`<resource>:order`.

`/api/metadata` has no pager: it answers with every row that matches. To count a collection,
read it with [`dhis2.metadata`](#dhis2metadata), `paging: true` and `page_size: 1`, and take
`pager.total`.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the dhis2 connection naming the instance. |
| `resources` | `string[] or object` | yes |  | The DHIS2 collection names to read, as they appear in the API path: a list such as `[dataSets, programs]` that each take the shared terms, or a mapping from a name to its own `fields`, `filter` and `order`, where a term a collection leaves unset falls back to the shared one and `{}` takes them all. |
| `fields` | `string or string[] or null` |  | `null` | The `fields=` selector every collection is read with unless it names its own: one string such as `id,name` or a list sent comma-joined; DHIS2's own `:owner` when unset. |
| `filter` | `string or string[] or null` |  | `null` | The `filter=` expressions every collection is narrowed by unless it names its own: one string such as `name:like:ANC` or a list sent as one filter each and ANDed. |
| `order` | `string or string[] or null` |  | `null` | The `order=` terms every collection is sorted by unless it names its own: one string such as `name:asc` or a list sent comma-joined. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `collections` | `object of any[]` | yes |  | Every collection asked for, keyed by its name, holding the rows the instance answered with; an empty list for a collection with no row that matched. |
| `totals` | `object of integer` | yes |  | How many rows each collection holds in `collections`, keyed by its name. |
| `duration_ms` | `integer` | yes |  | How long the export took. |

### `dhis2.metadata_import`

Create, update or delete DHIS2 metadata from a bundle, one object or many.

Not idempotent.

Posts one bundle to `/api/metadata`: an object keyed by collection name, each holding the
objects to write. It is the shape `dhis2.metadata_export` answers under `collections`, and DHIS2's
own export, so an export's `collections` is a bundle as it stands. One object is a bundle of one:
`{dataElements: [{...}]}` creates a data element, the same bundle holding only its `id` deletes it
under `import_strategy: DELETE`, and `import_strategy: UPDATE` with `merge_mode: MERGE` changes the
fields it names and keeps the rest. There is no separate single-object block, because the
per-object endpoints have no dry run and answer a different report.

A dry run is sent as `importMode=VALIDATE`, never `dryRun`: the metadata importer accepts
`dryRun=true` without a word and commits the bundle. `atomic_mode` takes `ALL` or `NONE` only,
since the importer reads the tracker's `OBJECT`, or any other word, as `ALL`. The report is asked
for in full, so `objects` names every object with its uid, including one the instance generated.

The report is read whether it came on 200 or on 409. A report whose status is `ERROR` fails the
step with `dhis2.metadata_import.refused`, naming the first refused objects, unless
`fail_on_error` is off, when the step succeeds and `conflicts` carries them. A bundle that is not an
object is refused with `dhis2.metadata_import.not_a_bundle` before anything is sent, and an answer
with no report in it fails with `dhis2.metadata_import.no_report`. Every one of these is
`rejected`.

`counts` and each entry of `by_class` are the pack's import counts, with DHIS2's `created`
answered as `imported`. Each object names its `object_class`, `uid` and `index`; each conflict
adds the instance's `error_code`, its words as `value`, and the `property` it is about.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the dhis2 connection naming the instance. |
| `metadata` | `any` | yes |  | The metadata bundle to send: an object keyed by collection name, such as `{dataElements: [...], dataSets: [...]}`, written in the step or referenced from an upstream output. |
| `dry_run` | `boolean` |  | `false` | Whether the instance validates the bundle without writing anything, sent as `importMode=VALIDATE`: DHIS2's metadata importer ignores `dryRun` and commits. |
| `import_strategy` | `"CREATE_AND_UPDATE" or "CREATE" or "UPDATE" or "DELETE"` |  | `"CREATE_AND_UPDATE"` | What the import may do to existing objects: CREATE_AND_UPDATE, CREATE, UPDATE, or DELETE. |
| `atomic_mode` | `"ALL" or "NONE"` |  | `"ALL"` | ALL refuses the whole bundle when any object is refused; NONE writes what it can. |
| `identifier` | `"UID" or "CODE" or "AUTO"` |  | `"UID"` | Which property objects and references are matched by: UID, CODE, or AUTO for either. |
| `merge_mode` | `"REPLACE" or "MERGE" or null` |  | `null` | How an update meets the stored object: REPLACE overwrites every field, MERGE keeps the fields the bundle leaves out; the instance's own default, REPLACE, when unset. |
| `skip_sharing` | `boolean` |  | `false` | Whether the sharing settings in the bundle are left out of the import. |
| `fail_on_error` | `boolean` |  | `true` | Whether a report whose status is ERROR fails the step; off, the step succeeds and the output carries the errors. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `status` | `string` | yes |  | The report's own word: OK, WARNING, or ERROR when `fail_on_error` is off. |
| `dry_run` | `boolean` | yes |  | Whether this was a validation only, with nothing written. |
| `sent` | `integer` | yes |  | How many objects the bundle held, across its collections. |
| `counts` | `object` | yes |  | What happened to the objects: imported (DHIS2's created), updated, ignored and deleted. |
| `by_class` | `object of object` | yes |  | The same counts for each class of object in the bundle, keyed by class, such as DataElement. |
| `objects` | `object[]` | yes |  | Every object the report names, with its uid. |
| `conflicts` | `object[]` | yes |  | Every object the report refused, empty when the import was clean. |

### `dhis2.predictor_run`

Run DHIS2 predictors over a date range.

Idempotent.

Runs one `predictor` through `/api/predictors/{uid}/run`, one `predictor_group` through
`/api/predictorGroups/{uid}/run`, or with neither every predictor on the instance through
`/api/predictors/run`, for `start_date` to `end_date`; naming both is refused with
`dhis2.predictor.both_targets`. The run is one request that DHIS2 holds open until the values are
written, and `predictions` is the count its answer gives, with the summary's `inserted`,
`updated`, `deleted` and `unchanged` where the version reports them. DHIS2 has no dry run for
predictors, so every example that runs one names no group by default.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the dhis2 connection naming the instance. |
| `start_date` | `string` | yes |  | The ISO date the range starts on, such as 2026-01-01. |
| `end_date` | `string` | yes |  | The ISO date the range ends on, such as 2026-03-31. |
| `predictor` | `string or null` |  | `null` | The uid of one predictor to run. |
| `predictor_group` | `string or null` |  | `null` | The uid of a predictor group whose members run. With neither this nor `predictor`, every predictor on the instance runs. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `predictions` | `integer` | yes |  | How many values the run predicted, as the instance counted them. |
| `inserted` | `integer or null` |  | `null` | How many predicted values were new, where the instance reported it. |
| `updated` | `integer or null` |  | `null` | How many replaced a value predicted before, where the instance reported it. |
| `deleted` | `integer or null` |  | `null` | How many earlier predictions were removed, where the instance reported it. |
| `unchanged` | `integer or null` |  | `null` | How many matched what was already there, where the instance reported it. |
| `message` | `string or null` |  | `null` | What the instance said, in its own words. |

### `dhis2.resource_tables_run`

Rebuild the DHIS2 resource tables, without the analytics tables.

Not idempotent. Polls every 30s unless the step says otherwise.

Submits `POST /api/resourceTables`, the resource tables on their own without the analytics
tables, and follows the `RESOURCE_TABLE` job exactly as `dhis2.analytics_run` follows its own: a
job already running is joined unless `join_running` is off, each probe streams the new
notifications into the run's log, and a task silent for fifteen minutes, or whose feed empties
after it had spoken, is gone. A job that ends at level `ERROR` fails the step with its last
message. DHIS2 offers no way to stop the job, so a cancelled step leaves it to finish.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the dhis2 connection naming the instance. |
| `join_running` | `boolean` |  | `true` | Whether a resource tables job already running on the instance is followed instead of a second one being submitted. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `task_id` | `string` | yes |  | The id the instance gave the job. |
| `completed_at` | `string or null` |  | `null` | When the task said it was done, in the instance's own timestamp. |
| `messages` | `string[]` | yes |  | The last few notification messages, oldest first. |
| `joined` | `boolean` |  | `false` | Whether the step followed a job already running rather than submitting its own. |

### `dhis2.sql_view`

Run a DHIS2 SQL view by uid and read its rows.

Idempotent.

Runs `GET /api/sqlViews/{uid}/data.json` for a stored view and answers its grid as `rows`, each
an object keyed by the result's column names, with `columns` beside them. `variables` fill a
`QUERY` view's `${name}` placeholders, each sent as `var=name:value`, and `criteria` narrow a
`VIEW` or `MATERIALIZED_VIEW` by column, each sent as `criteria=column:value`. The block sends
no SQL of its own.

DHIS2 pages a view's result at 50 rows unless told otherwise, so an unpaged step asks for every
row with `paging=false`; `paging: true` reads one `page` of `page_size` and answers a `pager`.
A uid the instance holds no view by fails `rejected`.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the dhis2 connection naming the instance. |
| `sql_view` | `string` | yes |  | The uid of the SQL view to run. |
| `variables` | `object` |  |  | Values for a `QUERY` view's `${name}` placeholders, keyed by name. DHIS2 keeps only letters and digits of each value, so a wildcard belongs in the view's SQL. |
| `criteria` | `object` |  |  | Column values a `VIEW` or `MATERIALIZED_VIEW` result is narrowed to, keyed by column, every one of them matched. |
| `paging` | `boolean` |  | `false` | Whether the read is paged. Off by default: DHIS2 answers a view's first 50 rows unless told otherwise, and a view is read for all of its rows. |
| `page` | `integer or null` |  | `null` | The 1-based page to read, when `paging` is on. |
| `page_size` | `integer or null` |  | `null` | How many rows a page holds, when `paging` is on. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `rows` | `object[]` | yes |  | The view's rows, each an object keyed by column name. |
| `columns` | `object[]` | yes |  | The result's columns, in the order the view selects them. |
| `title` | `string or null` |  | `null` | The view's name, as the result carries it. |
| `pager` | `object or null` |  | `null` | The page read, the page size, the total and whether more pages follow; null when the read is not paged and so answered every row. |
| `duration_ms` | `integer` | yes |  | How long the read took. |

### `dhis2.system_info`

Read a DHIS2 instance's version, build, server clock and analytics state.

Idempotent.

Reads `/api/system/info` through the connection, so a `base_url` that redirects is followed the
way the connection allows it and no `follow_redirects_with_auth` is needed. The keys a report
reads most are lifted into named fields; every other key, and a named one that did not hold a
string, is carried as the instance wrote it under `other`.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the dhis2 connection naming the instance. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `version` | `string or null` |  | `null` | The DHIS2 version, such as `2.42.1`. |
| `revision` | `string or null` |  | `null` | The source revision the running build was made from. |
| `build_time` | `string or null` |  | `null` | When the running build was made, as the instance writes it. |
| `system_id` | `string or null` |  | `null` | The instance's own system identifier. |
| `system_name` | `string or null` |  | `null` | The name the instance is configured with, its application title. |
| `instance_base_url` | `string or null` |  | `null` | The base URL the instance believes it is served at. |
| `server_date` | `string or null` |  | `null` | The instance's clock at the moment it answered. |
| `server_time_zone_id` | `string or null` |  | `null` | The time zone the server runs in, such as `Etc/UTC`. |
| `calendar` | `string or null` |  | `null` | The calendar the instance keeps its periods in, such as `iso8601` or `ethiopian`. |
| `date_format` | `string or null` |  | `null` | The date format the instance shows dates in, such as `yyyy-mm-dd`. |
| `last_analytics_table_success` | `string or null` |  | `null` | When the analytics tables were last generated successfully. |
| `last_analytics_table_runtime` | `string or null` |  | `null` | How long that last successful analytics table generation took, as the instance words it. |
| `interval_since_last_analytics_table_success` | `string or null` |  | `null` | How long ago that was, as the instance words it. |
| `other` | `object` |  |  | Every other key of the answer, as the instance wrote it: the database, the Java runtime, the memory and processor counts, and any of the named keys that did not hold a string. |
| `duration_ms` | `integer` | yes |  | How long the read took. |

### `dhis2.task_wait`

Wait on a DHIS2 background job by its job type and id.

Idempotent. Polls every 10s unless the step says otherwise.

Follows any DHIS2 background job by the `job_type` it is filed under and the `task_id` its
submission answered with, through `/api/system/tasks/{job type}/{id}`, the same feed
`dhis2.analytics_run` reads: nothing is sent at execute, each probe streams the notifications new
since the last into the run's log, and the job's terminal notification settles the step. A job
that ends at level `ERROR` fails the step with its last message, a task the instance answers 404
for is gone, and so is one whose feed stays empty for fifteen minutes or empties after it had
spoken. Both halves are held to one plain path segment at validation. Waiting on a job is not
owning it, so a cancelled step leaves the job running.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the dhis2 connection naming the instance. |
| `job_type` | `string` | yes |  | The job type the task is filed under, such as `DATAVALUE_IMPORT`, `METADATA_IMPORT`, `ANALYTICS_TABLE`, `RESOURCE_TABLE`, `PREDICTOR` or `DATA_INTEGRITY`. |
| `task_id` | `string` | yes |  | The id the instance gave the job, the `response.id` its submission answered with. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `task_id` | `string` | yes |  | The id of the job that was followed. |
| `job_type` | `string` | yes |  | The job type it is filed under. |
| `completed_at` | `string or null` |  | `null` | When the task said it was done, in the instance's own timestamp. |
| `messages` | `string[]` | yes |  | The last few notification messages, oldest first. |

### `dhis2.tracker`

Read DHIS2 tracker objects.

Idempotent.

Reads one `/api/tracker` collection, scoped by program, organisation unit and `ou_mode`, and
narrowed by `status`, `updated_after` and `filter` where the collection has them. The rows come
back under `rows`, whatever key the instance's version filed them under.

By default the read is one page, DHIS2's first 50 rows unless `page` and `page_size` say
otherwise, and `pager.more` says whether rows match past it: a step that reads one page of a
larger collection is told so rather than handed the first 50 as if they were all. `total: true`
asks the instance to count them too, which fills `pager.total` and `pager.page_count`.

`all_pages: true` reads every page, from the first, and answers them as one list. It is bounded
three ways, by `max_rows`, `max_pages` and `max_total` (the rows' size as JSON), and reaching any
of them fails the step `rejected` with `dhis2.tracker.cap_reached` rather than answering the part
read so far. A named program or org unit the instance does not know fails the step with
`dhis2.unknown_uids` unless `require_known` is off.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the dhis2 connection naming the instance. |
| `kind` | `"trackedEntities" or "enrollments" or "events"` | yes |  | The tracker collection to read: `trackedEntities`, `enrollments`, or `events`. |
| `program` | `string or null` |  | `null` | The uid of the program to scope the read to. |
| `org_unit` | `string or null` |  | `null` | The uid of the organisation unit to read within. |
| `ou_mode` | `"SELECTED" or "CHILDREN" or "DESCENDANTS" or "ACCESSIBLE" or "CAPTURE" or "ALL" or null` |  | `null` | How the org unit is interpreted: `SELECTED`, `CHILDREN`, `DESCENDANTS`, `ACCESSIBLE`, `CAPTURE`, or `ALL`. |
| `fields` | `string or string[] or null` |  | `null` | The DHIS2 `fields=` selector, as one string such as `event,status` or a list such as `[event, status]` that is sent comma-joined; the instance's own default when unset. Inside a YAML flow list a nested selector such as `dataValues[dataElement,value]` must be quoted, as in `[event, "dataValues[dataElement,value]"]`, because YAML refuses an unquoted bracket or comma in a flow item. |
| `filter` | `string or string[] or null` |  | `null` | One or more DHIS2 `filter=` expressions on the collection's attributes: one string such as `w75KJ2mc4zz:like:Anna`, or a list such as `[w75KJ2mc4zz:like:Anna, zDhUuAYrxNC:like:Kelly]` that is sent as one `filter=` each. Tracked entities and events take one; the enrollments collection has no attribute filter of its own, so a filter given for it rides through as a plain query parameter the instance may ignore. |
| `status` | `string or null` |  | `null` | The status to read, where the collection has one: an enrollment or event `status`. |
| `updated_after` | `string or null` |  | `null` | Read only rows changed at or after this ISO instant. |
| `page` | `integer or null` |  | `null` | The 1-based page to read; the first when unset. The output's `pager.more` says whether more pages follow it. |
| `page_size` | `integer or null` |  | `null` | How many rows a page holds: the instance's own default, 50, for one page, and 500 when every page is read. |
| `all_pages` | `boolean` |  | `false` | Whether every page is read, from the first until the instance has no more, and answered as one list. The read is bounded by `max_rows`, `max_pages` and `max_total`, and fails rather than answering part of the collection when one is reached. |
| `total` | `boolean` |  | `false` | Whether the instance counts every matching row (`totalPages=true`), so that `pager.total` and `pager.page_count` are known. Counting costs the instance a query of its own. |
| `max_rows` | `integer` |  | `100000` | The most rows reading every page may gather before the step fails. |
| `max_pages` | `integer` |  | `1000` | The most pages reading every page may request before the step fails. |
| `max_total` | `string or integer` |  | `"256mb"` | The most the gathered rows may come to, as JSON, before reading every page fails. |
| `require_known` | `boolean` |  | `true` | Whether the step fails when the named program or org unit is unknown to the instance, rather than answering no rows for it. One metadata lookup asks for both before the read. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `rows` | `any[]` | yes |  | The tracked entities, enrollments or events read, every page's in order when every page was read. |
| `pager` | `object` | yes |  | The page the rows came from, the page size, the totals when counted, and whether more pages follow. |
| `duration_ms` | `integer` | yes |  | How long the read took. |

### `dhis2.tracker_import`

Create, update or delete DHIS2 tracked entities, enrollments, events and relationships.

Not idempotent. Polls every 10s unless the step says otherwise.

Posts one bundle of `trackedEntities`, `enrollments`, `events` and `relationships` to
`/api/tracker`. By default the instance runs it as a job, as DHIS2 2.41 and later do on their own,
and the step hands the job to the engine rather than holding a worker: each probe reads
`/api/tracker/jobs/{id}`, a notification marked complete ends the wait, and the finished job's
report is read from `/api/tracker/jobs/{id}/report`. A job the instance answers 404 for is gone,
and so is one that has written nothing fifteen minutes after submission. A job whose final
notification is an `ERROR`, as it is when the report refused an object, is finished too: its
report is read and says why, and a job that ended in error with no report to read fails with
`dhis2.tracker_import.job_failed` and the job's own words. DHIS2 offers no way to stop a running import, so
cancelling the step leaves it to finish. `async_mode: false` holds one request open and reads the
report it answers with.

A dry run is sent as `importMode=VALIDATE`. The report is asked for in full and read whether it
came on 200 or on 409. A report whose status is `ERROR` fails the step with
`dhis2.tracker_import.refused`, naming the first refused objects, unless `fail_on_error` is off. A
bundle that is not an object is refused with `dhis2.tracker_import.not_a_bundle`, a job answer
without a plain job id with `dhis2.tracker_import.no_job`, and an answer with no report in it with
`dhis2.tracker_import.no_report`, which is `transient` when the finished job's report is not there
yet and `rejected` otherwise.

`counts` and each entry of `by_tracker_type` are the pack's import counts, with DHIS2's `created`
answered as `imported`; `by_tracker_type` is keyed by DHIS2's own names: `TRACKED_ENTITY`,
`ENROLLMENT`, `EVENT` and `RELATIONSHIP`. Each object names its `tracker_type`, `uid` and
`index`; each conflict and warning adds the instance's `error_code` and its words as `value`.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the dhis2 connection naming the instance. |
| `tracker` | `any` | yes |  | The tracker bundle to send: an object of `trackedEntities`, `enrollments`, `events` and `relationships` lists, written in the step or referenced from an upstream output. |
| `dry_run` | `boolean` |  | `false` | Whether the instance validates the bundle without writing anything, sent as `importMode=VALIDATE`. |
| `import_strategy` | `"CREATE_AND_UPDATE" or "CREATE" or "UPDATE" or "DELETE"` |  | `"CREATE_AND_UPDATE"` | What the import may do to existing objects: CREATE_AND_UPDATE, CREATE, UPDATE, or DELETE. |
| `atomic_mode` | `"ALL" or "OBJECT"` |  | `"ALL"` | ALL refuses the whole bundle when any object is refused; OBJECT writes every object that passes on its own. |
| `async_mode` | `boolean` |  | `true` | Whether the instance runs the import as a job the engine follows, as DHIS2 does by default; off, one request is held open until the report is in. |
| `fail_on_error` | `boolean` |  | `true` | Whether a report whose status is ERROR fails the step; off, the step succeeds and the output carries the errors. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `status` | `string` | yes |  | The report's own word: OK, WARNING, or ERROR when `fail_on_error` is off. |
| `dry_run` | `boolean` | yes |  | Whether this was a validation only, with nothing written. |
| `job_id` | `string or null` |  | `null` | The id of the job the instance ran the import as, when it ran as one. |
| `sent` | `integer` | yes |  | How many objects the bundle held, across its four lists. |
| `counts` | `object` | yes |  | What happened to the objects: imported (DHIS2's created), updated, ignored and deleted. |
| `by_tracker_type` | `object of object` | yes |  | The same counts for each tracker type in the bundle, such as TRACKED_ENTITY or EVENT. |
| `objects` | `object[]` | yes |  | Every object the report names, with its uid. |
| `conflicts` | `object[]` | yes |  | Every error the validation report names, empty when the import was clean. |
| `warnings` | `object[]` | yes |  | Every warning the validation report names. |

### `dhis2.validation_run`

Run DHIS2 validation rule analysis and answer the violations.

Idempotent.

Runs `POST /api/dataAnalysis/validationRules` over `org_unit` and every unit below it, for
`start_date` to `end_date`, every rule or one `validation_rule_group`, and answers each
violation: the rule, the org unit, the period, the attribute option combo, both sides and the
operator. DHIS2 runs the analysis in the foreground and answers in that one request, on every
supported version; there is no job to follow for it. `max_results` caps the answer.

`persist` and `notification` are the analysis's two writes, storing each violation under
`/api/validationResults` and sending the rules' notifications, and both are off by default, so
the analysis is a read. `fail_on_violations: true` fails the step `rejected` with
`dhis2.validation.violated`, naming the first violations, so a later step runs only on data
that holds.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the dhis2 connection naming the instance. |
| `org_unit` | `string` | yes |  | The uid of the org unit the analysis covers, with every unit below it. |
| `start_date` | `string` | yes |  | The ISO date the range starts on, such as 2026-01-01. |
| `end_date` | `string` | yes |  | The ISO date the range ends on, such as 2026-03-31. |
| `validation_rule_group` | `string or null` |  | `null` | The uid of a validation rule group to evaluate alone; every rule when unset. |
| `max_results` | `integer or null` |  | `null` | The most violations the instance answers with; its own cap, 500, when unset. |
| `persist` | `boolean` |  | `false` | Whether the instance also stores each violation as a validation result, a write to `/api/validationResults`. Off, the analysis writes nothing. |
| `notification` | `boolean` |  | `false` | Whether the instance also sends the notifications the violated rules are set up with. |
| `fail_on_violations` | `boolean` |  | `false` | Whether the step fails when any rule is violated, so a later step runs only on data that holds. Off, the violations are the output. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `violations` | `object[]` | yes |  | Each place a rule does not hold, empty when every rule held. |
| `count` | `integer` | yes |  | How many violations the analysis answered, at most `max_results`. |
| `duration_ms` | `integer` | yes |  | How long the analysis took. |

## Sensors

### `dhis2.data_set_complete`

Wait for a DHIS2 data set to be marked complete.

Polls every 1m unless the step says otherwise. Gives up after 24h unless the step says
otherwise.

Each poke reads `/api/completeDataSetRegistrations` once for the data set, period and
organisation unit. A registration carrying `completed: false` is a window that was reopened, so
the wait goes on; on an older instance, which answers without the flag, a registration's
existence is the completion.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the dhis2 connection naming the instance. |
| `data_set` | `string` | yes |  | The uid of the data set. |
| `period` | `string` | yes |  | An ISO period identifier, such as 2026Q1. |
| `org_unit` | `string` | yes |  | The uid of the organisation unit. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `completed_at` | `string or null` |  | `null` | When the registration was made, in the instance's own timestamp. |
| `stored_by` | `string or null` |  | `null` | Who marked the data set complete. |

## How a failure is classified

Every block inherits one classifier, so retry policy means the same thing across the pack:

| What happened | Class |
| --- | --- |
| The instance answered 5xx | `transient` |
| The instance answered 429, rate limiting | `transient` |
| The instance answered any other 4xx, or refused the credential | `rejected` |
| The client does not speak the instance's version | `rejected` |
| A connection or read failure on the wire | `transient` |

A refusal's message is the instance's own words when it gave any: a DHIS2 web message's
`message`, and the reason phrase when the body was not one.

## Every refusal carries a code

A refusal is catalogued: it carries a stable dotted code beside the sentence it renders, so a
stream of run records is selected by code however the English is later reworded --
`jq 'select(.error_code == "dhis2.import.refused")'`. The code is API and the text is not. The
codes from `dhis2.analytics_query.no_program` on are what a config refuses at validation.

| Code | Text |
| --- | --- |
| `dhis2.answered` | `{where} answered {status}: {remote}` |
| `dhis2.export.empty_answer` | `{where} answered with an empty body rather than a data value set, which DHIS2 does when {org_unit} is outside the account's data scope; nothing was exported` |
| `dhis2.unknown_uids` | `{where} is scoped to uids the instance knows no object by: {unknown}; the read would answer nothing for them, so it was not made. Check the uids, or set require_known: false to read anyway` |
| `dhis2.tracker.cap_reached` | `reading every page of {kind} reached {cap} ({limit}) with rows still to read; nothing is answered rather than a part of the collection. Raise {cap} or narrow the read` |
| `dhis2.task.no_reference` | `the job submission answered without a task reference to follow: a job type and a task id, each one plain path segment` |
| `dhis2.task.disappeared` | `task {task} disappeared before its result could be collected` |
| `dhis2.task.no_result` | `task {task} has no result to collect: the instance holds no terminal notification for it` |
| `dhis2.import.no_data_values` | `data_values {found}, not a data value set with a dataValues list, so nothing was sent. A step's whole output passed where its document was meant is the usual cause: an export's document is steps.<step>.output.body, not steps.<step>.output` |
| `dhis2.import.no_values_taken` | `the instance took none of the {sent} values sent, and require_values asks for at least one: {detail}` |
| `dhis2.import.no_summary` | `{where} answered without an import summary, so nothing says the import took` |
| `dhis2.import.unknown_status` | `{where} answered a summary whose status is '{status}', so nothing says the import took` |
| `dhis2.import.refused` | `the import was refused: {detail}` |
| `dhis2.import.took_nothing` | `the import took nothing: {detail}` |
| `dhis2.import.partial` | `the import took {taken} values and refused {ignored} despite atomic_mode ALL: {detail}` |
| `dhis2.import.conflicts_and_more` | `{named} (and {more} more)` |
| `dhis2.import.values_ignored` | `{ignored} values ignored` |
| `dhis2.connection.unreachable` | `the instance did not answer: {detail}` |
| `dhis2.connection.redirect_refused` | `base_url on {configured} redirects to {target}, which is neither that host, a subdomain of it, nor under dhis2.org beside it, so the credential was not sent; set base_url to the target if it is yours` |
| `dhis2.metadata.unknown_resource` | `the instance's version knows no metadata resource named '{resource}'` |
| `dhis2.message.no_recipient` | `a message needs at least one recipient in users, user_groups or org_units` |
| `dhis2.message.no_conversation` | `{where} took the message but answered without the conversation it created` |
| `dhis2.analytics_query.no_program` | `a {mode} analytics query needs a program to read under` |
| `dhis2.export.no_data` | `a data value set export names what to read: a data_set, data_element or data_element_group` |
| `dhis2.export.no_org_unit` | `a data value set export names where to read: an org_unit or org_unit_group` |
| `dhis2.export.no_period` | `a data value set export names when to read: a period, a start_date with an end_date, last_updated or last_updated_duration` |
| `dhis2.export.half_range` | `start_date and end_date bound one range, so a data value set export takes both or neither` |
| `dhis2.tracker.page_with_all_pages` | `all_pages reads every page from the first, so it takes no page` |
| `dhis2.connection.both_credentials` | `a dhis2 connection takes an api_token or basic credentials, not both` |
| `dhis2.connection.no_credential` | `a dhis2 connection needs an api_token or basic credentials` |
| `dhis2.connection.no_basic_password` | `basic credentials need a basic_password beside the basic_username` |
| `dhis2.connection.base_url_holds_more` | `base_url says where the instance is and nothing else: a user, a password, a query or a fragment in it is refused, because it is stored as written; a credential goes in api_token or basic_password` |
| `dhis2.connection.bad_api_token` | `an api_token must be visible ASCII with no whitespace, or it cannot be sent as a header value` |
| `dhis2.metadata_import.not_a_bundle` | `a metadata bundle is an object keyed by collection, such as dataElements, and this one is {got}` |
| `dhis2.metadata_import.no_report` | `{where} answered without an import report, so nothing says the import took` |
| `dhis2.metadata_import.refused` | `the metadata import was refused: {detail}` |
| `dhis2.tracker_import.not_a_bundle` | `a tracker bundle is an object of trackedEntities, enrollments, events or relationships, and this one is {got}` |
| `dhis2.tracker_import.no_report` | `{where} answered without an import report, so nothing says the import took` |
| `dhis2.tracker_import.no_job` | `{where} accepted the import as a job but answered without a job id to follow` |
| `dhis2.tracker_import.job_failed` | `import job {job} ended in error without a report to read; the job said: {said}` |
| `dhis2.tracker_import.refused` | `the tracker import was refused: {detail}` |
| `dhis2.data_value.no_value` | `setting a data value needs a value` |
| `dhis2.data_value.half_attribute` | `attribute_combo and attribute_options name an attribute option combo together: give both or neither` |
| `dhis2.data_value.unknown_attribute` | `attribute combo {combo} has no option combo made of exactly the options {options}` |
| `dhis2.data_value.refused` | `the instance would not take the data value: {detail}` |
| `dhis2.data_set_completion.refused` | `the completion registration was refused: {detail}` |
| `dhis2.export.format_unsupported` | `DHIS2 {version} does not export a data value set as {format}, and answers JSON in its place; ADX is exported by 2.41 and 2.42, and every version imports it` |
| `dhis2.import.not_text` | `a {format} import sends its document as text, and data_values is {found}; give the document's text, or its storage URI as data_values_uri` |
| `dhis2.import.two_sources` | `data_values and data_values_uri each name the document to send, so an import takes one of them` |
| `dhis2.data_store.no_key` | `get, set and delete address one key, so they need a key` |
| `dhis2.data_store.no_value` | `setting a data store key needs a value to store` |
| `dhis2.validation.violated` | `validation rule analysis found {count} violations, and fail_on_violations asks for none: {detail}` |
| `dhis2.predictor.both_targets` | `a predictor run names one predictor or one predictor group, not both; name neither to run every predictor` |
