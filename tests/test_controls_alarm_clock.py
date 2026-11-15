"""AlarmClock (structure file spec V17)."""

from __future__ import annotations

import json

import pytest
from homeassistant.helpers import entity_registry as er

from _controls import control, entity_id, state, structure_with
from custom_components.loxone.controls.alarm_clock import put_command

STATES = (
    "isEnabled",
    "isAlarmActive",
    "confirmationNeeded",
    "entryList",
    "currentEntry",
    "nextEntry",
    "nextEntryMode",
    "ringingTime",
    "ringDuration",
    "prepareDuration",
    "snoozeTime",
    "snoozeDuration",
    "nextEntryTime",
    "wakeAlarmSoundSettings",
)
CLOCK = control(
    "AlarmClock",
    "Bedroom Alarm",
    states=STATES,
    details={"hasNightLight": True, "wakeAlarmSounds": [{"id": 0, "name": "Birds"}, {"id": 1, "name": "Beep"}]},
)
ENTRIES = {
    "1": {"name": "Workday", "isActive": True, "alarmTime": 23400, "modes": [3, 4, 5, 6, 7]},
    "2": {"name": "Night/Light", "isActive": False, "alarmTime": 30600, "nightLight": True, "daily": 1},
}


@pytest.fixture
def loxapp3(loxapp3):
    return structure_with(loxapp3, CLOCK)


@pytest.fixture
async def setup(hass, mock_connection, mock_entry, setup_loxone_entry):
    await setup_loxone_entry(mock_entry)
    return mock_connection


def _commands(setup) -> list:
    return [c["value"] for c in setup.sent]


def test_put_command():
    assert put_command("1", ENTRIES["1"], active=False) == "entryList/put/1/Workday/23400/0/3,4,5,6,7"
    assert put_command("2", ENTRIES["2"], active=True) == "entryList/put/2/Night%2FLight/30600/1/1"


async def test_next_alarm(hass, setup):
    sensor = entity_id(hass, "sensor", CLOCK["uuidAction"])
    setup.feed(state(CLOCK, "entryList"), json.dumps(ENTRIES))
    setup.feed(state(CLOCK, "nextEntry"), 1.0)
    setup.feed(state(CLOCK, "currentEntry"), -1.0)
    # 2026-11-16 06:30 local: days since 2009-01-01 * 86400 + 6.5 h
    setup.feed(state(CLOCK, "nextEntryTime"), 6528.0 * 86400 + 23400)
    await hass.async_block_till_done()
    current = hass.states.get(sensor)
    assert current.attributes["device_class"] == "timestamp"
    assert current.attributes["next_entry"] == "Workday"
    assert current.attributes["current_entry"] is None
    assert current.state.startswith("2026-11-16")


async def test_binary_sensors_and_buttons(hass, setup):
    ringing = entity_id(hass, "binary_sensor", f"{CLOCK['uuidAction']}-isAlarmActive")
    setup.feed(state(CLOCK, "isAlarmActive"), 1.0)
    await hass.async_block_till_done()
    assert hass.states.get(ringing).state == "on"

    for command in ("snooze", "dismiss"):
        button = entity_id(hass, "button", f"{CLOCK['uuidAction']}-cmd-{command}")
        await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    await hass.async_block_till_done()
    assert _commands(setup) == ["snooze", "dismiss"]


async def test_duration_numbers(hass, setup):
    snooze = entity_id(hass, "number", f"{CLOCK['uuidAction']}-snoozeDuration")
    setup.feed(state(CLOCK, "snoozeDuration"), 300.0)
    await hass.async_block_till_done()
    assert hass.states.get(snooze).state == "300.0"
    assert hass.states.get(snooze).attributes["min"] == 60
    await hass.services.async_call("number", "set_value", {"entity_id": snooze, "value": 600}, blocking=True)
    await hass.async_block_till_done()
    assert _commands(setup) == ["setSnoozeDuration/600"]


async def test_entry_switches_are_discovered(hass, setup):
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("switch", "loxone", f"{CLOCK['uuidAction']}-entry-1") is None
    setup.feed(state(CLOCK, "entryList"), json.dumps(ENTRIES))
    await hass.async_block_till_done()

    workday = entity_id(hass, "switch", f"{CLOCK['uuidAction']}-entry-1")
    night = entity_id(hass, "switch", f"{CLOCK['uuidAction']}-entry-2")
    assert hass.states.get(workday).state == "on"
    assert hass.states.get(workday).attributes["alarm_time"] == "06:30"
    assert hass.states.get(night).state == "off"

    await hass.services.async_call("switch", "turn_off", {"entity_id": workday}, blocking=True)
    await hass.services.async_call("switch", "turn_on", {"entity_id": night}, blocking=True)
    await hass.async_block_till_done()
    assert _commands(setup) == [
        "entryList/put/1/Workday/23400/0/3,4,5,6,7",
        "entryList/put/2/Night%2FLight/30600/1/1",
    ]

    # A deleted entry becomes unavailable.
    setup.feed(state(CLOCK, "entryList"), json.dumps({"1": ENTRIES["1"]}))
    await hass.async_block_till_done()
    assert hass.states.get(night).state == "unavailable"


async def test_wake_sound_settings(hass, setup):
    sound = entity_id(hass, "select", f"{CLOCK['uuidAction']}-wake-sound")
    volume = entity_id(hass, "number", f"{CLOCK['uuidAction']}-wake-volume")
    sloping = entity_id(hass, "switch", f"{CLOCK['uuidAction']}-wake-sloping")
    setup.feed(state(CLOCK, "wakeAlarmSoundSettings"), json.dumps({"sound": 1, "volume": 40, "isSloping": True}))
    await hass.async_block_till_done()
    assert hass.states.get(sound).state == "Beep"
    assert hass.states.get(volume).state == "40"
    assert hass.states.get(sloping).state == "on"

    await hass.services.async_call("select", "select_option", {"entity_id": sound, "option": "Birds"}, blocking=True)
    await hass.services.async_call("number", "set_value", {"entity_id": volume, "value": 55}, blocking=True)
    await hass.services.async_call("switch", "turn_off", {"entity_id": sloping}, blocking=True)
    await hass.async_block_till_done()
    assert _commands(setup) == ["setWakeAlarmSound/0", "setWakeAlarmVolume/55", "setWakeAlarmSlopingOn/0"]
