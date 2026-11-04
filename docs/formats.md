# The DHIS2 formats

The pack contributes three JSON Schema formats. In JSON Schema `format` is an annotation that
asserts nothing on its own; dirigent's engine always hands its validator a checker, so a
`format` written in a schema this instance holds is enforced. Every format an installed pack
contributes joins the engine's own in that checker.

| Format | A string that is | Examples |
| --- | --- | --- |
| `dhis2-uid` | a DHIS2 UID: one letter, then ten alphanumerics | `ImspTQPwCqd`, `BfMAe6Itzgt` |
| `dhis2-period` | a DHIS2 ISO period of any period type | `2026`, `202601`, `2026Q1`, `2026S1`, `2026BiW4` |
| `dhis2-code` | a DHIS2 code: one to fifty characters, not padded, on one line | `DE_359596`, `OU_222702`, `ANC 1st visit` |

A format only ever narrows a `string`: a value of the wrong type is caught by `type`, and the
checker speaks only once the value is already a string. So a field written
`{"type": ["string", "null"], "format": "dhis2-uid"}` admits `null` and holds every string to
the format, the way the draft's own formats behave.

## `dhis2-uid`

Eleven characters: `[A-Za-z][A-Za-z0-9]{10}`, matched whole. `ImspTQPwCqd` passes; a
ten-character string, a leading digit, and a UID with a hyphen in it are all refused.

## `dhis2-period`

Every DHIS2 ISO period type, matched whole:

| Type | Shape | Example |
| --- | --- | --- |
| Yearly | `YYYY` | `2026` |
| Financial year | `YYYYFeb`, `YYYYApril`, `YYYYJuly`, `YYYYAug`, `YYYYSep`, `YYYYOct`, `YYYYNov` | `2026April` |
| Six-monthly | `YYYYSn`, `YYYYAprilSn`, `YYYYNovSn` | `2026S1`, `2026AprilS2` |
| Quarterly | `YYYYQn`, `YYYYNovQn` | `2026Q1`, `2026NovQ2` |
| Bi-monthly | `YYYYMMB`, months 01 to 06 | `202603B` |
| Monthly | `YYYYMM` | `202601` |
| Bi-weekly | `YYYYBiWn`, 1 to 27 | `2026BiW4` |
| Weekly | `YYYYWn`, `YYYYWedWn`, `YYYYThuWn`, `YYYYSatWn`, `YYYYSunWn` | `2026W3`, `2026WedW03` |
| Daily | `YYYYMMDD` | `20260115` |

Week and bi-week numbers are zero-padded or not. The month, day, quarter, half and week numbers
are bounded, so `202613`, `2026Q5`, `2026S3` and `2026BiW28` are refused.

## `dhis2-code`

The `code` property every identifiable object in DHIS2 carries, and the key `idScheme=CODE`
addresses it by. DHIS2 caps a code at fifty characters and puts no character class on it, so
neither does this format: one to fifty characters, with no whitespace at either end and no
line break, matched whole. `DE_359596`, `OU-222702` and `ANC 1st visit` all pass; an empty
string, a padded ` DE_359596 `, and a fifty-one-character string are refused.

An instance that keeps its codes to a house convention, say upper-case letters, digits and
underscores, writes that as a `pattern` beside the format. The format holds what DHIS2
itself holds; the convention is the schema author's.

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
      input: ${steps.export.output.body}
```

A schema is also what a pipeline's parameters are declared with, so a parameter written
`format: dhis2-uid` refuses a bad org unit when the run is submitted rather than when the call
is made.

## Portability

A format no installed pack contributes stays a passing annotation: the value is valid, just
unchecked. So the same schema asserts on an instance that has this pack and passes on one that
does not, and a schema written against DHIS2 is not a schema only a DHIS2 instance can hold.
