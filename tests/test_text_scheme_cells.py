"""Unnamed text cells of a system scheme (InfoOnlyText / TextState named "-").

A parking reservation scheme in a real installation places ~50 text cells
called "-" on its image. They become sensors named after the scheme and
their position, start disabled and live on the scheme's device.
"""

from __future__ import annotations

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from _controls import control, entity_id, state, structure_with
from custom_components.loxone.controls.info import has_meaningful_name

NAMED_TEXT = control("InfoOnlyText", "Free Places", states=("text",), details={"format": "%s"})
NAMED_STATE = control("TextState", "Heating Status", states=("textAndIcon", "iconAndColor"))
CELL_TEXT = control("InfoOnlyText", "-", states=("text",), details={"format": "%s"}, uuidAction="cell-text-0001")
CELL_STATE = control("TextState", " - ", states=("textAndIcon", "iconAndColor"), uuidAction="cell-state-0002")
ORPHAN = control("InfoOnlyText", "-", states=("text",), uuidAction="0rphan00-0000-0000-ffff000000000003")
PARKING = control(
    "SystemScheme",
    "Parking Reservations",
    details={
        "mainControl": NAMED_TEXT["uuidAction"],
        "controlReferences": [
            {"uuidAction": NAMED_TEXT["uuidAction"], "pos": {"x": 0, "y": 0}},
            {"uuidAction": CELL_TEXT["uuidAction"], "pos": {"x": 1, "y": 0}},
            {"uuidAction": CELL_STATE["uuidAction"], "pos": {"x": 2, "y": 0}},
        ],
    },
)


@pytest.fixture
def loxapp3(loxapp3):
    return structure_with(loxapp3, NAMED_TEXT, NAMED_STATE, CELL_TEXT, CELL_STATE, ORPHAN, PARKING)


@pytest.fixture
async def setup(hass, mock_connection, mock_entry, setup_loxone_entry):
    await setup_loxone_entry(mock_entry)
    return mock_connection


@pytest.mark.parametrize(("name", "expected"), [("-", False), (" - ", False), ("", False), ("A", True), ("98", True)])
def test_has_meaningful_name(name, expected):
    assert has_meaningful_name(name) is expected


async def test_named_text_sensors_are_unchanged(hass, setup):
    registry = er.async_get(hass)
    for item in (NAMED_TEXT, NAMED_STATE):
        entry = registry.async_get(entity_id(hass, "sensor", item["uuidAction"]))
        assert entry.original_name == item["name"]
        assert entry.disabled_by is None
    setup.feed(state(NAMED_STATE, "textAndIcon"), "Heating active")
    await hass.async_block_till_done()
    current = hass.states.get(entity_id(hass, "sensor", NAMED_STATE["uuidAction"]))
    assert current.state == "Heating active"
    assert "original_name" not in current.attributes


async def test_unnamed_scheme_cells(hass, setup):
    registry = er.async_get(hass)
    devices = dr.async_get(hass)
    scheme_device = registry.async_get(entity_id(hass, "sensor", PARKING["uuidAction"])).device_id

    text = registry.async_get(entity_id(hass, "sensor", CELL_TEXT["uuidAction"]))
    status = registry.async_get(entity_id(hass, "sensor", CELL_STATE["uuidAction"]))
    assert text.original_name == "Parking Reservations 2"
    assert status.original_name == "Parking Reservations 3"
    assert text.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert status.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert text.device_id == status.device_id == scheme_device
    assert devices.async_get(scheme_device).suggested_area == "Kitchen"

    scheme = hass.states.get(entity_id(hass, "sensor", PARKING["uuidAction"]))
    assert scheme.attributes["controls"] == ["Free Places", "Parking Reservations 2", "Parking Reservations 3"]


async def test_enabled_scheme_cell_keeps_its_values(hass, setup, mock_entry):
    registry = er.async_get(hass)
    cell = entity_id(hass, "sensor", CELL_TEXT["uuidAction"])
    registry.async_update_entity(cell, disabled_by=None)
    await hass.config_entries.async_reload(mock_entry.entry_id)
    await hass.async_block_till_done()

    setup.feed(state(CELL_TEXT, "text"), "ABC 1234")
    await hass.async_block_till_done()
    current = hass.states.get(cell)
    assert current.state == "ABC 1234"
    assert current.attributes["original_name"] == "-"
    assert current.attributes["system_scheme"] == "Parking Reservations"
    assert current.attributes["scheme_position"] == 2


async def test_unnamed_text_without_scheme(hass, setup):
    orphan = er.async_get(hass).async_get(entity_id(hass, "sensor", ORPHAN["uuidAction"]))
    assert orphan.original_name == "InfoOnlyText 0rphan00"
    assert orphan.disabled_by is er.RegistryEntryDisabler.INTEGRATION
