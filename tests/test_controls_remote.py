"""Remote (media controller, structure file spec V17)."""

from __future__ import annotations

import pytest
from homeassistant.const import STATE_OFF, STATE_ON

from _controls import control, entity_id, state, structure_with
from custom_components.loxone.controls.remote import mode_list

REMOTE = control(
    "Remote",
    "Living Room Media",
    states=("timeout", "mode", "active"),
    details={"favoritePad": 0, "modeList": {"1": {"name": "TV", "usedButtons": []}, "2": {"name": "Radio"}}},
)


@pytest.fixture
def loxapp3(loxapp3):
    return structure_with(loxapp3, REMOTE)


@pytest.fixture
async def setup(hass, mock_connection, mock_entry, setup_loxone_entry):
    await setup_loxone_entry(mock_entry)
    return mock_connection


def _commands(setup) -> list:
    return [c["value"] for c in setup.sent]


def test_mode_list():
    assert mode_list(REMOTE["details"]) == {1: "TV", 2: "Radio"}
    assert mode_list({"modeList": {"0": {"name": "Off"}, "x": {}}}) == {}
    assert mode_list({}) == {}


async def test_state_and_activity(hass, setup):
    remote = entity_id(hass, "remote", REMOTE["uuidAction"])
    setup.feed(state(REMOTE, "mode"), 2.0)
    await hass.async_block_till_done()
    current = hass.states.get(remote)
    assert current.state == STATE_ON
    assert current.attributes["current_activity"] == "Radio"
    assert current.attributes["activity_list"] == ["TV", "Radio"]

    setup.feed(state(REMOTE, "mode"), 0.0)
    await hass.async_block_till_done()
    assert hass.states.get(remote).state == STATE_OFF


async def test_turn_on_off(hass, setup):
    remote = entity_id(hass, "remote", REMOTE["uuidAction"])
    await hass.services.async_call("remote", "turn_on", {"entity_id": remote, "activity": "TV"}, blocking=True)
    await hass.services.async_call("remote", "turn_on", {"entity_id": remote}, blocking=True)
    await hass.services.async_call("remote", "turn_off", {"entity_id": remote}, blocking=True)
    await hass.async_block_till_done()
    assert _commands(setup) == ["mode/1", "on", "reset"]


async def test_send_command(hass, setup):
    remote = entity_id(hass, "remote", REMOTE["uuidAction"])
    await hass.services.async_call(
        "remote",
        "send_command",
        {"entity_id": remote, "command": ["volplus", "num5"], "num_repeats": 2, "delay_secs": 0},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert _commands(setup) == ["volplus", "num5", "volplus", "num5"]
