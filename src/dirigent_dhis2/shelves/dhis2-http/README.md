# DHIS2 examples: the generic-HTTP way

These pipelines talk to DHIS2 with dirigent's ordinary `http.request` and `http.ready`
blocks -- no adapter, no `dhis2.*` block, nothing to install. This is the pattern for
reaching any system that has no adapter, or for a DHIS2 call the native pack does not yet
cover: the document names the endpoint, the query and the shape it wants, and composes the
rest. The native adapter and its growing family live beside this in [`../dhis2/`](../dhis2), and
the documents that put an adapter block next to one of the engine's own live in
[`../dhis2-compose/`](../dhis2-compose).

No document carries a credential. Each names the connections it uses under
`requires.connections`, and the instance holds them: `dhis2-play-http`, an `http` connection to
the public demo, which `dg connection create` makes once and asks how to sign in for:

```bash
dg connection create http dhis2-play-http --set base_url=https://play.dhis2.org/2.43 \
    --set follow_redirects_with_auth=true --set timeout=2m
dg run examples/dhis2-http/dhis2-system-info.yaml
```

The demo takes the login it publishes on its own sign-in page. Create the same code against
your own DHIS2, or rename it in a copy, and the documents read yours instead.

## The write target

The six documents that build a write send it to the **playground**, a request-and-response
service every dirigent instance serves itself under `/api/v1/playground`, unauthenticated. It
answers with the request it received, so the receipt a document reads back is its own payload
under `.request.body` -- once, whatever the method.

Five of them name a connection for it, because the connection is what a reader repoints at
their own DHIS2. `dhis2-forward-org-units.yaml` takes a parameter instead: the playground
needs no credential, and there is nothing for a connection to hold.

Those connections are created the same way, on the instance that serves the playground, and
each document's top-of-file comment gives the command:

```bash
dg dev &
dg connection create http receiver --set base_url=http://127.0.0.1:3333/api/v1/playground
dg run examples/dhis2-http/dhis2-sync-org-units.yaml
```

`dhis2-fhir-to-data-values.yaml` needs only the playground: its capture is inline, so it reaches
no DHIS2 at all, and it carries its credential-free connection so a `dg run --local` runs it
against a `dg dev` beside it. The other five read the play demo as well.

## The demo redirect

`https://play.dhis2.org/2.43` names the newest 2.43 play demo: it answers with a redirect to
the versioned instance on another host, `https://play.im.dhis2.org/stable-2-43-2` at the time
of writing, and moves when DHIS2 publishes the next patch.

A client drops the credential when a redirect changes host, so each connection here sets
`follow_redirects_with_auth: true`. The connection follows `base_url`'s redirect once, without
the credential, and sends every request to where it landed, credential and method intact, so
the pipelines follow the demo as it moves.

## Pipelines

| File | What it demonstrates |
| --- | --- |
| [dhis2-system-info.yaml](dhis2-system-info.yaml) | Authentication and a minimal API call. |
| [dhis2-org-unit-levels.yaml](dhis2-org-unit-levels.yaml) | The configured hierarchy levels. |
| [dhis2-org-units.yaml](dhis2-org-units.yaml) | Save a snapshot of every DHIS2 organisation unit to storage. |
| [dhis2-org-unit-detail.yaml](dhis2-org-unit-detail.yaml) | Read one organisation unit, its hierarchy path, and its immediate children. |
| [dhis2-forward-org-units.yaml](dhis2-forward-org-units.yaml) | Select, reshape with `transform.jq`, and send an organisation-unit batch to the playground -- nothing on the allowlist. |
| [dhis2-run-analytics.yaml](dhis2-run-analytics.yaml) | Start an analytics-table update and poll the asynchronous DHIS2 task with `http.ready` -- what the native `dhis2.analytics_run` does for you. |
| [dhis2-sync-org-units.yaml](dhis2-sync-org-units.yaml) | An organisation-unit sync: count before fetching, bound the read, ask for fields, order by `path`. |
| [dhis2-export-data-elements.yaml](dhis2-export-data-elements.yaml) | A metadata export with `fields=:owner`, and the import vocabulary -- `importStrategy`, `atomicMode`, `importMode=VALIDATE`. |
| [dhis2-fhir-to-data-values.yaml](dhis2-fhir-to-data-values.yaml) | A FHIR `QuestionnaireResponse` translated into a `/api/dataValueSets` import, link id by link id. |
| [dhis2-export-data-values-csv.yaml](dhis2-export-data-values-csv.yaml) | A data value set as CSV rather than JSON -- the extension is the content negotiation -- written out with `storage.write`. |
| [dhis2-data-values-validated.yaml](dhis2-data-values-validated.yaml) | A data value set fetched and validated against the pack's `dhis2-uid` and `dhis2-period` formats. |
| [dhis2-export-data-values-range.yaml](dhis2-export-data-values-range.yaml) | Every period inside a `startDate`/`endDate` window in one call, instead of a period at a time. |
| [dhis2-mark-data-set-complete.yaml](dhis2-mark-data-set-complete.yaml) | Reading a completion registration, and the POST that signs a period off. |
| [dhis2-mark-data-set-incomplete.yaml](dhis2-mark-data-set-incomplete.yaml) | Both ways of reopening a signed-off period: `completed: false`, and the outright DELETE. |
| [dhis2-events-by-stage.yaml](dhis2-events-by-stage.yaml) | Events of a single program stage in an occurrence window, and the `orgUnitMode`/`ouMode` split. |

The metadata, export and tracker examples only read DHIS2; the forwarding, sync, metadata
export, FHIR and completeness examples write solely to the playground. That is the rule for
this directory: the play demo is shared, so nothing here practises an import against it.
Every document that builds a write builds the real request, correctly parameterised, and
posts it at a receiver that cannot act on it -- repoint its target and the same document
performs the real thing.

`dhis2-export-data-elements.yaml` marks the sharpest trap in the DHIS2 API: a dry run is
`importMode=VALIDATE` on `/api/metadata` and `dryRun=true` on `/api/dataValueSets`, and
reaching for the wrong spelling does not fail -- it imports.
