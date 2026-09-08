# DHIS2 examples: the generic-HTTP way

These pipelines talk to DHIS2 with dirigent's ordinary `http.request` and `http.ready`
blocks -- no adapter, no `dhis2.*` block, nothing to install. This is the pattern for
reaching any system that has no adapter, or for a DHIS2 call the native pack does not yet
cover: the document names the endpoint, the query and the shape it wants, and composes the
rest. The native adapter and its growing family live beside this in [`../dhis2/`](../dhis2), and
the documents that put an adapter block next to one of the engine's own live in
[`../dhis2-compose/`](../dhis2-compose).

Each document carries the connection it uses, in a `connections:` block beside its steps, so
it runs on its own with nothing to set up first:

```bash
dg run --local examples/dhis2-http/dhis2-system-info.yaml
```

Carrying a connection is for a document that has to run standalone; an instance you own names
its connections instead, and a server refuses to apply a document that embeds one.
`--connections FILE` replaces a carried connection by code, so these point at your own DHIS2
without editing them.

## The demo redirect

`https://play.dhis2.org/demo` is a stable alias. It responds with a redirect to a versioned
instance on another host; on 30 August 2026 that target was
`https://play.im.dhis2.org/stable-2-43-1`.

Because the redirect crosses hosts, an HTTP client must not forward Basic Auth automatically.
Dirigent follows a redirect only when a step sets `follow_redirects: true`, and its client
drops credentials when the origin changes. The connection therefore names the resolved
versioned instance directly. When DHIS2 moves the stable demo, resolve the alias again and
update `base_url` in each pipeline's `connections:` block:

```bash
curl -sSI https://play.dhis2.org/demo
```

## Pipelines

| File | What it demonstrates |
| --- | --- |
| [dhis2-system-info.yaml](dhis2-system-info.yaml) | Authentication and a minimal API call. |
| [dhis2-org-unit-levels.yaml](dhis2-org-unit-levels.yaml) | The configured hierarchy levels. |
| [dhis2-org-units.yaml](dhis2-org-units.yaml) | A compact snapshot of every organisation unit, saved as an artifact. |
| [dhis2-org-unit-detail.yaml](dhis2-org-unit-detail.yaml) | One parameterized organisation unit and its children. |
| [dhis2-forward-org-units.yaml](dhis2-forward-org-units.yaml) | Select, reshape with `transform.jq`, and send an organisation-unit batch to Postman Echo -- nothing on the allowlist. |
| [dhis2-run-analytics.yaml](dhis2-run-analytics.yaml) | Start an analytics-table update and poll the asynchronous DHIS2 task with `http.ready` -- what the native `dhis2.analytics_run` does for you. |
| [dhis2-sync-org-units.yaml](dhis2-sync-org-units.yaml) | An organisation-unit sync: count before fetching, bound the read, ask for fields, order by `path`. |
| [dhis2-export-data-elements.yaml](dhis2-export-data-elements.yaml) | A metadata export with `fields=:owner`, and the import vocabulary -- `importStrategy`, `atomicMode`, `importMode=VALIDATE`. |
| [dhis2-fhir-to-data-values.yaml](dhis2-fhir-to-data-values.yaml) | A FHIR `QuestionnaireResponse` translated into a `/api/dataValueSets` import, link id by link id. |
| [dhis2-export-data-values-csv.yaml](dhis2-export-data-values-csv.yaml) | A data value set as CSV rather than JSON -- the extension is the content negotiation -- streamed to storage. |
| [dhis2-data-values-validated.yaml](dhis2-data-values-validated.yaml) | A data value set fetched and validated against the pack's `dhis2-uid` and `dhis2-period` formats. |
| [dhis2-export-data-values-range.yaml](dhis2-export-data-values-range.yaml) | Every period inside a `startDate`/`endDate` window in one call, instead of a period at a time. |
| [dhis2-mark-data-set-complete.yaml](dhis2-mark-data-set-complete.yaml) | Reading a completion registration, and the POST that signs a period off. |
| [dhis2-mark-data-set-incomplete.yaml](dhis2-mark-data-set-incomplete.yaml) | Both ways of reopening a signed-off period: `completed: false`, and the outright DELETE. |
| [dhis2-events-by-stage.yaml](dhis2-events-by-stage.yaml) | Events of a single program stage in an occurrence window, and the `orgUnitMode`/`ouMode` split. |

The metadata, export and tracker examples only read DHIS2; the forwarding, sync, metadata
export, FHIR and completeness examples write solely to Postman Echo. That is the rule for this directory: the play demo is shared, so
nothing here practises an import against it. Every document that builds a write builds the
real request, correctly parameterised, and posts it somewhere harmless -- repoint its target
connection and the same document performs the real thing.

`dhis2-export-data-elements.yaml` marks the sharpest trap in the DHIS2 API: a dry run is
`importMode=VALIDATE` on `/api/metadata` and `dryRun=true` on `/api/dataValueSets`, and
reaching for the wrong spelling does not fail -- it imports.
