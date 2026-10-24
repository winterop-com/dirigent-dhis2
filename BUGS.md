# Bugs found while testing dirigent-dhis2

Bugs in the systems dirigent-dhis2 is built on -- dhis2w and DHIS2 itself -- and what they lack,
found by running the pack and its examples for real. Bugs in dirigent-dhis2 itself are fixed in
the same session and are not listed. Each entry names where it was seen, what happens, and what
would fix it. A bug that is fixed leaves the file.

## DHIS2

### 2.42.7: an export outside the account's scope answers 200 with an empty body

- Seen: `stable-2-42-7` (2.42.7), 2026-10-23, as `admin`, whose org units there are two districts
  (`P1HohXRfAkY`, `YuQRtpLP10I`) rather than the root.
- `GET /api/dataValueSets.json?dataSet=pBOMPrpg1QX&period=202507&orgUnit=ImspTQPwCqd&children=true`
  answers 200 with zero bytes. The same request as `system` answers the 16 values. An export
  that finds nothing in scope answers `{"dataSet": ..., "dataValues": []}`, so the empty body is
  the refusal, unannounced. The tracker endpoints answer the same situation with 403
  `Organisation unit is not part of your search scope`.
- Not tried on 2.43.2, where `admin` holds the root.
- Fix: answer 409 or 403 naming the org unit, as tracker does.

### 2.43.2: a conflict no longer names what it refused

- Seen: `stable-2-43-2` (2.43.2), 2026-10-23, importing a non-integer value for `s46m5MS0hxu`.
- 2.42.7 answers the conflict with `object: s46m5MS0hxu`, `property: value` and
  `objects: {dataElement, value}`. 2.43.2 answers it with no `object` and no `property`, and
  `objects: {args: "1-not-a-number-INTEGER-value_not_integer"}`; only `indexes` and `errorCode`
  (now `E8122`, was `E7619`) say which value it was.
- dirigent-dhis2 now carries `error_code` and `indexes` and names an unnamed conflict by
  position.
- Fix: keep `object` (the data element) and `property` in the conflict, as 2.42 does.

### 2.43.2: one data element outside the data set refuses the whole import, whatever atomicMode

- Seen: `stable-2-43-2` (2.43.2), 2026-10-23, dry runs into `BfMAe6Itzgt` with one good value
  and one naming `aaaaaaaaaaa`.
- 2.42.7 takes the good value and reports the other as a conflict (`WARNING`, updated 1,
  ignored 1) under both `atomicMode=ALL` and `NONE`. 2.43.2 answers `ERROR` with nothing taken
  under both: `Data set BfMAe6Itzgt not usable with data element(s): [aaaaaaaaaaa]`. A value of
  the wrong type is still a per-row conflict on 2.43.2, so only this check refuses wholesale.
- Fix: under `atomicMode=NONE`, report the data element as a conflict and take the other rows,
  as 2.42 does.

### 2.43.2: import counts no longer add up to what was sent

- Seen: `stable-2-43-2` (2.43.2), 2026-10-23.
- A dry run of one value identical to the stored one answers `imported 0, updated 0, ignored 0`;
  2.42.7 answers `ignored 1`. A dry run of two values, the first stored with a different value
  and the second not stored at all, answers `updated 2, imported 0`; 2.42.7 answers
  `updated 1, imported 1`. A reader can no longer tell from the counts what a real import would
  create, revise or leave alone.
- Fix: count an unchanged value as ignored and a value a dry run would create as imported, as
  2.42 does.

## The play demos

### stable-2-42-7: admin is not assigned to the root org unit

- Seen: `stable-2-42-7`, 2026-10-23, after the instance was rebuilt that night.
- `admin` holds `P1HohXRfAkY` and `YuQRtpLP10I`, with no data view or search org units; on
  `stable-2-43-2` it holds `ImspTQPwCqd`, Sierra Leone. Every example reading from the root as
  `admin` gets nothing back from a data value set export and 403 from the tracker endpoints on
  2.42.7. `system` / `System123` reaches the root on both.
- Fix: assign `admin` to the root on the 2.42 demo, as on 2.43.
