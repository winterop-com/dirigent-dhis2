"""Tests for the data value set blocks' forms other than JSON, and the id schemes an import takes."""

import json as jsonlib

import httpx2
import pytest
from pydantic import ValidationError

from dhis2server import BASE_URL, CONNECTION, Dhis2Server, json, serve, summary
from dirigent_dhis2.export import Dhis2DataValueSetExportOperator, Dhis2DataValueSetExportOutput
from dirigent_dhis2.imports import Dhis2DataValueSetImportConfig, Dhis2DataValueSetImportOperator
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext, call_block

IMPORT = f"{BASE_URL}/api/dataValueSets"
SELECTION = {"connection": CONNECTION, "data_set": "pBOMPrpg1QX", "period": "2026Q1", "org_unit": "ImspTQPwCqd"}

CSV = (
    "dataelement,period,orgunit,categoryoptioncombo,attributeoptioncombo,value\n"
    "pikOziyCXbM,202507,DiszpKrYNg8,hEFKSsPV5et,HllvX50cXC0,23\n"
    "pikOziyCXbM,202507,DiszpKrYNg8,V6L425pT3A0,HllvX50cXC0,9\n"
)
XML = (
    '<dataValueSet xmlns="http://dhis2.org/schema/dxf/2.0" dataSet="BfMAe6Itzgt" '
    'completeDate="2010-08-06T00:00:00.000+0000" period="202507" orgUnit="DiszpKrYNg8">'
    '<dataValue dataElement="UOlfIjgN8X6" value="23"/><dataValue dataElement="pikOziyCXbM" value="9"/>'
    "</dataValueSet>"
)
ADX = (
    '<adx xmlns="urn:ihe:qrph:adx:2015"><group dataSet="DS_359711" period="2025-07-01/P1M" orgUnit="OU_559">'
    '<dataValue dataElement="DE_19" value="23"/></group></adx>'
)


def text(status: int, body: str, content_type: str) -> httpx2.Response:
    return httpx2.Response(status, content=body.encode(), headers={"Content-Type": content_type})


@pytest.mark.parametrize(
    ("form", "path", "accept"),
    [
        ("csv", "/api/dataValueSets.csv", "application/csv"),
        ("xml", "/api/dataValueSets.xml", "application/xml"),
        ("adx", "/api/dataValueSets", "application/adx+xml"),
    ],
)
async def test_a_text_export_lands_in_storage_and_inlines_its_head(
    ctx: FakeContext, dhis2: Dhis2Server, form: str, path: str, accept: str
) -> None:
    route = dhis2.get(f"{BASE_URL}{path}").answers(text(200, CSV, accept))
    output = await call_block(
        Dhis2DataValueSetExportOperator(), {**SELECTION, "format": form, "data_element_id_scheme": "CODE"}, ctx
    )
    assert isinstance(output, Dhis2DataValueSetExportOutput)
    assert output.format == form
    assert output.body is None
    assert output.text == CSV
    assert output.content_bytes == len(CSV)
    assert output.truncated is False
    assert output.uri is not None
    assert ctx.storage.path_for(output.uri).read_text() == CSV
    request = route.last
    assert request.headers["Accept"] == accept
    assert request.url.params["dataSet"] == "pBOMPrpg1QX"
    assert request.url.params["dataElementIdScheme"] == "CODE"


async def test_a_text_export_past_the_inline_size_is_cut_in_the_output_only(
    ctx: FakeContext, dhis2: Dhis2Server
) -> None:
    ctx.inline_capture = 20
    dhis2.get(f"{BASE_URL}/api/dataValueSets.csv").answers(text(200, CSV, "application/csv"))
    output = await call_block(Dhis2DataValueSetExportOperator(), {**SELECTION, "format": "csv"}, ctx)
    assert isinstance(output, Dhis2DataValueSetExportOutput)
    assert output.text == CSV[:20]
    assert output.truncated is True
    assert output.content_bytes == len(CSV)
    assert output.uri is not None
    assert ctx.storage.path_for(output.uri).read_text() == CSV


async def test_an_empty_text_export_is_the_scope_refusal(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(f"{BASE_URL}/api/dataValueSets.csv").answers(text(200, "", "application/csv"))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2DataValueSetExportOperator(), {**SELECTION, "format": "csv"}, ctx)
    assert refused.value.code == "dhis2.export.empty_answer"


async def test_an_adx_export_from_2_43_is_refused_before_it_is_asked(
    ctx: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = serve(monkeypatch, version="2.43.2")
    route = server.get(f"{BASE_URL}/api/dataValueSets").answers(json(200, {"dataValues": []}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2DataValueSetExportOperator(), {**SELECTION, "format": "adx"}, ctx)
    assert refused.value.code == "dhis2.export.format_unsupported"
    assert refused.value.error_class is ErrorClass.REJECTED
    assert route.requests == []


async def test_an_adx_export_answered_with_json_is_refused(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(f"{BASE_URL}/api/dataValueSets").answers(json(200, {"dataValues": []}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2DataValueSetExportOperator(), {**SELECTION, "format": "adx"}, ctx)
    assert refused.value.code == "dhis2.export.format_unsupported"


async def test_a_refused_text_export_is_classified_by_its_status(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    dhis2.get(f"{BASE_URL}/api/dataValueSets.xml").answers(json(503, {"message": "down"}))
    with pytest.raises(BlockFailure) as refused:
        await call_block(Dhis2DataValueSetExportOperator(), {**SELECTION, "format": "xml"}, ctx)
    assert refused.value.error_class is ErrorClass.TRANSIENT


@pytest.mark.parametrize(
    ("form", "document", "content_type", "sent"),
    [
        ("csv", CSV, "application/csv", 2),
        ("xml", XML, "application/xml", 2),
        ("adx", ADX, "application/adx+xml", 1),
    ],
)
async def test_a_text_import_is_sent_in_its_own_media_type(
    ctx: FakeContext, dhis2: Dhis2Server, form: str, document: str, content_type: str, sent: int
) -> None:
    route = dhis2.post(IMPORT).answers(json(200, summary("SUCCESS", imported=sent)))
    output = await call_block(
        Dhis2DataValueSetImportOperator(),
        {"connection": CONNECTION, "data_values": document, "format": form},
        ctx,
    )
    assert output.model_dump()["sent"] == sent
    request = route.last
    assert request.headers["Content-Type"] == content_type
    assert request.content.decode() == document


async def test_an_adx_import_is_read_by_code_unless_told_otherwise(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.post(IMPORT).answers(json(200, summary("SUCCESS", imported=1)))
    await call_block(
        Dhis2DataValueSetImportOperator(), {"connection": CONNECTION, "data_values": ADX, "format": "adx"}, ctx
    )
    assert route.last.url.params["idScheme"] == "CODE"
    await call_block(
        Dhis2DataValueSetImportOperator(),
        {"connection": CONNECTION, "data_values": ADX, "format": "adx", "id_scheme": "UID"},
        ctx,
    )
    assert route.last.url.params["idScheme"] == "UID"


async def test_every_id_scheme_rides_the_import_query(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.post(IMPORT).answers(json(200, summary("SUCCESS", imported=1)))
    await call_block(
        Dhis2DataValueSetImportOperator(),
        {
            "connection": CONNECTION,
            "data_values": {"dataValues": [{"dataElement": "DE_1", "value": "1"}]},
            "id_scheme": "CODE",
            "data_element_id_scheme": "NAME",
            "org_unit_id_scheme": "ATTRIBUTE:abcdefghijk",
            "category_option_combo_id_scheme": "UID",
        },
        ctx,
    )
    params = route.last.url.params
    assert params["idScheme"] == "CODE"
    assert params["dataElementIdScheme"] == "NAME"
    assert params["orgUnitIdScheme"] == "ATTRIBUTE:abcdefghijk"
    assert params["categoryOptionComboIdScheme"] == "UID"
    assert route.last.headers["Content-Type"] == "application/json"


def test_an_id_scheme_outside_dhis2s_spellings_is_refused() -> None:
    with pytest.raises(ValidationError):
        Dhis2DataValueSetImportConfig.model_validate(
            {"connection": CONNECTION, "data_values": {"dataValues": []}, "id_scheme": "code"}
        )


async def test_a_dry_run_of_xml_leaves_the_completeness_claim_out(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.post(IMPORT).answers(json(200, summary("SUCCESS", imported=2)))
    await call_block(
        Dhis2DataValueSetImportOperator(),
        {"connection": CONNECTION, "data_values": XML, "format": "xml", "dry_run": True},
        ctx,
    )
    sent = route.last.content.decode()
    assert "completeDate" not in sent
    assert 'dataSet="BfMAe6Itzgt"' in sent
    assert route.last.url.params["dryRun"] == "true"


async def test_a_real_xml_import_sends_the_document_whole(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.post(IMPORT).answers(json(200, summary("SUCCESS", imported=2)))
    await call_block(
        Dhis2DataValueSetImportOperator(), {"connection": CONNECTION, "data_values": XML, "format": "xml"}, ctx
    )
    assert route.last.content.decode() == XML


async def test_a_text_import_given_an_object_is_refused_before_it_is_sent(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    route = dhis2.post(IMPORT).answers(json(200, summary("SUCCESS")))
    with pytest.raises(BlockFailure) as refused:
        await call_block(
            Dhis2DataValueSetImportOperator(),
            {"connection": CONNECTION, "data_values": {"dataValues": []}, "format": "csv"},
            ctx,
        )
    assert refused.value.code == "dhis2.import.not_text"
    assert route.requests == []


async def test_an_import_reads_its_document_from_storage(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    async with ctx.storage.open_write("file://scratch/values.csv") as sink:
        await sink.write(CSV.encode())
    route = dhis2.post(IMPORT).answers(json(200, summary("SUCCESS", imported=2)))
    output = await call_block(
        Dhis2DataValueSetImportOperator(),
        {"connection": CONNECTION, "data_values_uri": "file://scratch/values.csv", "format": "csv"},
        ctx,
    )
    assert output.model_dump()["sent"] == 2
    assert route.last.content.decode() == CSV


async def test_a_json_document_from_storage_is_parsed_and_counted(ctx: FakeContext, dhis2: Dhis2Server) -> None:
    document = {"dataValues": [{"dataElement": "de1", "value": "7"}], "completeDate": "2026-01-01"}
    async with ctx.storage.open_write("file://scratch/values.json") as sink:
        await sink.write(jsonlib.dumps(document).encode())
    route = dhis2.post(IMPORT).answers(json(200, summary("SUCCESS", imported=1)))
    output = await call_block(
        Dhis2DataValueSetImportOperator(),
        {"connection": CONNECTION, "data_values_uri": "file://scratch/values.json", "dry_run": True},
        ctx,
    )
    assert output.model_dump()["sent"] == 1
    assert "completeDate" not in jsonlib.loads(route.last.content)


def test_an_import_naming_its_document_twice_is_refused() -> None:
    with pytest.raises(ValidationError, match="each name the document"):
        Dhis2DataValueSetImportConfig.model_validate(
            {"connection": CONNECTION, "data_values": {"dataValues": []}, "data_values_uri": "file://x.json"}
        )
