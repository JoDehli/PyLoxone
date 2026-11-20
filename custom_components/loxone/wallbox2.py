"""
Loxone Wallbox2 (Wallbox Gen. 2)

Entities for the ``Wallbox2`` control of the structure file (Loxone structure
file V17.0, section "Wallbox2"):

* switch        - charging allowed / enabled       (``allow/on`` / ``allow/off``)
* select        - charging mode 1-5 and manual     (``setmode/<id>``)
* number        - manual charging limit in kW      (``manualLimit/<kW>``)
* binary_sensor - vehicle connected, charging active, load shedding,
                  phase switching

The meter part of the control (``actual`` / ``total`` ...) is already exposed by
the Meter handling in ``sensor.py``; nothing is duplicated here.

All entities of one Wallbox2 control share a device. Commands are sent through
the regular ``SENDDOMAIN`` event, like every other platform of this component.

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""

from __future__ import annotations

import json
import logging
import math

from homeassistant.components.binary_sensor import (BinarySensorDeviceClass,
                                                    BinarySensorEntity)
from homeassistant.components.number import (NumberDeviceClass, NumberEntity,
                                             NumberMode)
from homeassistant.components.select import SelectEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory, UnitOfPower

from . import LoxoneEntity
from .const import SENDDOMAIN
from .helpers import (add_room_and_cat_to_value_values, get_all,
                      get_or_create_device)

_LOGGER = logging.getLogger(__name__)

WALLBOX2_TYPE = "Wallbox2"

# Commands of the Wallbox2 control (structure file V17.0, p. 147)
CMD_ALLOW_ON = "allow/on"
CMD_ALLOW_OFF = "allow/off"
CMD_SET_MODE = "setmode/{}"
CMD_MANUAL_LIMIT = "manualLimit/{}"

# Mode id of the manual mode (cannot be renamed, the limit can be changed)
MANUAL_MODE_ID = 99


def _truthy(value) -> bool | None:
    """Loxone sends booleans as 0/1 numbers (sometimes as strings).

    Returns None for a value that cannot be read, so a broken state shows up as
    "unknown" instead of pretending to be "off".
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number > 0


def get_wallbox2_controls(loxconfig: dict) -> list[dict]:
    """Return copies of all Wallbox2 controls, room and category resolved.

    ``add_room_and_cat_to_value_values`` replaces the room/category uuid in
    place, so each platform has to work on its own copy.
    """
    return [
        add_room_and_cat_to_value_values(loxconfig, dict(control))
        for control in get_all(loxconfig, [WALLBOX2_TYPE])
    ]


def build_mode_options(details: dict) -> tuple[list[str], dict[int, str], dict[str, int]]:
    """Build the select options from the ``modes`` detail."""
    return build_mode_options_from_list(details.get("modes") or [])


def parse_modes(value) -> list | None:
    """Parse the ``modes`` state (a JSON array, as text or already decoded)."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value if isinstance(value, list) else None


def build_mode_options_from_list(
    modes: list,
) -> tuple[list[str], dict[int, str], dict[str, int]]:
    """Build the select options from a list of mode objects.

    Returns the ordered option labels plus both lookup maps. A mode without a
    configured name is called "Mode <id>", the manual mode "Manual". The manual
    mode is always offered, even when the structure file omits it.
    """
    entries: list[tuple[int, str]] = []
    seen: set[int] = set()
    for mode in modes:
        try:
            mode_id = int(mode.get("id"))
        except (TypeError, ValueError, AttributeError):
            continue
        if mode_id in seen:
            continue
        seen.add(mode_id)
        name = (mode.get("name") or "").strip()
        if not name:
            name = "Manual" if mode_id == MANUAL_MODE_ID else f"Mode {mode_id}"
        entries.append((mode_id, name))
    if MANUAL_MODE_ID not in seen:
        entries.append((MANUAL_MODE_ID, "Manual"))

    options: list[str] = []
    id_to_label: dict[int, str] = {}
    label_to_id: dict[str, int] = {}
    for mode_id, label in entries:
        candidate = label
        index = 2
        while candidate in label_to_id:  # select options must be unique
            candidate = f"{label} ({index})"
            index += 1
        options.append(candidate)
        id_to_label[mode_id] = candidate
        label_to_id[candidate] = mode_id
    return options, id_to_label, label_to_id


class LoxoneWallbox2Entity(LoxoneEntity):
    """Common base: one entity per aspect of a Wallbox2 control."""

    # Key into the control's ``states`` dict this entity follows
    _state_key: str = ""
    # Suffix that keeps the unique id different from the control's uuidAction
    _suffix: str = ""
    # Name part appended to the control name
    _label: str = ""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.type = WALLBOX2_TYPE
        self._attr_name = f"{kwargs.get('name', 'Wallbox')} {self._label}".strip()
        self._attr_device_info = get_or_create_device(
            self.uuidAction, kwargs.get("name", "Wallbox"), self.type, self.room
        )

    @property
    def should_poll(self) -> bool:
        """The Miniserver pushes every change."""
        return False

    @property
    def unique_id(self) -> str:
        """uuidAction is shared by all aspects, so add the suffix."""
        return f"{self.uuidAction}-{self._suffix}"

    def _send(self, command: str) -> None:
        """Send a command to the Wallbox2 control."""
        self.hass.bus.async_fire(
            SENDDOMAIN, dict(uuid=self.uuidAction, value=command)
        )

    def _handle_value(self, value) -> None:
        """Store a pushed value. Implemented by the subclasses."""
        raise NotImplementedError

    async def event_handler(self, e):
        """Follow the state uuid of this aspect."""
        state_uuid = self.states.get(self._state_key)
        if state_uuid and state_uuid in e.data:
            self._handle_value(e.data[state_uuid])
            self.async_write_ha_state()

    @property
    def extra_state_attributes(self):
        return {
            **self._attr_extra_state_attributes,
            "state_uuid": self.states.get(self._state_key),
            "device_type": self.type,
            "platform": "loxone",
        }


class LoxoneWallbox2Switch(LoxoneWallbox2Entity, SwitchEntity):
    """Charging allowed (``enabled`` state, ``allow/on`` / ``allow/off``)."""

    _state_key = "enabled"
    _suffix = "allow"
    _label = "Charging allowed"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._attr_is_on = None

    def _handle_value(self, value) -> None:
        self._attr_is_on = _truthy(value)

    async def async_turn_on(self, **kwargs):
        self._send(CMD_ALLOW_ON)

    async def async_turn_off(self, **kwargs):
        self._send(CMD_ALLOW_OFF)


class LoxoneWallbox2Select(LoxoneWallbox2Entity, SelectEntity):
    """Charging mode (``mode`` state, ``setmode/<id>``)."""

    _state_key = "mode"
    _suffix = "mode"
    _label = "Charging mode"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        (
            self._attr_options,
            self._id_to_label,
            self._label_to_id,
        ) = build_mode_options(kwargs.get("details") or {})
        self._attr_current_option = None
        self._mode_id = None

    def _handle_value(self, value) -> None:
        try:
            self._mode_id = int(float(value))
        except (TypeError, ValueError):
            self._mode_id = None
        self._attr_current_option = self._id_to_label.get(self._mode_id)

    def _apply_modes(self, value) -> None:
        """Take the mode names from the pushed ``modes`` state."""
        modes = parse_modes(value)
        if modes is None:
            _LOGGER.debug("Unusable wallbox modes state: %r", value)
            return
        _LOGGER.debug("Wallbox modes from the Miniserver: %s", modes)
        (
            self._attr_options,
            self._id_to_label,
            self._label_to_id,
        ) = build_mode_options_from_list(modes)
        self._attr_current_option = self._id_to_label.get(self._mode_id)

    async def event_handler(self, e):
        """Follow the mode names first, then the active mode."""
        modes_uuid = self.states.get("modes")
        if modes_uuid and modes_uuid in e.data:
            self._apply_modes(e.data[modes_uuid])
            self.async_write_ha_state()
        await super().event_handler(e)

    @property
    def extra_state_attributes(self):
        return {
            **super().extra_state_attributes,
            "mode_id": self._mode_id,
            "modes": {str(k): v for k, v in self._id_to_label.items()},
        }

    async def async_select_option(self, option: str) -> None:
        mode_id = self._label_to_id.get(option)
        if mode_id is None:
            _LOGGER.warning(
                "Unknown mode '%s' for Loxone wallbox %s", option, self.name
            )
            return
        self._send(CMD_SET_MODE.format(mode_id))


class LoxoneWallbox2Number(LoxoneWallbox2Entity, NumberEntity):
    """Manual charging limit (``limit`` state, ``manualLimit/<kW>``).

    Setting a value also activates the manual mode (99) on the Miniserver, as
    described in the structure file.
    """

    _state_key = "limit"
    _suffix = "manual-limit"
    _label = "Manual limit"

    _attr_device_class = NumberDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_mode = NumberMode.BOX

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        details = kwargs.get("details") or {}
        low, high = float(details["min"]), float(details["max"])
        if not (math.isfinite(low) and math.isfinite(high)) or not 0 < low <= high:
            raise ValueError(f"invalid wallbox power range {low}..{high}")
        self._attr_native_min_value = low
        self._attr_native_max_value = high
        self._attr_native_step = 0.1
        self._attr_native_value = None

    def _handle_value(self, value) -> None:
        try:
            self._attr_native_value = float(value)
        except (TypeError, ValueError):
            self._attr_native_value = None

    async def async_set_native_value(self, value: float) -> None:
        value = float(value)
        if not math.isfinite(value):
            _LOGGER.warning("Ignoring non-finite wallbox limit %r", value)
            return
        # Never leave the range the wallbox itself reports.
        value = min(max(value, self._attr_native_min_value),
                    self._attr_native_max_value)
        self._send(CMD_MANUAL_LIMIT.format(round(value, 2)))


class LoxoneWallbox2BinarySensor(LoxoneWallbox2Entity, BinarySensorEntity):
    """Read-only flag of the Wallbox2 control."""

    def __init__(self, state_key, suffix, label, device_class=None,
                 diagnostic=False, **kwargs):
        # Instance values shadow the class attributes read by the base class.
        self._state_key = state_key
        self._suffix = suffix
        self._label = label
        super().__init__(**kwargs)
        self._attr_device_class = device_class
        if diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_is_on = None

    def _handle_value(self, value) -> None:
        self._attr_is_on = _truthy(value)


# state key, unique id suffix, label, device class, diagnostic
BINARY_SENSORS = (
    ("connected", "connected", "Vehicle connected", BinarySensorDeviceClass.PLUG, False),
    ("active", "charging", "Charging", BinarySensorDeviceClass.BATTERY_CHARGING, False),
    ("loadshed", "loadshed", "Load shedding", None, True),
    ("phaseSwitching", "phase-switching", "Phase switching", None, True),
)


def _build(factory, control: dict) -> list:
    """Run ``factory`` for one control; one broken wallbox must not take the
    whole platform down, so a failure is logged and the control skipped."""
    try:
        return factory(control)
    except Exception:  # noqa: BLE001
        _LOGGER.exception(
            "Could not set up Loxone wallbox %s", control.get("name")
        )
        return []


def build_switches(loxconfig: dict) -> list[LoxoneWallbox2Switch]:
    entities = []
    for control in get_wallbox2_controls(loxconfig):
        if "enabled" in (control.get("states") or {}):
            entities += _build(lambda c: [LoxoneWallbox2Switch(**c)], control)
    return entities


def build_selects(loxconfig: dict) -> list[LoxoneWallbox2Select]:
    entities = []
    for control in get_wallbox2_controls(loxconfig):
        if "mode" in (control.get("states") or {}):
            entities += _build(lambda c: [LoxoneWallbox2Select(**c)], control)
    return entities


def build_numbers(loxconfig: dict) -> list[LoxoneWallbox2Number]:
    """The limit entity needs the wallbox's own min/max; without a valid range
    it is not created, so no value can be sent that the wallbox never allowed."""
    entities = []
    for control in get_wallbox2_controls(loxconfig):
        if "limit" in (control.get("states") or {}):
            entities += _build(lambda c: [LoxoneWallbox2Number(**c)], control)
    return entities


def build_binary_sensors(loxconfig: dict) -> list[LoxoneWallbox2BinarySensor]:
    entities = []
    for control in get_wallbox2_controls(loxconfig):
        states = control.get("states") or {}
        for state_key, suffix, label, device_class, diagnostic in BINARY_SENSORS:
            if state_key in states:
                entities += _build(
                    lambda c, a=(state_key, suffix, label, device_class, diagnostic):
                    [LoxoneWallbox2BinarySensor(*a, **c)],
                    control,
                )
    return entities
