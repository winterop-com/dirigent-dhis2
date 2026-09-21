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

| Block | Kind | Group | Summary |
| --- | --- | --- | --- |
| [`dhis2.analytics_query`](#dhis2analytics_query) | operator | dhis2 | Run a DHIS2 analytics query. |
| [`dhis2.analytics_run`](#dhis2analytics_run) | operator | dhis2 | Run the DHIS2 analytics tables job. |
| [`dhis2.data_value_set_export`](#dhis2data_value_set_export) | operator | dhis2 | Export a DHIS2 data value set. |
| [`dhis2.data_value_set_import`](#dhis2data_value_set_import) | operator | dhis2 | Import a data value set into DHIS2. |
| [`dhis2.metadata`](#dhis2metadata) | operator | dhis2 | Read a DHIS2 metadata resource. |
| [`dhis2.tracker`](#dhis2tracker) | operator | dhis2 | Read DHIS2 tracker objects. |
| [`dhis2.data_set_complete`](#dhis2data_set_complete) | sensor | dhis2 | Wait for a DHIS2 data set to be marked complete. |

## Operators

### `dhis2.analytics_query`

Run a DHIS2 analytics query.

Idempotent.

Runs one query and hands the grid on: `aggregate` reads `/api/analytics`, and `event` or
`enrollment` reads `/api/analytics/{events,enrollments}/query` under one program, which is why
those two modes require a `program`.

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

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `body` | `any or null` |  | `null` | The parsed response: the analytics grid, its headers, metaData, and rows. |
| `duration_ms` | `integer` | yes |  | How long the query took. |

### `dhis2.analytics_run`

Run the DHIS2 analytics tables job.

Not idempotent. Polls every 1m unless the step says otherwise.

Submits the job to `/api/resourceTables/analytics`, then follows the task's notification feed:
each probe streams the messages new since its cursor into the run's log, and the feed's own
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

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `task_id` | `string` | yes |  | The id the instance gave the job. |
| `completed_at` | `string or null` |  | `null` | When the task said it was done, in the instance's own timestamp. |
| `messages` | `string[]` | yes |  | The last few notification messages, oldest first. |

### `dhis2.data_value_set_export`

Export a DHIS2 data value set.

Idempotent.

Reads one data set, for one period, at one organisation unit, and answers with the parsed
document as its `body`. A run that has to leave the export behind as a file hands that body to
`storage.write`, which is the only block that puts a value into storage.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the dhis2 connection naming the instance. |
| `data_set` | `string` | yes |  | The uid of the data set to export. |
| `period` | `string` | yes |  | An ISO period identifier, such as 2026Q1. |
| `org_unit` | `string` | yes |  | The uid of the organisation unit to export for. |
| `children` | `boolean` |  | `false` | Whether the org unit's descendants are included. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `body` | `any or null` |  | `null` | The exported data value set, the value the next step works on. |
| `duration_ms` | `integer` | yes |  | How long the export took. |

### `dhis2.data_value_set_import`

Import a data value set into DHIS2.

Not idempotent.

Sends the document in `data_values`, written in the step or referenced from an upstream
output (a set held in storage comes in through `storage.read`), and reads the import summary as the instance's verdict: a 409 carrying a summary is that
verdict too, not a transport failure. A summary whose status is `ERROR` fails the step with the
first conflicts named, and so does a `WARNING` with ignored values under `atomic_mode: ALL`.
DHIS2 does not honour `ALL` as the rollback it describes: on every supported major the good
values are committed beside the conflicts, so that failure names how many values landed. A 200
without an import summary in it fails the step too, since nothing then says the import took.
Every one of these failures is `rejected`, so the same document is not retried against the same
instance.

A dry run sends the document without its `completeDate`, and says so in the log. DHIS2 2.41 and
2.42 register the data set complete under `dryRun=true`, and a rehearsal must persist nothing.

**Config**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `connection` | `string` | yes |  | The code of the dhis2 connection naming the instance. |
| `data_values` | `any` | yes |  | The data value set document to send, written in the step or referenced from one; a set held in storage comes in through storage.read. |
| `dry_run` | `boolean` |  | `false` | Whether the instance validates the import without writing anything. A `completeDate` in the document is left out of a dry run: DHIS2 2.41 and 2.42 register the data set complete even under dryRun, and a rehearsal must persist nothing. |
| `import_strategy` | `"CREATE" or "UPDATE" or "CREATE_AND_UPDATE" or "DELETE"` |  | `"CREATE_AND_UPDATE"` | What the import may do to existing values: CREATE, UPDATE, CREATE_AND_UPDATE, or DELETE. |
| `atomic_mode` | `"ALL" or "NONE"` |  | `"ALL"` | ALL asks the instance to refuse the whole import on any conflict; NONE takes what it can. DHIS2 does not always honour ALL and may commit the good values beside the conflicts, so a failure under ALL names what landed. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `status` | `string` | yes |  | The summary's own word: SUCCESS, WARNING, or ERROR. |
| `imported` | `integer` | yes |  | How many values were created. |
| `updated` | `integer` | yes |  | How many values were revised. |
| `ignored` | `integer` | yes |  | How many values the instance did not take. |
| `deleted` | `integer` | yes |  | How many values were removed. |
| `conflicts` | `object[]` | yes |  | Every value the instance refused, empty when the import was clean. |

Each conflict is an object of two strings, `object` and `value`, in the instance's own words.

### `dhis2.metadata`

Read a DHIS2 metadata resource.

Idempotent.

Reads one collection through the version-bound generic accessor, so `resource` is the
collection name as it appears in the API path and a name the instance's version does not
publish is `rejected` rather than retried. `paging` is off by default: a metadata read wants
the whole collection, not its first page.

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
| `body` | `any or null` |  | `null` | The parsed response: the collection under its own key, and a `pager` when paged. |
| `duration_ms` | `integer` | yes |  | How long the read took. |

The instance's own version and system information is not a metadata collection, so it is read
with `http.request` rather than with this block.

### `dhis2.tracker`

Read DHIS2 tracker objects.

Idempotent.

Reads one page of one `/api/tracker` collection, scoped by program, organisation unit and
`ou_mode`, and narrowed by `status`, `updated_after` and `filter` where the collection has
them.

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
| `page` | `integer or null` |  | `null` | The 1-based page to read. |
| `page_size` | `integer or null` |  | `null` | How many rows a page holds. |

**Output**

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `body` | `any or null` |  | `null` | The parsed response: the objects under `instances` and the `page` block DHIS2 sends. |
| `duration_ms` | `integer` | yes |  | How long the read took. |

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
last three are what the connection kind refuses at validation.

| Code | Text |
| --- | --- |
| `dhis2.answered` | `{where} answered {status}: {remote}` |
| `dhis2.analytics.no_task_reference` | `the analytics job submission answered without a task reference to follow` |
| `dhis2.analytics.task_disappeared` | `task {task} disappeared before its result could be collected` |
| `dhis2.analytics.no_result` | `task {task} has no result to collect: the instance holds no terminal notification for it` |
| `dhis2.import.no_summary` | `{where} answered without an import summary, so nothing says the import took` |
| `dhis2.import.refused` | `the import was refused: {detail}` |
| `dhis2.import.took_nothing` | `the import took nothing: {detail}` |
| `dhis2.import.partial` | `the import took {taken} values and refused {ignored} despite atomic_mode ALL: {detail}` |
| `dhis2.metadata.unknown_resource` | `the instance's version knows no metadata resource named '{resource}'` |
| `dhis2.analytics_query.no_program` | `a {mode} analytics query needs a program to read under` |
| `dhis2.connection.both_credentials` | `a dhis2 connection takes an api_token or basic credentials, not both` |
| `dhis2.connection.no_credential` | `a dhis2 connection needs an api_token or basic credentials` |
| `dhis2.connection.no_basic_password` | `basic credentials need a basic_password beside the basic_username` |
