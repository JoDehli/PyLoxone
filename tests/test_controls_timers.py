"""Hourcounter and PulseAt (structure file spec V17)."""

from __future__ import annotations

import pytest
from homeassistant.helpers import entity_registry as er

from _controls import control, entity_id, state, structure_with

COUNTER = control(
    "Hourcounter",
    "Heat Pump Service",
    states=(
        "total",
        "remaining",
        "lastActivation",
        "overdue",
        "maintenanceInterval",
        "stateUnit",
        "active",
        "overdueSince",
    ),
)
PULSE = control(
    "PulseAt",
    "Morning Pulse",
    states=("isActive", "startTime", "oneTimePulseDate", "pulseDuration", "type"),
    details={"pulseDurationLocked": False},
)
LOCKED_PULSE = control(
    "PulseAt", "Locked Pulse", states=("isActive", "startTime", "pulseDuration"), details={"pulseDurationLocked": True}
)


@pytest.fixture
def loxapp3(loxapp3):
    return structure_with(loxapp3, COUNTER, PULSE, LOCKED_PULSE)


@pytest.fixture
async def setup(hass, mock_connection, mock_entry, setup_loxone_entry):
    await setup_loxone_entry(mock_entry)
    return mock_connection


def _commands(setup) -> list:
    return [(c["uuid"], c["value"]) for c in setup.sent]


async def test_hourcounter_sensors(hass, setup):
    total = entity_id(hass, "sensor", f"{COUNTER['uuidAction']}-total")
    overdue = entity_id(hass, "binary_sensor", f"{COUNTER['uuidAction']}-overdue")
    last = entity_id(hass, "sensor", f"{COUNTER['uuidAction']}-lastActivation")
    setup.feed(state(COUNTER, "total"), 7200.0)
    setup.feed(state(COUNTER, "overdue"), 1.0)
    setup.feed(state(COUNTER, "lastActivation"), 86400.0)
    await hass.async_block_till_done()
    current = hass.states.get(total)
    # Seconds from the Miniserver, shown in hours.
    assert current.attributes["unit_of_measurement"] == "h"
    assert float(current.state) == 2.0
    assert hass.states.get(overdue).state == "on"
    assert hass.states.get(overdue).attributes["device_class"] == "problem"
    assert hass.states.get(last).attributes["device_class"] == "timestamp"


async def test_hourcounter_buttons(hass, setup):
    reset = entity_id(hass, "button", f"{COUNTER['uuidAction']}-cmd-reset")
    await hass.services.async_call("button", "press", {"entity_id": reset}, blocking=True)
    await hass.async_block_till_done()
    assert _commands(setup) == [(COUNTER["uuidAction"], "reset")]
    # resetAll also wipes the operating time: disabled by default.
    reset_all = er.async_get(hass).async_get(entity_id(hass, "button", f"{COUNTER['uuidAction']}-cmd-resetAll"))
    assert reset_all.disabled_by is not None


async def test_pulse_at(hass, setup):
    output = entity_id(hass, "binary_sensor", PULSE["uuidAction"])
    start = entity_id(hass, "time", f"{PULSE['uuidAction']}-startTime")
    duration = entity_id(hass, "number", f"{PULSE['uuidAction']}-pulseDuration")
    setup.feed(state(PULSE, "isActive"), 1.0)
    setup.feed(state(PULSE, "startTime"), 6 * 3600 + 15 * 60)
    setup.feed(state(PULSE, "pulseDuration"), 2.5)
    await hass.async_block_till_done()
    assert hass.states.get(output).state == "on"
    assert hass.states.get(start).state == "06:15:00"
    assert hass.states.get(duration).state == "2.5"

    await hass.services.async_call("time", "set_value", {"entity_id": start, "time": "07:30:10"}, blocking=True)
    await hass.services.async_call("number", "set_value", {"entity_id": duration, "value": 5}, blocking=True)
    button = entity_id(hass, "button", f"{PULSE['uuidAction']}-cmd-pulse")
    await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    await hass.async_block_till_done()
    uuid = PULSE["uuidAction"]
    assert _commands(setup) == [(uuid, "setTime/27010"), (uuid, "setPulseDuration/5"), (uuid, "pulse")]


async def test_locked_pulse_duration_is_read_only(hass, setup):
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("number", "loxone", f"{LOCKED_PULSE['uuidAction']}-pulseDuration") is None
    entity_id(hass, "sensor", f"{LOCKED_PULSE['uuidAction']}-pulseDuration")
