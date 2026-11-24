"""Central objects (structure file spec V17)."""

from __future__ import annotations

import pytest

from _controls import control, entity_id, structure_with

JALOUSIE_MEMBER = "63746c3a-0113-9767-ffff-a616c6f7573000019"  # not in the structure file


def _central(control_type: str, name: str, members: list[str]) -> dict:
    return control(control_type, name, details={"controls": [{"uuid": u, "id": i} for i, u in enumerate(members, 1)]})


CENTRAL_JALOUSIE = _central("CentralJalousie", "All Blinds", [JALOUSIE_MEMBER])
CENTRAL_GATE = _central("CentralGate", "All Gates", [])
CENTRAL_WINDOW = _central("CentralWindow", "All Windows", [])
CENTRAL_ALARM = _central("CentralAlarm", "All Alarms", [])
CENTRAL_AUDIO = _central("CentralAudioZone", "All Audio", [])
CENTRAL_LIGHT = _central("CentralLightController", "All Lights", [])
CENTRAL_PRESENCE = _central("CentralPresence", "All Presence", [])
ALL = (CENTRAL_JALOUSIE, CENTRAL_GATE, CENTRAL_WINDOW, CENTRAL_ALARM, CENTRAL_AUDIO, CENTRAL_LIGHT, CENTRAL_PRESENCE)


@pytest.fixture
def loxapp3(loxapp3):
    # The light controller member refers to a control of the harness.
    harness_light = next(u for u, c in loxapp3["controls"].items() if c["type"] == "LightControllerV2")
    CENTRAL_LIGHT["details"]["controls"] = [{"uuid": harness_light, "id": 1}]
    return structure_with(loxapp3, *ALL)


@pytest.fixture
async def setup(hass, mock_connection, mock_entry, setup_loxone_entry):
    await setup_loxone_entry(mock_entry)
    return mock_connection


def _commands(setup) -> list:
    return [(c["uuid"], c["value"]) for c in setup.sent]


@pytest.mark.parametrize(
    ("central", "device_class", "commands"),
    [
        (CENTRAL_JALOUSIE, "shutter", ["FullUp", "FullDown", "stop"]),
        (CENTRAL_GATE, "gate", ["open", "close", "stop"]),
        (CENTRAL_WINDOW, "window", ["fullopen", "fullclose", "stop"]),
    ],
)
async def test_central_covers(hass, setup, central, device_class, commands):
    cover = entity_id(hass, "cover", central["uuidAction"])
    current = hass.states.get(cover)
    assert current.attributes["device_class"] == device_class
    assert current.attributes["assumed_state"] is True
    for service in ("open_cover", "close_cover", "stop_cover"):
        await hass.services.async_call("cover", service, {"entity_id": cover}, blocking=True)
    await hass.async_block_till_done()
    assert _commands(setup) == [(central["uuidAction"], cmd) for cmd in commands]


async def test_member_names(hass, setup):
    cover = hass.states.get(entity_id(hass, "cover", CENTRAL_JALOUSIE["uuidAction"]))
    # Members missing from the structure file are listed by uuid.
    assert cover.attributes["controls"] == [JALOUSIE_MEMBER]
    lights = hass.states.get(entity_id(hass, "sensor", CENTRAL_LIGHT["uuidAction"]))
    assert lights.state == "1"
    assert lights.attributes["controls"] == ["Living Light Controller"]


@pytest.mark.parametrize(
    ("central", "commands"),
    [
        (CENTRAL_JALOUSIE, ["shade", "auto", "NoAuto"]),
        (CENTRAL_WINDOW, ["slightlyOpen"]),
        (CENTRAL_ALARM, ["on", "delayedon", "off", "quit"]),
        (CENTRAL_AUDIO, ["play", "pause", "volup", "voldown"]),
        (CENTRAL_LIGHT, ["on", "reset"]),
    ],
)
async def test_central_buttons(hass, setup, central, commands):
    for command in commands:
        button = entity_id(hass, "button", f"{central['uuidAction']}-cmd-{command}")
        await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    await hass.async_block_till_done()
    assert _commands(setup) == [(central["uuidAction"], cmd) for cmd in commands]


async def test_central_presence_has_only_the_member_sensor(hass, setup):
    sensor = hass.states.get(entity_id(hass, "sensor", CENTRAL_PRESENCE["uuidAction"]))
    assert sensor.state == "0"
    assert sensor.attributes["device_type"] == "CentralPresence"
