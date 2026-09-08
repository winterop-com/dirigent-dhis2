"""Tests for the DHIS2 pack's plugin wiring."""

from pluginkit import PluginManager

from dirigent_common import API_VERSION
from dirigent_dhis2 import Dhis2Plugin, plugin
from dirigent_plugin import ENTRY_POINT_GROUP, PROJECT_NAME, contribute, markers

DHIS2_BLOCKS = [
    "dhis2.analytics_query",
    "dhis2.analytics_run",
    "dhis2.data_set_complete",
    "dhis2.data_value_set_export",
    "dhis2.data_value_set_import",
    "dhis2.metadata",
    "dhis2.tracker",
]


def test_the_pack_contributes_the_dhis2_blocks() -> None:
    contribution = Dhis2Plugin().contribute()
    assert contribution.api_version == API_VERSION
    assert sorted(contribution.block_ids()) == DHIS2_BLOCKS
    assert [connection.id for connection in contribution.connection_kinds] == ["dhis2"]
    assert sorted(contribution.formats) == ["dhis2-period", "dhis2-uid"]
    assert contribution.notifiers == []
    assert contribution.storage_backends == []


def test_every_dhis2_block_shelves_under_the_dhis2_group() -> None:
    contribution = Dhis2Plugin().contribute()
    groups = {operator.spec.id: operator.spec.group for operator in contribution.operators}
    groups.update({sensor.spec.id: sensor.spec.group for sensor in contribution.sensors})
    assert groups == {block_id: "dhis2" for block_id in DHIS2_BLOCKS}


def test_no_dhis2_block_declares_itself_unsafe() -> None:
    contribution = Dhis2Plugin().contribute()
    assert [operator.spec.id for operator in contribution.operators if operator.spec.local_execution] == []


def test_the_pack_registers_through_a_plugin_manager() -> None:
    manager = PluginManager(PROJECT_NAME)
    manager.add_extension_points(markers)
    manager.register(plugin, name="dhis2")
    collected = [sorted(contribution.block_ids()) for contribution in manager.caller(contribute)()]
    assert collected == [DHIS2_BLOCKS]


def test_the_pack_is_discovered_through_the_entry_point_group() -> None:
    manager = PluginManager(PROJECT_NAME)
    manager.add_extension_points(markers)
    registered = manager.load_entrypoints(ENTRY_POINT_GROUP)
    assert registered >= 1
    assert manager.get_plugin("dhis2") is not None
