"""SteakThermo (Touch & Grill, structure file spec V17)."""

from __future__ import annotations

import json

import pytest

from _controls import control, entity_id, state, structure_with

STATES = (
    "currentTemperatures",
    "temperatureYellow",
    "temperatureGreen",
    "sensorInfo",
    "targetYellow",
    "targetGreen",
    "sensorAlarms",
    "yellowAlarmActive",
    "greenAlarmActive",
    "activeAlarmText",
    "timerRemaining",
    "timerInfo",
    "timerAlarm",
    "timerAlarmActive",
    "deviceState",
    "displayAlwaysOnBat",
    "displayAlwaysOnDc",
    "availableControls",
    "activeControl",
    "isActive",
    "touchProtection",
    "displayBrightness",
    "powerMode",
    "batteryStateOfCharge",
)
GRILL = control(
    "SteakThermo",
    "Touch Grill",
    states=STATES,
    details={"deviceType": 1, "isTouchProtectConnected": 0, "isBrightnessConnected": 0},
)
SENSOR_INFO = [
    {"name": "Brisket", "connected": True, "target": 85},
    {"name": "Pork Neck", "connected": False, "target": 100},
]


@pytest.fixture
def loxapp3(loxapp3):
    return structure_with(loxapp3, GRILL)


@pytest.fixture
async def setup(hass, mock_connection, mock_entry, setup_loxone_entry):
    await setup_loxone_entry(mock_entry)
    return mock_connection


def _commands(setup) -> list:
    return [c["value"] for c in setup.sent]


def _id(platform: str, key: str, hass) -> str:
    return entity_id(hass, platform, f"{GRILL['uuidAction']}-{key}")


async def test_temperatures(hass, setup):
    yellow = _id("sensor", "temperatureYellow", hass)
    green = _id("sensor", "temperatureGreen", hass)
    setup.feed(state(GRILL, "temperatureYellow"), 82.0)
    setup.feed(state(GRILL, "sensorInfo"), json.dumps(SENSOR_INFO))
    await hass.async_block_till_done()
    current = hass.states.get(yellow)
    assert current.state == "82.0"
    assert current.attributes["unit_of_measurement"] == "°C"
    assert current.attributes["sensor_name"] == "Brisket"
    assert hass.states.get(green).attributes["connected"] is False


async def test_target_temperature_keeps_the_sensor_name(hass, setup):
    target = _id("number", "targetGreen", hass)
    setup.feed(state(GRILL, "sensorInfo"), json.dumps(SENSOR_INFO))
    setup.feed(state(GRILL, "targetGreen"), 100.0)
    await hass.async_block_till_done()
    assert hass.states.get(target).state == "100.0"
    await hass.services.async_call("number", "set_value", {"entity_id": target, "value": 92}, blocking=True)
    await hass.async_block_till_done()
    assert _commands(setup) == ["setSensor/1/92/Pork%20Neck"]


async def test_timer(hass, setup):
    duration = _id("number", "timerDuration", hass)
    setup.feed(state(GRILL, "timerInfo"), json.dumps({"active": True, "duration": 300}))
    await hass.async_block_till_done()
    assert hass.states.get(duration).state == "300.0"
    assert hass.states.get(duration).attributes["timer_running"] is True

    await hass.services.async_call("number", "set_value", {"entity_id": duration, "value": 600}, blocking=True)
    for command in ("startTimer", "stopTimer", "quitAlarm"):
        await hass.services.async_call(
            "button", "press", {"entity_id": _id("button", f"cmd-{command}", hass)}, blocking=True
        )
    await hass.async_block_till_done()
    assert _commands(setup) == ["setTimerDuration/600", "startTimer", "stopTimer", "quitAlarm"]


async def test_device_diagnostics(hass, setup):
    device_state = _id("sensor", "deviceState", hass)
    power = _id("sensor", "powerMode", hass)
    battery = _id("sensor", "batteryStateOfCharge", hass)
    setup.feed(state(GRILL, "deviceState"), 4.0)
    setup.feed(state(GRILL, "powerMode"), 2.0)
    setup.feed(state(GRILL, "batteryStateOfCharge"), 64.0)
    await hass.async_block_till_done()
    assert hass.states.get(device_state).state == "asleep"
    assert hass.states.get(power).state == "battery"
    assert hass.states.get(battery).state == "64.0"


async def test_switches_and_brightness(hass, setup):
    touch = _id("switch", "touchProtection", hass)
    brightness = _id("number", "displayBrightness", hass)
    setup.feed(state(GRILL, "touchProtection"), 1.0)
    await hass.async_block_till_done()
    assert hass.states.get(touch).state == "on"

    await hass.services.async_call("switch", "turn_off", {"entity_id": touch}, blocking=True)
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": _id("switch", "displayAlwaysOnDc", hass)}, blocking=True
    )
    await hass.services.async_call("number", "set_value", {"entity_id": brightness, "value": 70}, blocking=True)
    await hass.async_block_till_done()
    assert _commands(setup) == ["setTouchProtection/0", "setDisplayAlwaysOnDc/1", "setDisplayBrightness/70"]


async def test_active_block_select(hass, setup):
    select = _id("select", "activeControl", hass)
    setup.feed(
        state(GRILL, "availableControls"),
        json.dumps([{"name": "Kitchen", "uuid": "a"}, {"name": "Garden", "uuid": "b"}]),
    )
    setup.feed(state(GRILL, "activeControl"), 1.0)
    await hass.async_block_till_done()
    current = hass.states.get(select)
    assert current.state == "Garden"
    assert current.attributes["options"] == ["Kitchen", "Garden"]
    await hass.services.async_call("select", "select_option", {"entity_id": select, "option": "Kitchen"}, blocking=True)
    await hass.async_block_till_done()
    assert _commands(setup) == ["setActive/0"]
