"""IRoomControllerV2 override reasons follow overrideEntries.reason (spec)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from custom_components.loxone.sensor import LoxoneRoomControllerOverrideSensor


def _reason(code: int) -> str:
    sensor = LoxoneRoomControllerOverrideSensor("Override", "uuid-reason", {}, "rc")
    sensor.async_schedule_update_ha_state = lambda: None
    asyncio.run(sensor.event_handler(SimpleNamespace(data={"uuid-reason": code})))
    return sensor._attr_native_value


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (2, "Window Open"),
        (9, "Cooling Forbidden"),  # was "Unknown (9)"
        (14, "Low request"),  # was "Fixed"
        (15, "Pause timer"),  # was clamped to 14
        (20, "Different mode than central"),  # was clamped to 14
    ],
)
def test_override_reason_labels(code, expected):
    assert _reason(code) == expected


def test_unknown_override_reason_is_kept_as_is():
    assert _reason(21) == "Unknown (21)"
