"""Daytimer (Schedule block, structure file spec V17)."""

from __future__ import annotations

import pytest
from homeassistant.const import STATE_UNKNOWN

from _controls import control, entity_id, state, structure_with
from custom_components.loxone.controls.daytimer import parse_mode_list

STATES = ("modeList", "mode", "override", "value", "entriesAndDefaultValue", "resetActive", "needsActivation")
MODE_LIST = '0:mode=0;name=\\"Feiertag\\",1:mode=1;name=\\"Urlaub\\",3:mode=3;name=\\"Montag\\"'

ANALOG = control("Daytimer", "Heating Schedule", states=STATES, details={"analog": True, "format": "%.1f°C"})
DIGITAL = control(
    "Daytimer",
    "Light Schedule",
    states=("mode", "value", "override"),
    details={"analog": False, "text": {"on": "Lights on", "off": "Lights off"}},
)


@pytest.fixture
def loxapp3(loxapp3):
    return structure_with(loxapp3, ANALOG, DIGITAL)


@pytest.fixture
async def setup(hass, mock_connection, mock_entry, setup_loxone_entry):
    await setup_loxone_entry(mock_entry)
    return mock_connection


def test_parse_mode_list():
    assert parse_mode_list(MODE_LIST) == {0: "Feiertag", 1: "Urlaub", 3: "Montag"}
    assert parse_mode_list('0:mode=0;name="Holiday"') == {0: "Holiday"}
    assert parse_mode_list(None) == {}


async def test_analog_daytimer(hass, setup):
    sensor = entity_id(hass, "sensor", ANALOG["uuidAction"])
    assert hass.states.get(sensor).state == STATE_UNKNOWN

    setup.feed(state(ANALOG, "modeList"), MODE_LIST)
    setup.feed(state(ANALOG, "mode"), 3.0)
    setup.feed(state(ANALOG, "value"), 21.5)
    setup.feed(state(ANALOG, "override"), 600.0)
    setup.feed(state(ANALOG, "needsActivation"), 1.0)
    await hass.async_block_till_done()
    current = hass.states.get(sensor)
    assert current.state == "21.5"
    assert current.attributes["unit_of_measurement"] == "°C"
    assert current.attributes["mode"] == "Montag"
    assert current.attributes["mode_id"] == 3
    assert current.attributes["override_active"] is True
    assert current.attributes["override_remaining"] == 600.0
    assert current.attributes["needs_activation"] is True


async def test_digital_daytimer(hass, setup):
    sensor = entity_id(hass, "sensor", DIGITAL["uuidAction"])
    setup.feed(state(DIGITAL, "value"), 1.0)
    await hass.async_block_till_done()
    current = hass.states.get(sensor)
    assert current.state == "on"
    assert current.attributes["value_text"] == "Lights on"
    assert current.attributes["options"] == ["off", "on"]

    setup.feed(state(DIGITAL, "value"), 0.0)
    await hass.async_block_till_done()
    assert hass.states.get(sensor).state == "off"


async def test_override_services(hass, setup):
    analog = entity_id(hass, "sensor", ANALOG["uuidAction"])
    digital = entity_id(hass, "sensor", DIGITAL["uuidAction"])
    await hass.services.async_call(
        "loxone", "daytimer_start_override", {"entity_id": analog, "value": 23.5, "duration": 3600}, blocking=True
    )
    await hass.services.async_call(
        "loxone", "daytimer_start_override", {"entity_id": digital, "value": 1, "duration": 60}, blocking=True
    )
    await hass.services.async_call("loxone", "daytimer_stop_override", {"entity_id": analog}, blocking=True)
    await hass.async_block_till_done()
    assert [(c["uuid"], c["value"]) for c in setup.sent] == [
        (ANALOG["uuidAction"], "startOverride/23.5/3600"),
        (DIGITAL["uuidAction"], "startOverride/1/60"),
        (ANALOG["uuidAction"], "stopOverride"),
    ]


async def test_override_service_skips_other_sensors(hass, setup):
    """Only daytimers advertise the override feature."""
    await hass.services.async_call("loxone", "daytimer_stop_override", {"entity_id": "all"}, blocking=True)
    await hass.async_block_till_done()
    assert sorted(c["uuid"] for c in setup.sent) == sorted([ANALOG["uuidAction"], DIGITAL["uuidAction"]])


async def test_activate_button_only_with_needs_activation(hass, setup):
    button = entity_id(hass, "button", f"{ANALOG['uuidAction']}-cmd-pulse")
    await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    await hass.async_block_till_done()
    assert setup.sent == [{"uuid": ANALOG["uuidAction"], "value": "pulse", "code": None}]

    from homeassistant.helpers import entity_registry as er

    assert er.async_get(hass).async_get_entity_id("button", "loxone", f"{DIGITAL['uuidAction']}-cmd-pulse") is None
