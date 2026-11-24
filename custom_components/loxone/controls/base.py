"""
Generic entities driven by a control's states and commands.

Every entity belongs to one Loxone control; all entities of a control share
one device. The unique id is the control's ``uuidAction`` for the main
entity and ``{uuidAction}-{key}`` for every further entity of the control.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cached_property
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.components.button import ButtonEntity
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.util import dt as dt_util

from .. import LoxoneEntity
from ..const import SENDDOMAIN
from ..helpers import clean_unit, get_or_create_device

_LOGGER = logging.getLogger(__name__)

# Loxone transfers dates as seconds since 2009-01-01 00:00 (Miniserver
# local time unless the spec says UTC).
_LOXONE_EPOCH = datetime(2009, 1, 1)  # noqa: DTZ001 - zone added per call


# --- value conversion ------------------------------------------------------


def to_float(value: Any) -> float | None:
    """A number, or None for anything that is not one."""
    if isinstance(value, bool):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value: Any) -> int | None:
    number = to_float(value)
    return None if number is None else int(number)


def to_bool(value: Any) -> bool | None:
    """Digital states arrive as 0.0 / 1.0, JSON flags as true / false."""
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "on"):
            return True
        if text in ("false", "off", ""):
            return False
    number = to_float(value)
    return None if number is None else number != 0


def to_text(value: Any) -> str | None:
    """Text states; HA limits a state to 255 characters."""
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    return text[:255]


def parse_json(value: Any, default: Any = None) -> Any:
    """JSON text state; ``default`` if it is empty or not JSON."""
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str) or not value.strip():
        return default
    try:
        return json.loads(value)
    except ValueError:
        return default


def from_loxone_time(value: Any, *, utc: bool = False) -> datetime | None:
    """Seconds since 2009 as an aware datetime; None for 0 / no value."""
    seconds = to_float(value)
    if not seconds or seconds <= 0:
        return None
    zone = UTC if utc else dt_util.get_default_time_zone()
    return _LOXONE_EPOCH.replace(tzinfo=zone) + timedelta(seconds=seconds)


def seconds_of_day(value: Any) -> str | None:
    """Seconds since midnight as ``HH:MM`` (``HH:MM:SS`` if needed)."""
    seconds = to_int(value)
    if seconds is None or seconds < 0:
        return None
    hours, rest = divmod(seconds % 86400, 3600)
    minutes, secs = divmod(rest, 60)
    if secs:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{hours:02d}:{minutes:02d}"


def unit_from_format(lox_format: Any) -> str | None:
    """Unit of a Loxone format string like ``%.1f kW``; None if it has none."""
    if not isinstance(lox_format, str) or not lox_format.strip():
        return None
    unit = clean_unit(lox_format).strip()
    return unit or None


# --- entities ----------------------------------------------------------------


class ControlEntity(LoxoneEntity):
    """
    Base for all entities of one control.

    ``watch`` lists the state names the entity follows; every change of
    them reaches :meth:`_handle_states` with the raw values by state name.
    """

    _attr_should_poll = False

    def __init__(
        self,
        control: dict,
        *,
        key: str | None = None,
        suffix: str | None = None,
        watch: tuple[str, ...] = (),
        enabled_default: bool = True,
        entity_category: EntityCategory | None = None,
        icon: str | None = None,
    ) -> None:
        name = control.get("name", "")
        super().__init__(
            uuidAction=control["uuidAction"],
            name=f"{name} {suffix}" if suffix else name,
            room=control.get("room", ""),
            cat=control.get("cat", ""),
        )
        self.control = control
        self.type = control.get("type", "")
        self._unique = control["uuidAction"] if key is None else f"{control['uuidAction']}-{key}"
        states = control.get("states") or {}
        self._watched = {states[name]: name for name in watch if states.get(name)}
        self._attr_entity_registry_enabled_default = enabled_default
        self._attr_entity_category = entity_category
        if icon:
            self._attr_icon = icon
        self._attr_device_info = get_or_create_device(control["uuidAction"], name, self.type, control.get("room", ""))

    @cached_property
    def unique_id(self) -> str:
        return self._unique

    @property
    def details(self) -> dict:
        return self.control.get("details") or {}

    def has_state(self, name: str) -> bool:
        return bool((self.control.get("states") or {}).get(name))

    def send(self, command: str) -> None:
        """Send ``command`` to the control (``jdev/sps/io/{uuid}/{command}``)."""
        self.hass.bus.async_fire(SENDDOMAIN, {"uuid": self.uuidAction, "value": command})

    async def event_handler(self, e) -> None:
        changes = {name: e.data[uuid] for uuid, name in self._watched.items() if uuid in e.data}
        if changes:
            self._handle_states(changes)
            self.async_schedule_update_ha_state()

    def _handle_states(self, changes: dict[str, Any]) -> None:
        """React to new raw values of watched states (by state name)."""

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            **self._attr_extra_state_attributes,
            "device_type": self.type,
            **self._extra_attributes(),
        }

    def _extra_attributes(self) -> dict[str, Any]:
        return {}


@dataclass(frozen=True, kw_only=True)
class StateSpec:
    """One state of a control shown as its own (binary) sensor."""

    key: str
    suffix: str | None = None
    # Default: to_float for sensors, to_bool for binary sensors.
    convert: Callable[[Any], Any] | None = None
    device_class: Any = None
    state_class: SensorStateClass | None = None
    unit: str | None = None
    suggested_unit: str | None = None
    entity_category: EntityCategory | None = None
    enabled_default: bool = True
    icon: str | None = None
    options: tuple[str, ...] | None = None
    main: bool = False


def state_entities(control: dict, specs: tuple[StateSpec, ...], cls: type) -> list:
    """One ``cls`` entity per spec whose state exists in the control."""
    states = control.get("states") or {}
    return [cls(control, spec) for spec in specs if states.get(spec.key)]


class ControlStateSensor(ControlEntity, SensorEntity):
    """A sensor showing one state of a control."""

    def __init__(self, control: dict, spec: StateSpec) -> None:
        super().__init__(
            control,
            key=None if spec.main else spec.key,
            suffix=spec.suffix,
            watch=(spec.key,),
            enabled_default=spec.enabled_default,
            entity_category=spec.entity_category,
            icon=spec.icon,
        )
        self.spec = spec
        self._attr_device_class = spec.device_class
        self._attr_state_class = spec.state_class
        self._attr_native_unit_of_measurement = spec.unit
        if spec.suggested_unit:
            self._attr_suggested_unit_of_measurement = spec.suggested_unit
        if spec.options is not None:
            self._attr_options = list(spec.options)
        self._attr_native_value = None

    def _handle_states(self, changes: dict[str, Any]) -> None:
        convert = self.spec.convert or to_float
        self._attr_native_value = convert(changes[self.spec.key])


class ControlBinarySensor(ControlEntity, BinarySensorEntity):
    """A binary sensor showing one digital state of a control."""

    def __init__(self, control: dict, spec: StateSpec) -> None:
        super().__init__(
            control,
            key=None if spec.main else spec.key,
            suffix=spec.suffix,
            watch=(spec.key,),
            enabled_default=spec.enabled_default,
            entity_category=spec.entity_category,
            icon=spec.icon,
        )
        self.spec = spec
        self._attr_device_class = spec.device_class
        self._attr_is_on = None

    def _handle_states(self, changes: dict[str, Any]) -> None:
        convert = self.spec.convert or to_bool
        self._attr_is_on = convert(changes[self.spec.key])


class ControlButton(ControlEntity, ButtonEntity):
    """A button sending one fixed command."""

    def __init__(
        self,
        control: dict,
        command: str,
        suffix: str,
        *,
        key: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(control, key=key or f"cmd-{command}", suffix=suffix, **kwargs)
        self.command = command

    async def async_press(self) -> None:
        self.send(self.command)


class ControlNumber(ControlEntity, NumberEntity):
    """
    A number backed by a state and set with a command template.

    ``command`` is formatted with ``value`` (already rounded to the step).
    """

    def __init__(
        self,
        control: dict,
        *,
        key: str,
        suffix: str,
        command: str,
        state: str | None = None,
        minimum: float = 0,
        maximum: float = 100,
        step: float = 1,
        unit: str | None = None,
        device_class: Any = None,
        mode: NumberMode = NumberMode.AUTO,
        convert: Callable[[Any], Any] = to_float,
        **kwargs: Any,
    ) -> None:
        super().__init__(control, key=key, suffix=suffix, watch=(state,) if state else (), **kwargs)
        self._state_key = state
        self._command = command
        self._convert = convert
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_mode = mode
        self._attr_native_value = None

    def _handle_states(self, changes: dict[str, Any]) -> None:
        self._attr_native_value = self._convert(changes[self._state_key])

    def format_value(self, value: float) -> str:
        step = self._attr_native_step or 1
        if float(step).is_integer() and float(value).is_integer():
            return str(int(value))
        return f"{value:g}"

    async def async_set_native_value(self, value: float) -> None:
        self.send(self._command.format(value=self.format_value(value)))


class ControlSwitch(ControlEntity, SwitchEntity):
    """A switch backed by a digital state with on / off commands."""

    def __init__(
        self,
        control: dict,
        *,
        key: str | None,
        suffix: str | None,
        state: str | None,
        on: str,
        off: str,
        convert: Callable[[Any], Any] = to_bool,
        **kwargs: Any,
    ) -> None:
        super().__init__(control, key=key, suffix=suffix, watch=(state,) if state else (), **kwargs)
        self._state_key = state
        self._on = on
        self._off = off
        self._convert = convert
        self._attr_is_on = None
        if state is None:
            self._attr_assumed_state = True

    def _handle_states(self, changes: dict[str, Any]) -> None:
        self._attr_is_on = self._convert(changes[self._state_key])

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.send(self._on)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.send(self._off)


class ControlSelect(ControlEntity, SelectEntity):
    """
    A select over ``options`` (id -> name) backed by a state.

    ``command`` is formatted with ``id``.
    """

    def __init__(
        self,
        control: dict,
        *,
        key: str | None,
        suffix: str | None,
        state: str,
        options: Mapping[Any, str],
        command: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(control, key=key, suffix=suffix, watch=(state,), **kwargs)
        self._state_key = state
        self._by_id = {str(_id): name for _id, name in options.items()}
        self._by_name = {name: _id for _id, name in self._by_id.items()}
        self._command = command
        self._attr_options = list(self._by_id.values())
        self._attr_current_option = None

    def _handle_states(self, changes: dict[str, Any]) -> None:
        raw = changes[self._state_key]
        number = to_float(raw)
        _id = str(int(number)) if number is not None and number.is_integer() else str(raw)
        self._attr_current_option = self._by_id.get(_id)

    async def async_select_option(self, option: str) -> None:
        self.send(self._command.format(id=self._by_name[option]))


# Re-exported for the control modules.
__all__ = [
    "BinarySensorDeviceClass",
    "ControlBinarySensor",
    "ControlButton",
    "ControlEntity",
    "ControlNumber",
    "ControlSelect",
    "ControlStateSensor",
    "ControlSwitch",
    "EntityCategory",
    "NumberMode",
    "SensorDeviceClass",
    "SensorStateClass",
    "StateSpec",
    "from_loxone_time",
    "parse_json",
    "seconds_of_day",
    "state_entities",
    "to_bool",
    "to_float",
    "to_int",
    "to_text",
    "unit_from_format",
]
