"""Hourcounter and PulseAt (structure file spec V17).

* Hourcounter (maintenance counter): ``total``, ``remaining``,
  ``lastActivation``, ``overdue``, ``maintenanceInterval``, ``stateUnit``,
  ``active``, ``overdueSince`` - all times in seconds; commands ``reset``
  and ``resetAll``.
* PulseAt: ``isActive``, ``startTime`` (seconds since midnight),
  ``oneTimePulseDate`` (seconds since 2009), ``pulseDuration``, ``type``;
  commands ``setTime/{s}``, ``setOneTimePulse/{date}``,
  ``setPulseDuration/{s}``, ``pulse``, ``setType/{id}``.
"""

from __future__ import annotations

from datetime import time
from typing import Any

from homeassistant.components.time import TimeEntity
from homeassistant.const import Platform, UnitOfTime

from . import SetupContext, register
from .base import (
    BinarySensorDeviceClass,
    ControlBinarySensor,
    ControlButton,
    ControlEntity,
    ControlNumber,
    ControlStateSensor,
    EntityCategory,
    NumberMode,
    SensorDeviceClass,
    SensorStateClass,
    StateSpec,
    from_loxone_time,
    state_entities,
    to_int,
)

_DURATION = {"device_class": SensorDeviceClass.DURATION, "unit": UnitOfTime.SECONDS}

# --- Hourcounter -------------------------------------------------------------


@register(Platform.SENSOR, "Hourcounter")
def _hourcounter_sensors(_ctx: SetupContext, control: dict) -> list:
    specs = (
        StateSpec(
            key="total",
            suffix="Operating Time",
            state_class=SensorStateClass.TOTAL_INCREASING,
            suggested_unit=UnitOfTime.HOURS,
            icon="mdi:timer-outline",
            **_DURATION,
        ),
        StateSpec(
            key="remaining",
            suffix="Until Maintenance",
            suggested_unit=UnitOfTime.HOURS,
            icon="mdi:wrench-clock",
            **_DURATION,
        ),
        StateSpec(
            key="overdueSince",
            suffix="Maintenance Overdue For",
            suggested_unit=UnitOfTime.HOURS,
            icon="mdi:wrench-clock",
            **_DURATION,
        ),
        StateSpec(
            key="maintenanceInterval",
            suffix="Maintenance Interval",
            suggested_unit=UnitOfTime.HOURS,
            entity_category=EntityCategory.DIAGNOSTIC,
            **_DURATION,
        ),
        StateSpec(
            key="lastActivation",
            suffix="Last Activation",
            convert=from_loxone_time,
            device_class=SensorDeviceClass.TIMESTAMP,
        ),
    )
    return state_entities(control, specs, ControlStateSensor)


@register(Platform.BINARY_SENSOR, "Hourcounter")
def _hourcounter_binary_sensors(_ctx: SetupContext, control: dict) -> list:
    specs = (
        StateSpec(key="active", suffix="Active", device_class=BinarySensorDeviceClass.RUNNING),
        StateSpec(key="overdue", suffix="Maintenance Required", device_class=BinarySensorDeviceClass.PROBLEM),
    )
    return state_entities(control, specs, ControlBinarySensor)


@register(Platform.BUTTON, "Hourcounter")
def _hourcounter_buttons(_ctx: SetupContext, control: dict) -> list:
    return [
        ControlButton(control, "reset", "Maintenance Done", icon="mdi:wrench-check"),
        ControlButton(
            control,
            "resetAll",
            "Reset All",
            icon="mdi:restore",
            entity_category=EntityCategory.CONFIG,
            enabled_default=False,
        ),
    ]


# --- PulseAt -----------------------------------------------------------------


class PulseAtStartTime(ControlEntity, TimeEntity):
    """Daily start time of the pulse (``setTime/{seconds since midnight}``)."""

    _attr_icon = "mdi:clock-start"

    def __init__(self, control: dict) -> None:
        super().__init__(control, key="startTime", suffix="Start Time", watch=("startTime",))
        self._attr_native_value = None

    def _handle_states(self, changes: dict[str, Any]) -> None:
        seconds = to_int(changes["startTime"])
        if seconds is None or seconds < 0:
            self._attr_native_value = None
            return
        hours, rest = divmod(seconds % 86400, 3600)
        self._attr_native_value = time(hours, *divmod(rest, 60))

    async def async_set_value(self, value: time) -> None:
        self.send(f"setTime/{value.hour * 3600 + value.minute * 60 + value.second}")


@register(Platform.BINARY_SENSOR, "PulseAt")
def _pulse_binary(_ctx: SetupContext, control: dict) -> list:
    return state_entities(
        control,
        (StateSpec(key="isActive", main=True, device_class=BinarySensorDeviceClass.RUNNING),),
        ControlBinarySensor,
    )


@register(Platform.SENSOR, "PulseAt")
def _pulse_sensors(_ctx: SetupContext, control: dict) -> list:
    specs = [
        StateSpec(
            key="oneTimePulseDate",
            suffix="One-time Pulse",
            convert=from_loxone_time,
            device_class=SensorDeviceClass.TIMESTAMP,
        ),
        StateSpec(key="type", suffix="Type", convert=to_int, entity_category=EntityCategory.DIAGNOSTIC),
    ]
    if (control.get("details") or {}).get("pulseDurationLocked"):
        # The duration input is driven by logic: read-only.
        specs.append(StateSpec(key="pulseDuration", suffix="Pulse Duration", **_DURATION))
    return state_entities(control, tuple(specs), ControlStateSensor)


@register(Platform.NUMBER, "PulseAt")
def _pulse_numbers(_ctx: SetupContext, control: dict) -> list:
    if (control.get("details") or {}).get("pulseDurationLocked") or not (control.get("states") or {}).get(
        "pulseDuration"
    ):
        return []
    return [
        ControlNumber(
            control,
            key="pulseDuration",
            suffix="Pulse Duration",
            command="setPulseDuration/{value}",
            state="pulseDuration",
            minimum=0,
            maximum=86400,
            step=0.1,
            unit=UnitOfTime.SECONDS,
            mode=NumberMode.BOX,
        )
    ]


@register(Platform.BUTTON, "PulseAt")
def _pulse_buttons(_ctx: SetupContext, control: dict) -> list:
    return [ControlButton(control, "pulse", "Pulse", icon="mdi:pulse")]


@register(Platform.TIME, "PulseAt")
def _pulse_time(_ctx: SetupContext, control: dict) -> list:
    return [PulseAtStartTime(control)] if (control.get("states") or {}).get("startTime") else []
