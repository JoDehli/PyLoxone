"""Sequential, StatusMonitor, MailBox, UpDownLeftRight (structure file spec V17)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.util import dt as dt_util

from _controls import control, entity_id, state, structure_with

SEQUENTIAL = control(
    "Sequential",
    "Garden Sequences",
    states=("activeSequence",),
    details={"sequences": [{"id": 4, "name": "Gustav"}, {"id": 8, "name": "Karl"}]},
)
STATUS = control(
    "StatusMonitor",
    "Battery Monitor",
    states=tuple(f"numState{i}" for i in range(10)) + ("numDef", "inputStates"),
    details={
        "inputs": [{"name": "Sensor A"}, {"name": "Sensor B"}, {"name": "Sensor C"}],
        "status": {
            "0": {"name": "Empty", "prio": 0, "id": 0, "color": "#FF0000"},
            "1": {"name": "Low", "prio": 1, "id": 1, "color": "#FFFF00"},
            "2": {"name": "OK", "prio": 2, "id": 2, "color": "#00FF00"},
        },
    },
)
MAILBOX = control(
    "MailBox",
    "Parcel Box",
    states=("notificationsDisabledInput", "packetReceived", "mailReceived", "disableEndTime"),
    details={"deviceType": 1},
)
UP_DOWN = control("UpDownDigital", "Stairwell Buttons")
LEFT_RIGHT = control("LeftRightDigital", "Hall Buttons")
ANALOG = control(
    "UpDownAnalog",
    "Setpoint Input",
    states=("value", "error"),
    details={"min": -10, "max": 40, "step": 0.5, "format": "%.1f°C"},
)


@pytest.fixture
def loxapp3(loxapp3):
    return structure_with(loxapp3, SEQUENTIAL, STATUS, MAILBOX, UP_DOWN, LEFT_RIGHT, ANALOG)


@pytest.fixture
async def setup(hass, mock_connection, mock_entry, setup_loxone_entry):
    await setup_loxone_entry(mock_entry)
    return mock_connection


def _commands(setup) -> list:
    return [(c["uuid"], c["value"]) for c in setup.sent]


async def test_sequential(hass, setup):
    select = entity_id(hass, "select", SEQUENTIAL["uuidAction"])
    setup.feed(state(SEQUENTIAL, "activeSequence"), 8.0)
    await hass.async_block_till_done()
    current = hass.states.get(select)
    assert current.state == "Karl"
    assert current.attributes["options"] == ["Off", "Gustav", "Karl"]

    await hass.services.async_call("select", "select_option", {"entity_id": select, "option": "Gustav"}, blocking=True)
    await hass.services.async_call("select", "select_option", {"entity_id": select, "option": "Off"}, blocking=True)
    await hass.async_block_till_done()
    assert _commands(setup) == [
        (SEQUENTIAL["uuidAction"], "triggerSequence/4"),
        (SEQUENTIAL["uuidAction"], "triggerSequence/0"),
    ]


async def test_status_monitor(hass, setup):
    main = entity_id(hass, "sensor", STATUS["uuidAction"])
    low = entity_id(hass, "sensor", f"{STATUS['uuidAction']}-numState1")
    setup.feed(state(STATUS, "numState0"), 0.0)
    setup.feed(state(STATUS, "numState1"), 1.0)
    setup.feed(state(STATUS, "numState2"), 2.0)
    setup.feed(state(STATUS, "inputStates"), "2,1,2")
    await hass.async_block_till_done()
    current = hass.states.get(main)
    # Low (prio 1) beats OK (prio 2); Empty has no inputs.
    assert current.state == "Low"
    assert current.attributes["inputs"] == {"Sensor A": "OK", "Sensor B": "Low", "Sensor C": "OK"}
    assert current.attributes["counts"] == {"Empty": 0.0, "Low": 1.0, "OK": 2.0}
    assert hass.states.get(low).state == "1"

    setup.feed(state(STATUS, "numState0"), 1.0)
    setup.feed(state(STATUS, "inputStates"), "0,1,255")
    await hass.async_block_till_done()
    current = hass.states.get(main)
    assert current.state == "Empty"
    assert current.attributes["inputs"]["Sensor C"] == "Unconfigured"


async def test_mailbox(hass, setup):
    parcel = entity_id(hass, "binary_sensor", f"{MAILBOX['uuidAction']}-packetReceived")
    pause = entity_id(hass, "number", f"{MAILBOX['uuidAction']}-disableNotifications")
    until = entity_id(hass, "sensor", f"{MAILBOX['uuidAction']}-disableEndTime")
    end = dt_util.utcnow() + timedelta(minutes=90)
    since_2009 = (end - dt_util.parse_datetime("2009-01-01T00:00:00+00:00")).total_seconds()

    setup.feed(state(MAILBOX, "packetReceived"), 1.0)
    setup.feed(state(MAILBOX, "disableEndTime"), since_2009)
    await hass.async_block_till_done()
    assert hass.states.get(parcel).state == "on"
    assert hass.states.get(pause).state in ("89", "90")
    assert hass.states.get(until).attributes["device_class"] == "timestamp"

    await hass.services.async_call("number", "set_value", {"entity_id": pause, "value": 0}, blocking=True)
    for command in ("confirmPacket", "confirmMail"):
        button = entity_id(hass, "button", f"{MAILBOX['uuidAction']}-cmd-{command}")
        await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    await hass.async_block_till_done()
    uuid = MAILBOX["uuidAction"]
    assert _commands(setup) == [(uuid, "disableNotifications/0"), (uuid, "confirmPacket"), (uuid, "confirmMail")]


@pytest.mark.parametrize(("item", "labels"), [(UP_DOWN, ("Up", "Down")), (LEFT_RIGHT, ("Right", "Left"))])
async def test_digital_virtual_input(hass, setup, item, labels):
    up = entity_id(hass, "button", f"{item['uuidAction']}-cmd-PulseUp")
    down = entity_id(hass, "button", f"{item['uuidAction']}-cmd-PulseDown")
    assert hass.states.get(up).attributes["friendly_name"].endswith(labels[0])
    assert hass.states.get(down).attributes["friendly_name"].endswith(labels[1])
    await hass.services.async_call("button", "press", {"entity_id": up}, blocking=True)
    await hass.services.async_call("button", "press", {"entity_id": down}, blocking=True)
    await hass.async_block_till_done()
    assert _commands(setup) == [(item["uuidAction"], "PulseUp"), (item["uuidAction"], "PulseDown")]


async def test_analog_virtual_input(hass, setup):
    number = entity_id(hass, "number", ANALOG["uuidAction"])
    setup.feed(state(ANALOG, "value"), 21.5)
    setup.feed(state(ANALOG, "error"), 0.0)
    await hass.async_block_till_done()
    current = hass.states.get(number)
    assert current.state == "21.5"
    assert (current.attributes["min"], current.attributes["max"], current.attributes["step"]) == (-10, 40, 0.5)
    assert current.attributes["unit_of_measurement"] == "°C"
    assert current.attributes["invalid_value"] is False

    await hass.services.async_call("number", "set_value", {"entity_id": number, "value": 22.5}, blocking=True)
    await hass.async_block_till_done()
    assert _commands(setup) == [(ANALOG["uuidAction"], "22.5")]
