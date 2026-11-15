"""SteakThermo (Touch & Grill, structure file spec V17).

Two sensors, counted from left (yellow, index 0) to right (green, 1).

States used: ``temperatureYellow`` / ``temperatureGreen``,
``targetYellow`` / ``targetGreen``, ``sensorInfo`` (JSON: name,
connected, target), ``yellowAlarmActive`` / ``greenAlarmActive``,
``activeAlarmText``, ``timerRemaining``, ``timerInfo`` (JSON: active,
duration), ``timerAlarmActive``, ``deviceState``, ``displayAlwaysOnBat``,
``displayAlwaysOnDc``, ``availableControls`` / ``activeControl``,
``isActive``, ``touchProtection``, ``displayBrightness``, ``powerMode``,
``batteryStateOfCharge``.

Commands used: ``quitAlarm``, ``setSensor/{index}/{target}/{name}``,
``setDisplayAlwaysOnBat/{0|1}``, ``setDisplayAlwaysOnDc/{0|1}``,
``setActive/{index}``, ``setThisActive``, ``setTimerDuration/{s}``,
``startTimer``, ``stopTimer``, ``setTouchProtection/{0|1}``,
``setDisplayBrightness/{0-100}``.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from homeassistant.components.number import NumberEntity
from homeassistant.components.select import SelectEntity
from homeassistant.const import PERCENTAGE, Platform, UnitOfTemperature, UnitOfTime

from . import SetupContext, register
from .base import (
    BinarySensorDeviceClass,
    ControlBinarySensor,
    ControlButton,
    ControlEntity,
    ControlNumber,
    ControlStateSensor,
    ControlSwitch,
    EntityCategory,
    NumberMode,
    SensorDeviceClass,
    SensorStateClass,
    StateSpec,
    parse_json,
    state_entities,
    to_float,
    to_int,
    to_text,
)

SENSORS = ((0, "Yellow"), (1, "Green"))
DEVICE_STATES = {0: "running", 1: "offline", 2: "off", 3: "error", 4: "asleep"}
POWER_MODES = {1: "dc", 2: "battery"}


def _json_list(raw: Any) -> list:
    value = parse_json(raw, [])
    return value if isinstance(value, list) else []


class TargetTemperatureNumber(ControlEntity, NumberEntity):
    """Target temperature of one sensor; ``setSensor`` also needs its name."""

    _attr_native_min_value = 0
    _attr_native_max_value = 300
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:thermometer-check"

    def __init__(self, control: dict, index: int, color: str) -> None:
        self.index = index
        self.color = color
        super().__init__(
            control, key=f"target{color}", suffix=f"{color} Target", watch=(f"target{color}", "sensorInfo")
        )
        self._attr_native_value = None
        self._sensor_name = color

    def _handle_states(self, changes: dict[str, Any]) -> None:
        if f"target{self.color}" in changes:
            self._attr_native_value = to_float(changes[f"target{self.color}"])
        if "sensorInfo" in changes:
            info = _json_list(changes["sensorInfo"])
            if self.index < len(info) and isinstance(info[self.index], dict):
                self._sensor_name = str(info[self.index].get("name") or self.color)

    async def async_set_native_value(self, value: float) -> None:
        name = quote(self._sensor_name, safe="")
        self.send(f"setSensor/{self.index}/{int(value)}/{name}")


class SensorTemperature(ControlStateSensor):
    """Current temperature of one sensor; its name and connection as attributes."""

    def __init__(self, control: dict, index: int, color: str) -> None:
        super().__init__(
            control,
            StateSpec(
                key=f"temperature{color}",
                suffix=f"{color} Temperature",
                unit=UnitOfTemperature.CELSIUS,
                device_class=SensorDeviceClass.TEMPERATURE,
                state_class=SensorStateClass.MEASUREMENT,
            ),
        )
        self.index = index
        info_uuid = (control.get("states") or {}).get("sensorInfo")
        if info_uuid:
            self._watched[info_uuid] = "sensorInfo"
        self._info: dict = {}

    def _handle_states(self, changes: dict[str, Any]) -> None:
        if self.spec.key in changes:
            super()._handle_states(changes)
        if "sensorInfo" in changes:
            info = _json_list(changes["sensorInfo"])
            self._info = info[self.index] if self.index < len(info) and isinstance(info[self.index], dict) else {}

    def _extra_attributes(self) -> dict[str, Any]:
        return {"sensor_name": self._info.get("name"), "connected": self._info.get("connected")}


class TimerDurationNumber(ControlEntity, NumberEntity):
    _attr_native_min_value = 0
    _attr_native_max_value = 86400
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:timer-cog-outline"

    def __init__(self, control: dict) -> None:
        super().__init__(control, key="timerDuration", suffix="Timer Duration", watch=("timerInfo",))
        self._attr_native_value = None
        self._running: bool | None = None

    def _handle_states(self, changes: dict[str, Any]) -> None:
        info = parse_json(changes["timerInfo"], {})
        if isinstance(info, dict):
            self._attr_native_value = to_float(info.get("duration"))
            self._running = info.get("active")

    async def async_set_native_value(self, value: float) -> None:
        self.send(f"setTimerDuration/{int(value)}")

    def _extra_attributes(self) -> dict[str, Any]:
        return {"timer_running": self._running}


class ActiveControlSelect(ControlEntity, SelectEntity):
    """Which of the assigned blocks the Touch & Grill currently controls."""

    _attr_icon = "mdi:grill"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, control: dict) -> None:
        super().__init__(
            control, key="activeControl", suffix="Active Block", watch=("availableControls", "activeControl")
        )
        self._names: list[str] = []
        self._index: int | None = None
        self._attr_options = []

    def _handle_states(self, changes: dict[str, Any]) -> None:
        if "availableControls" in changes:
            self._names = [
                str(item.get("name")) for item in _json_list(changes["availableControls"]) if isinstance(item, dict)
            ]
            self._attr_options = list(self._names)
        if "activeControl" in changes:
            self._index = to_int(changes["activeControl"])

    @property
    def current_option(self) -> str | None:
        if self._index is None or not 0 <= self._index < len(self._names):
            return None
        return self._names[self._index]

    async def async_select_option(self, option: str) -> None:
        self.send(f"setActive/{self._names.index(option)}")


def _has(control: dict, name: str) -> bool:
    return bool((control.get("states") or {}).get(name))


@register(Platform.SENSOR, "SteakThermo")
def _sensors(_ctx: SetupContext, control: dict) -> list:
    entities: list = [
        SensorTemperature(control, i, color) for i, color in SENSORS if _has(control, f"temperature{color}")
    ]
    specs = (
        StateSpec(
            key="timerRemaining",
            suffix="Timer Remaining",
            unit=UnitOfTime.SECONDS,
            device_class=SensorDeviceClass.DURATION,
            icon="mdi:timer-sand",
        ),
        StateSpec(key="activeAlarmText", suffix="Alarm", convert=to_text, icon="mdi:alarm-light-outline"),
        StateSpec(
            key="batteryStateOfCharge",
            suffix="Battery",
            unit=PERCENTAGE,
            device_class=SensorDeviceClass.BATTERY,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        StateSpec(
            key="deviceState",
            suffix="Device State",
            convert=lambda value: DEVICE_STATES.get(to_int(value)),
            device_class=SensorDeviceClass.ENUM,
            options=tuple(DEVICE_STATES.values()),
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        StateSpec(
            key="powerMode",
            suffix="Power Source",
            convert=lambda value: POWER_MODES.get(to_int(value)),
            device_class=SensorDeviceClass.ENUM,
            options=tuple(POWER_MODES.values()),
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
    )
    return entities + state_entities(control, specs, ControlStateSensor)


@register(Platform.BINARY_SENSOR, "SteakThermo")
def _binary_sensors(_ctx: SetupContext, control: dict) -> list:
    specs = (
        StateSpec(key="yellowAlarmActive", suffix="Yellow Alarm", device_class=BinarySensorDeviceClass.PROBLEM),
        StateSpec(key="greenAlarmActive", suffix="Green Alarm", device_class=BinarySensorDeviceClass.PROBLEM),
        StateSpec(key="timerAlarmActive", suffix="Timer Alarm", icon="mdi:timer-alert-outline"),
        StateSpec(key="isActive", suffix="Active Block", icon="mdi:grill"),
    )
    return state_entities(control, specs, ControlBinarySensor)


@register(Platform.NUMBER, "SteakThermo")
def _numbers(_ctx: SetupContext, control: dict) -> list:
    entities: list = [
        TargetTemperatureNumber(control, i, color) for i, color in SENSORS if _has(control, f"target{color}")
    ]
    if _has(control, "timerInfo"):
        entities.append(TimerDurationNumber(control))
    if _has(control, "displayBrightness") and not (control.get("details") or {}).get("isBrightnessConnected"):
        entities.append(
            ControlNumber(
                control,
                key="displayBrightness",
                suffix="Display Brightness",
                command="setDisplayBrightness/{value}",
                state="displayBrightness",
                unit=PERCENTAGE,
                mode=NumberMode.SLIDER,
                entity_category=EntityCategory.CONFIG,
                icon="mdi:brightness-6",
            )
        )
    return entities


@register(Platform.SWITCH, "SteakThermo")
def _switches(_ctx: SetupContext, control: dict) -> list:
    switches = []
    if not (control.get("details") or {}).get("isTouchProtectConnected"):
        switches.append(("touchProtection", "Touch Protection", "setTouchProtection", "mdi:gesture-tap-hold"))
    switches += [
        ("displayAlwaysOnBat", "Display Always On (Battery)", "setDisplayAlwaysOnBat", "mdi:monitor"),
        ("displayAlwaysOnDc", "Display Always On (Power)", "setDisplayAlwaysOnDc", "mdi:monitor"),
    ]
    return [
        ControlSwitch(
            control,
            key=state,
            suffix=suffix,
            state=state,
            on=f"{command}/1",
            off=f"{command}/0",
            entity_category=EntityCategory.CONFIG,
            icon=icon,
        )
        for state, suffix, command, icon in switches
        if _has(control, state)
    ]


@register(Platform.BUTTON, "SteakThermo")
def _buttons(_ctx: SetupContext, control: dict) -> list:
    return [
        ControlButton(control, "quitAlarm", "Acknowledge Alarm", icon="mdi:bell-check"),
        ControlButton(control, "startTimer", "Start Timer", icon="mdi:timer-play-outline"),
        ControlButton(control, "stopTimer", "Stop Timer", icon="mdi:timer-stop-outline"),
        ControlButton(control, "setThisActive", "Make Active Block", icon="mdi:grill"),
    ]


@register(Platform.SELECT, "SteakThermo")
def _selects(_ctx: SetupContext, control: dict) -> list:
    return (
        [ActiveControlSelect(control)] if _has(control, "availableControls") and _has(control, "activeControl") else []
    )
