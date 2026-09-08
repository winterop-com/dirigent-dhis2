# The DHIS2 formats

The pack contributes two JSON Schema formats. In JSON Schema `format` is an annotation that
asserts nothing on its own; dirigent's engine always hands its validator a checker, so a
`format` written in a schema this instance holds is enforced. Every format an installed pack
contributes joins the engine's own in that checker.

| Format | A string that is | Examples |
| --- | --- | --- |
| `dhis2-uid` | a DHIS2 UID: one letter, then ten alphanumerics | `ImspTQPwCqd`, `BfMAe6Itzgt` |
| `dhis2-period` | a DHIS2 ISO period of one of the common types | `2026`, `202601`, `20260115`, `2026Q1`, `2026W03` |

A format only ever narrows a `string`: a value of the wrong type is caught by `type`, and the
checker speaks only once the value is already a string.

## `dhis2-uid`

Eleven characters: `[A-Za-z][A-Za-z0-9]{10}`, matched whole. `ImspTQPwCqd` passes; a
ten-character string, a leading digit, and a UID with a hyphen in it are all refused.

## `dhis2-period`

The common DHIS2 ISO period types, matched whole:

| Type | Shape | Example |
| --- | --- | --- |
| Yearly | `YYYY` | `2026` |
| Monthly | `YYYYMM` | `202601` |
| Daily | `YYYYMMDD` | `20260115` |
| Quarterly | `YYYYQn` | `2026Q1` |
| Weekly | `YYYYWnn` | `2026W03` |

The month, day, quarter and week numbers are bounded, so `202613` and `2026Q5` are refused.

The rarer period types are not covered: bi-monthly (`YYYYMMB`), six-monthly (`YYYYSn`), and the
financial-year variants (`YYYYApril`, `YYYYJuly`, `YYYYOct`). A schema that has to accept one
of those uses `pattern` rather than this format.

## Using one in a schema

Write the format beside the type, the way any other format is written:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "dhis2-data-value-set",
  "title": "DHIS2 data value set",
  "type": "object",
  "required": ["dataValues"],
  "properties": {
    "dataSet": { "type": "string", "format": "dhis2-uid" },
    "period": { "type": "string", "format": "dhis2-period" },
    "orgUnit": { "type": "string", "format": "dhis2-uid" },
    "dataValues": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["dataElement", "value"],
        "properties": {
          "dataElement": { "type": "string", "format": "dhis2-uid" },
          "period": { "type": "string", "format": "dhis2-period" },
          "value": { "type": "string" }
        }
      }
    }
  }
}
```

That schema is [`examples/schemas/dhis2-data-value-set.json`](examples.md#schemas). Apply it on
its own, then gate a step on it by code:

```bash
dg schema create examples/schemas/dhis2-data-value-set.json
```

```yaml
steps:
  check:
    block: validate.schema
    config:
      schema: dhis2-data-value-set
      value: "{{ steps.export.json_body }}"
```

A schema is also what a pipeline's parameters are declared with, so a parameter written
`format: dhis2-uid` refuses a bad org unit when the run is submitted rather than when the call
is made.

## Portability

A format no installed pack contributes stays a passing annotation: the value is valid, just
unchecked. So the same schema asserts on an instance that has this pack and passes on one that
does not, and a schema written against DHIS2 is not a schema only a DHIS2 instance can hold.
