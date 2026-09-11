# Starters: what a real DHIS2 pipeline begins as

Every other shelf in this pack carries the connection it uses, so each document runs
standalone with `dg run --local`. This shelf is the other half: the same flows written the
way an instance accepts them, naming a `dhis2` connection instead of embedding one. A server
refuses a document that carries a connection, so these are the ones `dg pipeline new` copies
into a project.

Every document here is tagged `starter`, and the tag is what qualifies it: a multi-step flow
against a real instance, carrying no `connections:` and no `schemas:` and failing by nothing
by design. `dg examples list --plugin dhis2 --starter` is the menu.

Create the connection first, then copy:

```bash
dg connection create dhis2 --kind dhis2 \
  --config base_url=https://dhis2.example.org \
  --config basic_username=admin --config basic_password='...'
dg pipeline new dhis2-export-and-import
```

Each ends with a TO MAKE IT YOURS paragraph naming the edits a real instance needs: the uids
are the play demo's and almost certainly not yours.

| File | What it starts you with |
| --- | --- |
| [dhis2-export-and-import.yaml](dhis2-export-and-import.yaml) | The round trip: read a data value set and hand it to an import, rehearsed with `dry_run`. |
| [dhis2-export-through-storage.yaml](dhis2-export-through-storage.yaml) | The same move with the file kept: export, write, read back, import, four hops. |
| [dhis2-export-gated-on-a-schema.yaml](dhis2-export-gated-on-a-schema.yaml) | An export held to a named schema, so a changed payload stops at the step it arrived in. |
| [dhis2-export-reshaped-to-totals.yaml](dhis2-export-reshaped-to-totals.yaml) | An export reshaped with `transform.jq` into the shape the next system reads. |
| [dhis2-rebuild-then-report.yaml](dhis2-rebuild-then-report.yaml) | The analytics ordering: rebuild the tables, then read an indicator out of them. |
| [dhis2-signed-off-then-export.yaml](dhis2-signed-off-then-export.yaml) | A sensor gate: hold until a month is marked complete, then read it. |
| [dhis2-metadata-snapshot-to-storage.yaml](dhis2-metadata-snapshot-to-storage.yaml) | A metadata collection read with a fields projection and written to storage. |
