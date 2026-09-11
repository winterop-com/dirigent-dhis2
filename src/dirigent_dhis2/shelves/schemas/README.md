# Example schemas

Each file here is a plain JSON Schema (Draft 2020-12): the shape a read is expected to return,
written down once so a pipeline can be refused the moment a payload moves out from under it. A
schema is **locally authored** -- a picture you hold of the payload, never something fetched or
introspected from the source. That is why these live on their own and are applied on their own,
not inside a pipeline document.

Apply one the way a person would:

```bash
dg schema create examples/schemas/dhis2-org-units.json
```

A schema carries its own identity in its keywords, so there is nothing else to pass:

- `$id` becomes the `code` the schema is addressed by (falling back to the file's stem).
- `title` becomes its name.
- `description` becomes its body.

| File | The shape it pins |
| --- | --- |
| [dhis2-org-units.json](dhis2-org-units.json) | An object with an `organisationUnits` array of UID/name/level items |
| [dhis2-data-elements.json](dhis2-data-elements.json) | A `dataElements` array whose `valueType` and `domainType` are held to the DHIS2 enums |
| [dhis2-system-info.json](dhis2-system-info.json) | A top-level object, not a list: an instance `version` and a `serverDate` |
| [dhis2-number-data-elements.json](dhis2-number-data-elements.json) | A `dataElements` array whose every `valueType` is `NUMBER` |
| [dhis2-data-elements-v42.json](dhis2-data-elements-v42.json) | The v42-pinned `dataElements` shape: the 2.42 `valueType` enum and closed rows, so a 2.43 bump is caught |
| [dhis2-data-value-set.json](dhis2-data-value-set.json) | The `/api/dataValueSets` envelope, every id held to `dhis2-uid` and every period to `dhis2-period` |

These pin the reads the DHIS2 series makes: the `fields=` metadata reads the
[`../validate/`](../validate) documents gate on, and the data value set that
[`../dhis2-compose/dhis2-export-validated.yaml`](../dhis2-compose/dhis2-export-validated.yaml)
gates on.
