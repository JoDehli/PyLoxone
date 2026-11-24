"""Daytimer (Schedule block, structure file spec V17).

Details: ``analog`` (analog or digital output), ``text.on`` / ``text.off``
(digital) and ``format`` (analog). States: ``modeList``, ``mode``,
``override`` (remaining seconds), ``value``, ``entriesAndDefaultValue``
(a binary daytimer table, not used here), ``resetActive``,
``needsActivation``. Commands: ``pulse``, ``default/{value}``,
``startOverride/{value}/{seconds}``, ``stopOverride``, ``set/...``.

The main entity is a sensor with the current output value; overrides are
entity services, ``pulse`` is a button when the daytimer needs activation.
"""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import Platform

from . import SetupContext, register, register_service
from .base import ControlButton, ControlEntity, to_bool, to_float, to_int, to_text, unit_from_format

SUPPORT_DAYTIMER_OVERRIDE = 1
SERVICE_START_OVERRIDE = "daytimer_start_override"
SERVICE_STOP_OVERRIDE = "daytimer_stop_override"

# modeList: 0:mode=0;name=\"Feiertag\",1:mode=1;name=\"Urlaub\"
_MODE_RE = re.compile(r'(\d+):mode=(-?\d+);name=\\?"((?:[^"\\]|\\.)*?)\\?"')


def parse_mode_list(text: Any) -> dict[int, str]:
    """Mode id -> name from the proprietary ``modeList`` format."""
    if not isinstance(text, str):
        return {}
    return {int(mode): name for _index, mode, name in _MODE_RE.findall(text)}


class DaytimerSensor(ControlEntity, SensorEntity):
    """The daytimer's output value with mode and override as attributes."""

    _attr_icon = "mdi:calendar-clock"
    _attr_supported_features = SUPPORT_DAYTIMER_OVERRIDE

    def __init__(self, control: dict) -> None:
        super().__init__(
            control,
            watch=("value", "mode", "modeList", "override", "resetActive", "needsActivation"),
        )
        self.analog = bool(self.details.get("analog"))
        self._attr_native_value = None
        if self.analog:
            self._attr_native_unit_of_measurement = unit_from_format(self.details.get("format"))
        else:
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = ["off", "on"]
        self._value: float | None = None
        self._modes: dict[int, str] = {}
        self._mode: int | None = None
        self._override: float | None = None
        self._reset_active: bool | None = None
        self._needs_activation: bool | None = None

    def _handle_states(self, changes: dict[str, Any]) -> None:
        if "value" in changes:
            self._value = to_float(changes["value"])
            if self.analog:
                self._attr_native_value = self._value
            elif self._value is not None:
                self._attr_native_value = "on" if self._value else "off"
        if "modeList" in changes:
            self._modes = parse_mode_list(changes["modeList"])
        if "mode" in changes:
            self._mode = to_int(changes["mode"])
        if "override" in changes:
            self._override = to_float(changes["override"])
        if "resetActive" in changes:
            self._reset_active = to_bool(changes["resetActive"])
        if "needsActivation" in changes:
            self._needs_activation = to_bool(changes["needsActivation"])

    def _extra_attributes(self) -> dict[str, Any]:
        text = self.details.get("text") or {}
        attributes: dict[str, Any] = {
            "analog": self.analog,
            "mode_id": self._mode,
            "mode": self._modes.get(self._mode) if self._mode is not None else None,
            "override_active": bool(self._override),
            "override_remaining": self._override,
            "reset_active": self._reset_active,
            "needs_activation": self._needs_activation,
        }
        if not self.analog and self._value is not None:
            attributes["value_text"] = to_text(text.get("on") if self._value else text.get("off"))
        return attributes

    async def async_start_override(self, value: float, duration: int) -> None:
        """Override the output with ``value`` for ``duration`` seconds."""
        number = f"{value:g}" if self.analog else ("1" if value else "0")
        self.send(f"startOverride/{number}/{int(duration)}")

    async def async_stop_override(self) -> None:
        self.send("stopOverride")


register_service(
    Platform.SENSOR,
    SERVICE_START_OVERRIDE,
    "async_start_override",
    SUPPORT_DAYTIMER_OVERRIDE,
    {
        vol.Required("value"): vol.Coerce(float),
        vol.Required("duration"): vol.All(vol.Coerce(int), vol.Range(min=1)),
    },
)
register_service(Platform.SENSOR, SERVICE_STOP_OVERRIDE, "async_stop_override", SUPPORT_DAYTIMER_OVERRIDE)


@register(Platform.SENSOR, "Daytimer")
def _sensor(_ctx: SetupContext, control: dict) -> list:
    return [DaytimerSensor(control)] if control.get("states", {}).get("value") else []


@register(Platform.BUTTON, "Daytimer")
def _buttons(_ctx: SetupContext, control: dict) -> list:
    # "pulse" activates an entry that needs activation; only offered when
    # the daytimer has that state at all.
    if not control.get("states", {}).get("needsActivation"):
        return []
    return [ControlButton(control, "pulse", "Activate", icon="mdi:play-circle-outline")]
