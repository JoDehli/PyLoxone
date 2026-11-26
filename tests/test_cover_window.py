"""Window cover against the Loxone structure file spec (V17, "Window").

States: position, direction, lockedReason (text, name of the input on
"WP"), targetPosition (since 11.3), type (since 15.3: 0 tilt top,
1 tilt bottom, 2 tilt left, 3 tilt right, 4 sliding left, 5 sliding right).
Commands: fullopen, fullclose, moveToPosition/{0..100}, slightlyOpen/, stop.
The trailing slash on slightlyOpen/ is required: without it the Miniserver
answers 200 but does not move the window.

The integration runs on the harness structure file; "Kitchen Window" carries
every state of the spec, plus details.type (where real structures carry the
window type when the "type" state is missing).
"""

from __future__ import annotations

import pytest
from homeassistant.components.cover import CoverEntityFeature
from homeassistant.const import STATE_CLOSED, STATE_OPEN, STATE_OPENING, STATE_UNKNOWN
from homeassistant.exceptions import ServiceNotSupported
from homeassistant.helpers import entity_registry as er

from custom_components.loxone.const import SUPPORT_SLIGHTLY_OPEN

WINDOW = "63746c3a-017b-9746-ffff-8656e2057696000123"
POSITION = "36333734-017c-9336-ffff-d303137622d3000124"
DIRECTION = "36333734-017d-9336-ffff-d303137622d3000125"
LOCKED_REASON = "36333734-017e-9336-ffff-d303137622d3000126"
TARGET_POSITION = "36333734-017f-9336-ffff-d303137622d3000127"
WINDOW_TYPE = "36333734-0180-9336-ffff-d303137622d3000128"
GATE = "63746c3a-017f-9726-ffff-56e204761746000127"


@pytest.fixture
async def window_entity_id(hass, mock_connection, mock_entry, setup_loxone_entry):
    await setup_loxone_entry(mock_entry)
    entity_id = er.async_get(hass).async_get_entity_id("cover", "loxone", WINDOW)
    assert entity_id is not None
    return entity_id


async def test_state_unknown_until_first_position(hass, window_entity_id):
    assert hass.states.get(window_entity_id).state == STATE_UNKNOWN


async def test_position_and_direction(hass, mock_connection, window_entity_id):
    mock_connection.feed(POSITION, 0.0)
    await hass.async_block_till_done()
    assert hass.states.get(window_entity_id).state == STATE_CLOSED

    mock_connection.feed(POSITION, 0.3)
    mock_connection.feed(DIRECTION, 1.0)
    mock_connection.feed(TARGET_POSITION, 0.8)
    await hass.async_block_till_done()
    state = hass.states.get(window_entity_id)
    assert state.state == STATE_OPENING
    assert state.attributes["current_position"] == 30
    assert state.attributes["target_position"] == 80.0

    mock_connection.feed(DIRECTION, 0.0)
    await hass.async_block_till_done()
    assert hass.states.get(window_entity_id).state == STATE_OPEN


async def test_locked_reason(hass, mock_connection, window_entity_id):
    attrs = hass.states.get(window_entity_id).attributes
    assert attrs["locked"] is False
    assert attrs["locked_reason"] is None

    mock_connection.feed(LOCKED_REASON, "Wind alarm")
    await hass.async_block_till_done()
    attrs = hass.states.get(window_entity_id).attributes
    assert attrs["locked"] is True
    assert attrs["locked_reason"] == "Wind alarm"

    mock_connection.feed(LOCKED_REASON, "")
    await hass.async_block_till_done()
    attrs = hass.states.get(window_entity_id).attributes
    assert attrs["locked"] is False
    assert attrs["locked_reason"] is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0.0, "tilt_top"),
        (1.0, "tilt_bottom"),
        (2.0, "tilt_left"),
        (3.0, "tilt_right"),
        (4.0, "sliding_left"),
        (5.0, "sliding_right"),
        (9.0, None),
    ],
)
async def test_window_type(hass, mock_connection, window_entity_id, raw, expected):
    mock_connection.feed(WINDOW_TYPE, raw)
    await hass.async_block_till_done()
    assert hass.states.get(window_entity_id).attributes["window_type"] == expected


async def test_supported_features(hass, window_entity_id):
    features = hass.states.get(window_entity_id).attributes["supported_features"]
    for flag in (
        CoverEntityFeature.OPEN,
        CoverEntityFeature.CLOSE,
        CoverEntityFeature.STOP,
        CoverEntityFeature.SET_POSITION,
    ):
        assert features & flag
    assert features & SUPPORT_SLIGHTLY_OPEN


@pytest.mark.parametrize(
    ("call", "command"),
    [
        (("open_cover", {}), "fullopen"),
        (("close_cover", {}), "fullclose"),
        (("stop_cover", {}), "stop"),
        (("set_cover_position", {"position": 40}), "moveToPosition/40"),
    ],
)
async def test_cover_commands(hass, mock_connection, window_entity_id, call, command):
    service, data = call
    await hass.services.async_call("cover", service, {"entity_id": window_entity_id, **data}, blocking=True)
    await hass.async_block_till_done()
    assert {"uuid": WINDOW, "value": command, "code": None} in mock_connection.sent


async def test_slightly_open_service(hass, mock_connection, window_entity_id):
    await hass.services.async_call(
        "loxone",
        "window_slightly_open",
        {"entity_id": window_entity_id},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert mock_connection.sent == [{"uuid": WINDOW, "value": "slightlyOpen/", "code": None}]


async def test_slightly_open_service_ignores_other_covers(hass, mock_connection, window_entity_id):
    """Gates and Jalousies do not advertise SUPPORT_SLIGHTLY_OPEN; targeting
    all covers must only reach the window."""
    await hass.services.async_call("loxone", "window_slightly_open", {"entity_id": "all"}, blocking=True)
    await hass.async_block_till_done()
    assert [cmd["value"] for cmd in mock_connection.sent] == ["slightlyOpen/"]
    assert mock_connection.sent[0]["uuid"] == WINDOW


async def test_slightly_open_service_rejects_explicit_gate(hass, mock_connection, window_entity_id):
    """Targeting a Gate explicitly is refused, and nothing is sent."""
    gate_entity_id = er.async_get(hass).async_get_entity_id("cover", "loxone", GATE)
    assert gate_entity_id is not None
    with pytest.raises(ServiceNotSupported):
        await hass.services.async_call(
            "loxone", "window_slightly_open", {"entity_id": gate_entity_id}, blocking=True
        )
    await hass.async_block_till_done()
    assert mock_connection.sent == []


async def test_window_type_from_details(hass, window_entity_id):
    """Before any "type" event, the type comes from details.type."""
    assert hass.states.get(window_entity_id).attributes["window_type"] == "tilt_top"


@pytest.mark.usefixtures("mock_connection")
async def test_window_type_details_only(hass, loxapp3, monkeypatch, mock_entry, setup_loxone_entry):
    """Structures without the "type" state (seen on a live V17.1 Miniserver)
    still expose the type through details.type."""
    control = loxapp3["controls"][WINDOW]
    monkeypatch.setitem(control, "details", {"type": 3})
    monkeypatch.delitem(control["states"], "type")
    await setup_loxone_entry(mock_entry)
    entity_id = er.async_get(hass).async_get_entity_id("cover", "loxone", WINDOW)
    assert hass.states.get(entity_id).attributes["window_type"] == "tilt_right"
