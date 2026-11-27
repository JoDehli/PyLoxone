"""
Loxone Load Manager

Read-only entities for the ``LoadManager`` control (Loxone structure file
16.0, section "LoadManager", pp. 110-111):

* sensor        - ``currentPower``, ``peakOverloadPower``, ``availablePower``,
                  ``maxPower`` and ``maxTp`` (maximum technical power), all in
                  kW; number of locked loads (``lockedLoads``)
* binary_sensor - ``maxPowerExceeded``; per load: locked (``lockedLoads``)
                  and active (``statusLoads``, only for loads with
                  ``hasStatus``)

``currentPower`` is the current power in "Overload" mode and the average
power in "Peak" mode; ``peakOverloadPower`` is the current power in "Peak
Overload" mode (``mode`` 2, since V15.3). The entity names follow the
``mode`` detail, as the Loxone app does: in "Peak" and "Peak Overload" mode
``currentPower`` is called "Average power", and in "Peak Overload" mode
``peakOverloadPower`` is called "Current power". Only the names change, the
unique ids stay the same.

``lockedLoads`` and ``statusLoads`` are bitmasks, "First Bit -> First Load":
bit ``n`` belongs to the load with ``id`` ``n`` in the ``loads`` detail. This
was also checked on a Miniserver (firmware 17.3) with twelve loads, where the
active loads in ``statusLoads`` matched the power measured on those circuits.

Not in the structure file, but sent by firmware 17.3: the state
``availablePowerPeak``, the bitmask ``reducedLoads`` and the load detail
``isAnalog``. Their entities (available peak power, per analog load:
reduced) are created disabled by default, as their meaning is not
documented.

All entities of one LoadManager control share a device. The structure file
lists no commands for the control, so nothing is sent.

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""

from __future__ import annotations

import logging
import math

from homeassistant.components.binary_sensor import (BinarySensorDeviceClass,
                                                    BinarySensorEntity)
from homeassistant.components.sensor import (SensorDeviceClass, SensorEntity,
                                             SensorStateClass)
from homeassistant.const import EntityCategory, UnitOfPower

from . import LoxoneEntity
from .helpers import (add_room_and_cat_to_value_values, get_all,
                      get_or_create_device)

_LOGGER = logging.getLogger(__name__)

LOAD_MANAGER_TYPE = "LoadManager"


def _number(value) -> float | None:
    """Return a finite float, or None for a value that cannot be read."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _bitmask(value) -> int | None:
    """Read a bitmask state (sent as a number, sometimes as a string)."""
    number = _number(value)
    if number is None or number < 0:
        return None
    return int(number)


def get_load_manager_controls(loxconfig: dict) -> list[dict]:
    """Return copies of all LoadManager controls, room and category resolved.

    ``add_room_and_cat_to_value_values`` replaces the room/category uuid in
    place, so each platform has to work on its own copy.
    """
    return [
        add_room_and_cat_to_value_values(loxconfig, dict(control))
        for control in get_all(loxconfig, [LOAD_MANAGER_TYPE])
    ]


def get_loads(control: dict) -> list[dict]:
    """Return the usable entries of the ``loads`` detail.

    A load without an integer ``id`` in the range of a bitmask is skipped, as
    are duplicate ids, so every load maps to exactly one bit.
    """
    loads = []
    seen: set[int] = set()
    for load in (control.get("details") or {}).get("loads") or []:
        try:
            load_id = int(load.get("id"))
        except (TypeError, ValueError, AttributeError):
            continue
        if not 0 <= load_id < 64 or load_id in seen:
            continue
        seen.add(load_id)
        loads.append({**load, "id": load_id})
    return loads


class LoxoneLoadManagerEntity(LoxoneEntity):
    """Common base: one entity per aspect of a LoadManager control."""

    # Key into the control's ``states`` dict this entity follows
    _state_key: str = ""
    # Suffix that keeps the unique id different from the control's uuidAction
    _suffix: str = ""
    # Name part appended to the control name
    _label: str = ""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.type = LOAD_MANAGER_TYPE
        self._attr_name = (
            f"{kwargs.get('name', 'Load Manager')} {self._label}".strip()
        )
        self._attr_device_info = get_or_create_device(
            self.uuidAction,
            kwargs.get("name", "Load Manager"),
            self.type,
            self.room,
        )

    @property
    def should_poll(self) -> bool:
        """The Miniserver pushes every change."""
        return False

    @property
    def unique_id(self) -> str:
        """uuidAction is shared by all aspects, so add the suffix."""
        return f"{self.uuidAction}-{self._suffix}"

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


class LoxoneLoadManagerPowerSensor(LoxoneLoadManagerEntity, SensorEntity):
    """A power value of the control in kW."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, state_key, suffix, label, diagnostic=False,
                 undocumented=False, **kwargs):
        # Instance values shadow the class attributes read by the base class.
        self._state_key = state_key
        self._suffix = suffix
        self._label = label
        super().__init__(**kwargs)
        if diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        if undocumented:
            self._attr_entity_registry_enabled_default = False
        self._attr_native_value = None

    def _handle_value(self, value) -> None:
        self._attr_native_value = _number(value)


class LoxoneLoadManagerLockedCountSensor(LoxoneLoadManagerEntity, SensorEntity):
    """Number of locked loads, with their names as an attribute."""

    _state_key = "lockedLoads"
    _suffix = "locked-loads"
    _label = "Locked loads"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:power-plug-off"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._loads = get_loads(kwargs)
        self._mask: int | None = None
        self._attr_native_value = None

    def _handle_value(self, value) -> None:
        self._mask = _bitmask(value)
        if self._mask is None:
            self._attr_native_value = None
            return
        self._attr_native_value = sum(
            1 for load in self._loads if self._mask >> load["id"] & 1
        )

    @property
    def extra_state_attributes(self):
        locked = (
            []
            if self._mask is None
            else [
                load.get("name") or f"Load {load['id'] + 1}"
                for load in self._loads
                if self._mask >> load["id"] & 1
            ]
        )
        return {**super().extra_state_attributes, "locked_loads": locked}


class LoxoneLoadManagerBinarySensor(LoxoneLoadManagerEntity, BinarySensorEntity):
    """A flag of the control, or one bit of a per-load bitmask."""

    def __init__(self, state_key, suffix, label, bit=None, device_class=None,
                 diagnostic=False, load=None, undocumented=False, **kwargs):
        self._state_key = state_key
        self._suffix = suffix
        self._label = label
        super().__init__(**kwargs)
        self._bit = bit
        self._load = load
        self._attr_device_class = device_class
        if diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        if undocumented:
            self._attr_entity_registry_enabled_default = False
        self._attr_is_on = None

    def _handle_value(self, value) -> None:
        if self._bit is None:
            number = _number(value)
            self._attr_is_on = None if number is None else number > 0
            return
        mask = _bitmask(value)
        self._attr_is_on = None if mask is None else bool(mask >> self._bit & 1)

    @property
    def extra_state_attributes(self):
        attributes = super().extra_state_attributes
        if self._load is not None:
            attributes = {
                **attributes,
                "load_id": self._load["id"],
                "load_name": self._load.get("name"),
                "load_power": _number(self._load.get("power")),
                "load_analog": bool(self._load.get("isAnalog")),
            }
        return attributes


MODE_OVERLOAD = 0
MODE_PEAK = 1
MODE_PEAK_OVERLOAD = 2

# state key, unique id suffix, label, diagnostic, undocumented
POWER_SENSORS = (
    ("currentPower", "current-power", "Current power", False, False),
    ("peakOverloadPower", "peak-overload-power", "Peak overload power", False, False),
    ("availablePower", "available-power", "Available power", False, False),
    ("availablePowerPeak", "available-power-peak", "Available peak power", True, True),
    ("maxPower", "max-power", "Maximum power", True, False),
    ("maxTp", "max-technical-power", "Maximum technical power", True, False),
)


def get_mode(control: dict) -> int | None:
    """Return the ``mode`` detail (since V15.3), or None when it is missing."""
    mode = _number((control.get("details") or {}).get("mode"))
    return None if mode is None else int(mode)


def power_label(state_key: str, default: str, mode: int | None) -> str:
    """Name a power value after its meaning in the configured mode.

    Spec: ``currentPower`` is the average power in "Peak" mode, and
    ``peakOverloadPower`` the current power in "Peak Overload" mode. The
    Loxone app also shows ``currentPower`` as "Average power" in "Peak
    Overload" mode. Without a ``mode`` (before V15.3) the default is kept.
    """
    if state_key == "currentPower" and mode in (MODE_PEAK, MODE_PEAK_OVERLOAD):
        return "Average power"
    if state_key == "peakOverloadPower" and mode == MODE_PEAK_OVERLOAD:
        return "Current power"
    return default


def _build(factory, control: dict) -> list:
    """Run ``factory`` for one control; one broken load manager must not take
    the whole platform down, so a failure is logged and the control skipped."""
    try:
        return factory(control)
    except Exception:  # noqa: BLE001
        _LOGGER.exception(
            "Could not set up Loxone load manager %s", control.get("name")
        )
        return []


def _sensors(control: dict) -> list:
    states = control.get("states") or {}
    mode = get_mode(control)
    entities: list = [
        LoxoneLoadManagerPowerSensor(
            state_key, suffix, power_label(state_key, label, mode),
            diagnostic, undocumented, **control
        )
        for state_key, suffix, label, diagnostic, undocumented in POWER_SENSORS
        if state_key in states
    ]
    if "lockedLoads" in states:
        entities.append(LoxoneLoadManagerLockedCountSensor(**control))
    return entities


def _binary_sensors(control: dict) -> list:
    states = control.get("states") or {}
    entities: list = []
    if "maxPowerExceeded" in states:
        entities.append(LoxoneLoadManagerBinarySensor(
            "maxPowerExceeded", "max-power-exceeded", "Maximum power exceeded",
            device_class=BinarySensorDeviceClass.PROBLEM, **control,
        ))
    for load in get_loads(control):
        load_id = load["id"]
        name = load.get("name") or f"Load {load_id + 1}"
        # state key, suffix, label, device class, undocumented
        per_load = [("lockedLoads", "locked", "locked", None, False)]
        # Spec: "Only display status if `hasStatus' attribute of load is true"
        if load.get("hasStatus"):
            per_load.append(("statusLoads", "active", "active",
                             BinarySensorDeviceClass.RUNNING, False))
        if load.get("isAnalog"):
            per_load.append(("reducedLoads", "reduced", "reduced", None, True))
        for state_key, suffix, label, device_class, undocumented in per_load:
            if state_key in states:
                entities.append(LoxoneLoadManagerBinarySensor(
                    state_key, f"load-{load_id}-{suffix}", f"{name} {label}",
                    bit=load_id, device_class=device_class, load=load,
                    undocumented=undocumented, **control,
                ))
    return entities


def build_sensors(loxconfig: dict) -> list[SensorEntity]:
    entities = []
    for control in get_load_manager_controls(loxconfig):
        entities += _build(_sensors, control)
    return entities


def build_binary_sensors(loxconfig: dict) -> list[LoxoneLoadManagerBinarySensor]:
    entities = []
    for control in get_load_manager_controls(loxconfig):
        entities += _build(_binary_sensors, control)
    return entities
