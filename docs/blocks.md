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
  `dhis2.metadata`, `dhis2.tracker` and `dhis2.analytics_query`.
- **A read of several collections** answers `collections`, each one's rows under its own name,
  and `counts`, each one's row count under its name. That is `dhis2.metadata_export`.
- **`body`** carries a DHIS2 document as the instance wrote it, and only where the document is
  itself the thing to hand on: the data value set `dhis2.data_value_set_export` reads, which an
  import takes whole, and the analytics grid beside its `rows`, for its `headers` and
  `metaData`.
- **An import** answers its summary's `status`, `counts` holding `imported`, `updated`,
  `ignored` and `deleted`, and `conflicts`.
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
| [`dhis2.data_value`](#dhis2data_value) | operator | dhis2 | Get, set or delete one DHIS2 data value by data element, period and org unit. |
| [`dhis2.data_value_set_export`](#dhis2data_value_set_export) | operator | dhis2 | Export a DHIS2 data value set. |
| [`dhis2.data_value_set_import`](#dhis2data_value_set_import) | operator | dhis2 | Import a data value set into DHIS2. |
| [`dhis2.message`](#dhis2message) | operator | dhis2 | Send a DHIS2 message to users, user groups or org units. |
| [`dhis2.metadata`](#dhis2metadata) | operator | dhis2 | Read one DHIS2 metadata collection, whole or one page of it. |
| [`dhis2.metadata_export`](#dhis2metadata_export) | operator | dhis2 | Read several DHIS2 metadata collections, every row of each, in one request. |
| [`dhis2.metadata_import`](#dhis2metadata_import) | operator | dhis2 | Create, update or delete DHIS2 metadata from a bundle, one object or many. |
| [`dhis2.system_info`](#dhis2system_info) | operator | dhis2 | Read a DHIS2 instance's version, build, server clock and analytics state. |
| [`dhis2.tracker`](#dhis2tracker) | operator | dhis2 | Read DHIS2 tracker objects. |
| [`dhis2.tracker_import`](#dhis2tracker_import) | operator | dhis2 | Create, update or delete DHIS2 tracked entities, enrollments, events and relationships. |
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
segment fails the step with `dhis2.analytics.no_task_reference`, before the task is polled. Either
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

Export a DHIS2 data value set.

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
export that found no values still answers with the data set it was asked for.

Every value in the body carries its own `period`, `orgUnit` and `attributeOptionCombo`. DHIS2
2.43 writes a field once on the set when every value shares it, and a one-unit export's values
then carry no org unit at all, where 2.42 repeats them on every value; the block copies what the
set holds down onto each value that lacks it, never over a value's own, so a step reading
`dataValues[].period` reads the same from either version.

With `children`, the body leaves out the document-level `orgUnit` DHIS2 echoes back. An import
applies that field to every value in place of the value's own, so a body that kept it would
write each descendant's values onto the org unit the export was asked for.

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
| `require_known` | `boolean` |  | `true` | Whether the step fails when a named data set, data element, group or org unit is unknown to the instance, rather than answering an empty set for it. One metadata lookup asks for every named uid before the export. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `body` | `any or null` |  | `null` | The exported data value set, the document a `dhis2.data_value_set_import` takes whole as its `data_values`. Every value carries its own period, org unit and attribute option combo, whichever version answered. |
| `duration_ms` | `integer` | yes |  | How long the export took. |

### `dhis2.data_value_set_import`

Import a data value set into DHIS2.

Not idempotent.

Sends the document in `data_values`, written in the step or referenced from an upstream
output (a set held in storage comes in through `storage.read`). A document that is not an object
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

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the dhis2 connection naming the instance. |
| `data_values` | `any` | yes |  | The data value set document to send, an object with a `dataValues` list, written in the step or referenced from one: an export's document is `${steps.<step>.output.body}`, and a set held in storage comes in through storage.read. A document with no `dataValues` list fails the step before anything is sent. |
| `dry_run` | `boolean` |  | `false` | Whether the instance validates the import without writing anything. A `completeDate` in the document is left out of a dry run: DHIS2 2.41 and 2.42 register the data set complete even under dryRun, and a rehearsal must persist nothing. |
| `import_strategy` | `"CREATE" or "UPDATE" or "CREATE_AND_UPDATE" or "DELETE"` |  | `"CREATE_AND_UPDATE"` | What the import may do to existing values: CREATE, UPDATE, CREATE_AND_UPDATE, or DELETE. |
| `atomic_mode` | `"ALL" or "NONE"` |  | `"ALL"` | ALL asks the instance to refuse the whole import on any conflict; NONE takes what it can. DHIS2 does not always honour ALL and may commit the good values beside the conflicts, so a failure under ALL names what landed. |
| `require_values` | `boolean` |  | `false` | Whether the step fails when the instance took no value at all: none imported, updated or deleted. Off, an empty `dataValues` list is sent and answers zero counts. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `status` | `string` | yes |  | The summary's own word: SUCCESS or WARNING. |
| `sent` | `integer` | yes |  | How many values the document held; zero says nothing was there to import. |
| `counts` | `object` | yes |  | What happened to the values: imported, updated, ignored and deleted. |
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
its own name in `collections` and its row count in `counts`. Each name is checked against the
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
| `counts` | `object of integer` | yes |  | How many rows each collection holds in `collections`, keyed by its name. |
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
and so is one that has written nothing fifteen minutes after submission; a job whose final
notification is an `ERROR` fails the step. DHIS2 offers no way to stop a running import, so
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
| `dhis2.analytics.no_task_reference` | `the analytics job submission answered without a task reference to follow` |
| `dhis2.analytics.task_disappeared` | `task {task} disappeared before its result could be collected` |
| `dhis2.analytics.no_result` | `task {task} has no result to collect: the instance holds no terminal notification for it` |
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
| `dhis2.metadata_import.not_a_bundle` | `a metadata bundle is an object keyed by collection, such as dataElements, and this one is {got}` |
| `dhis2.metadata_import.no_report` | `{where} answered without an import report, so nothing says the import took` |
| `dhis2.metadata_import.refused` | `the metadata import was refused: {detail}` |
| `dhis2.tracker_import.not_a_bundle` | `a tracker bundle is an object of trackedEntities, enrollments, events or relationships, and this one is {got}` |
| `dhis2.tracker_import.no_report` | `{where} answered without an import report, so nothing says the import took` |
| `dhis2.tracker_import.no_job` | `{where} accepted the import as a job but answered without a job id to follow` |
| `dhis2.tracker_import.refused` | `the tracker import was refused: {detail}` |
| `dhis2.data_value.no_value` | `setting a data value needs a value` |
| `dhis2.data_value.half_attribute` | `attribute_combo and attribute_options name an attribute option combo together: give both or neither` |
| `dhis2.data_value.unknown_attribute` | `attribute combo {combo} has no option combo made of exactly the options {options}` |
| `dhis2.data_value.refused` | `the instance would not take the data value: {detail}` |
| `dhis2.data_set_completion.refused` | `the completion registration was refused: {detail}` |
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