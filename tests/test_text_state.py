"""TextState ("Status" block) and InfoOnlyText as read-only text sensors (#529).

Shape per the Loxone structure file: ``textAndIcon`` is a text event with
the text, ``iconAndColor`` (since 13.1) a text state holding
``{"icon": "Icons/xxxx.svg", "color": "#45864A"}``. The fixture control
"Heating Status" (tests/fixtures/LoxAPP3.json) follows that shape; the
expected values below are literals, not derived from the code under test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.loxone.sensor import text_state_icon_and_color

FIXTURE = Path(__file__).parent / "fixtures" / "LoxAPP3.json"

STATUS_ACTION = "63746c3a-0200-96d7-ffff-f746578747374000200"
STATUS_TEXT = "36333734-0201-9336-ffff-d303230302d3000201"
STATUS_ICON_COLOR = "36333734-0202-9336-ffff-d303230302d3000202"

INFO_TEXT_ACTION = "63746c3a-01c0-96d7-ffff-f696e726f756000190"
INFO_TEXT_STATE = "36333734-01c1-9336-ffff-d303204b72d3000191"


@pytest.fixture
def loxapp3() -> dict:
    """The repository's own structure file; the harness file has no TextState."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _entity_id(hass, unique_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id("sensor", "loxone", unique_id)
    assert entity_id is not None, f"no sensor for {unique_id}"
    return entity_id


async def test_text_state_creates_read_only_sensor(hass, mock_connection, mock_entry, setup_loxone_entry):
    await setup_loxone_entry(mock_entry)

    registry = er.async_get(hass)
    entity_id = _entity_id(hass, STATUS_ACTION)
    device = dr.async_get(hass).async_get(registry.async_get(entity_id).device_id)
    assert device.name == "Heating Status"
    assert device.model == "TextState"
    # Read-only: no text entity for the Status block.
    assert registry.async_get_entity_id("text", "loxone", STATUS_ACTION) is None

    mock_connection.feed(STATUS_TEXT, "Heizen aktiv")
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state.state == "Heizen aktiv"
    assert state.attributes["device_type"] == "TextState"
    assert state.attributes["state_uuid"] == STATUS_TEXT


async def test_text_state_icon_and_color_attributes(hass, mock_connection, mock_entry, setup_loxone_entry):
    await setup_loxone_entry(mock_entry)
    entity_id = _entity_id(hass, STATUS_ACTION)

    mock_connection.feed(STATUS_TEXT, "Lüften")
    mock_connection.feed(STATUS_ICON_COLOR, '{"icon": "Icons/Ventilation.svg", "color": "#45864A"}')
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state.state == "Lüften"
    assert state.attributes["loxone_icon"] == "Icons/Ventilation.svg"
    assert state.attributes["color"] == "#45864A"
    # A Loxone SVG path is not an mdi icon; the frontend must not try it.
    assert "icon" not in state.attributes

    # Malformed payloads clear the attributes instead of raising.
    mock_connection.feed(STATUS_ICON_COLOR, "{not json")
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state.state == "Lüften"
    assert "loxone_icon" not in state.attributes
    assert "color" not in state.attributes


async def test_text_state_long_text_is_capped(hass, mock_connection, mock_entry, setup_loxone_entry):
    await setup_loxone_entry(mock_entry)
    entity_id = _entity_id(hass, STATUS_ACTION)

    text = "x" * 300
    mock_connection.feed(STATUS_TEXT, text)
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert len(state.state) == 255
    assert state.state == "x" * 254 + "…"
    assert state.attributes["text"] == text

    # Back under the limit: the attribute goes away.
    mock_connection.feed(STATUS_TEXT, "kurz")
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state.state == "kurz"
    assert "text" not in state.attributes


async def test_text_state_without_icon_and_color_state(
    hass, loxapp3, mock_connection, mock_entry, setup_loxone_entry
):
    """Firmware before 13.1 has no ``iconAndColor`` state."""
    del loxapp3["controls"][STATUS_ACTION]["states"]["iconAndColor"]
    await setup_loxone_entry(mock_entry)
    entity_id = _entity_id(hass, STATUS_ACTION)

    mock_connection.feed(STATUS_TEXT, "Aus")
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state.state == "Aus"
    assert "loxone_icon" not in state.attributes


async def test_info_only_text_creates_a_sensor(hass, mock_connection, mock_entry, setup_loxone_entry):
    """A text memory flag with "Use" ticked is an InfoOnlyText control."""
    await setup_loxone_entry(mock_entry)
    entity_id = _entity_id(hass, INFO_TEXT_ACTION)

    mock_connection.feed(INFO_TEXT_STATE, "Wartung")
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "Wartung"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"icon": "Icons/a.svg", "color": "#FF0000"}', {"icon": "Icons/a.svg", "color": "#FF0000"}),
        ({"icon": "Icons/a.svg"}, {"icon": "Icons/a.svg"}),
        ('{"icon": "", "color": 5}', {}),
        ("[1, 2]", {}),
        ("", {}),
        (None, {}),
        (3.0, {}),
    ],
)
def test_icon_and_color_parser(raw, expected):
    assert text_state_icon_and_color(raw) == expected
