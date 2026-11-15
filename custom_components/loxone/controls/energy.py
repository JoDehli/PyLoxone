"""Energy controls (structure file spec V17).

* EnergyManager: ``currentPower`` / ``currentBat`` and loads from
  ``details.loads`` with ``trigger/{id}``, ``turnOn/{id}``, ``turnOff/{id}``
* EnergyManager2: grid / storage / production power, storage state of
  charge, the MinSoc / MaxSpwr parameters and loads that only exist in
  the ``loads`` text state (``{uuid}/activate|deactivate|automatic``)
* EnergyFlowMonitor: production / grid / storage power, prices, CO2 factor
  and the live value of every root node (``actualN``)
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, Platform, UnitOfPower
from homeassistant.core import callback

from ..const import EVENT
from . import SetupContext, register
from .base import (
    ControlButton,
    ControlEntity,
    ControlNumber,
    ControlStateSensor,
    ControlSwitch,
    NumberMode,
    StateSpec,
    from_loxone_time,
    parse_json,
    state_entities,
    to_bool,
    to_float,
    unit_from_format,
)

_LOGGER = logging.getLogger(__name__)

_POWER_UNITS = {unit.value for unit in UnitOfPower}


def _power_spec(key: str, suffix: str, unit: str | None, **kwargs: Any) -> StateSpec:
    """A power state; device class only when the unit is a power unit."""
    return StateSpec(
        key=key,
        suffix=suffix,
        unit=unit,
        device_class=SensorDeviceClass.POWER if unit in _POWER_UNITS else None,
        state_class=SensorStateClass.MEASUREMENT,
        **kwargs,
    )


def _loads(raw: Any) -> list[dict]:
    loads = parse_json(raw, [])
    return [load for load in loads if isinstance(load, dict)] if isinstance(loads, list) else []


# --- EnergyManager (generation 1) -----------------------------------------


class EnergyManagerLoadSwitch(ControlSwitch):
    """One load of an EnergyManager: on = turnOn (permanent), off = turnOff."""

    def __init__(self, control: dict, load: dict) -> None:
        self.load_id = load.get("id")
        super().__init__(
            control,
            key=f"load-{self.load_id}",
            suffix=load.get("name") or f"Load {self.load_id}",
            state="loads",
            on=f"turnOn/{self.load_id}",
            off=f"turnOff/{self.load_id}",
            icon="mdi:power-plug-outline",
        )
        self._attr_assumed_state = False
        self._load_state: dict = {}

    def _handle_states(self, changes: dict[str, Any]) -> None:
        for load in _loads(changes["loads"]):
            if load.get("id") == self.load_id:
                self._load_state = load
                self._attr_is_on = to_bool(load.get("isActive"))

    def _extra_attributes(self) -> dict[str, Any]:
        state = self._load_state
        return {
            "load_id": self.load_id,
            "preparing": state.get("isPreparing"),
            "active_until": from_loxone_time(state.get("activeUntil")),
            "waiting_for_activation": state.get("isWaitingforActivation"),
            "permanent_on": state.get("isPermanentOn"),
        }


@register(Platform.SENSOR, "EnergyManager")
def _em_sensors(_ctx: SetupContext, control: dict) -> list:
    # The spec only names the inputs (AIp, AIb); their units are not part
    # of the structure file.
    specs = (
        StateSpec(key="currentPower", suffix="Current Power", state_class=SensorStateClass.MEASUREMENT),
        StateSpec(key="currentBat", suffix="Battery", state_class=SensorStateClass.MEASUREMENT),
    )
    return state_entities(control, specs, ControlStateSensor)


def _em_loads(control: dict) -> list[dict]:
    loads = (control.get("details") or {}).get("loads") or []
    return [load for load in loads if isinstance(load, dict) and "id" in load]


@register(Platform.SWITCH, "EnergyManager")
def _em_switches(_ctx: SetupContext, control: dict) -> list:
    return [EnergyManagerLoadSwitch(control, load) for load in _em_loads(control)]


@register(Platform.BUTTON, "EnergyManager")
def _em_buttons(_ctx: SetupContext, control: dict) -> list:
    # "trigger" starts the minimum on time; without one there is no trigger.
    return [
        ControlButton(
            control,
            f"trigger/{load['id']}",
            f"{load.get('name') or 'Load ' + str(load['id'])} Trigger",
            key=f"trigger-{load['id']}",
            icon="mdi:play-circle-outline",
        )
        for load in _em_loads(control)
        if to_float(load.get("minOnTime"))
    ]


# --- EnergyManager2 -------------------------------------------------------

LOAD_MODES = ("automatic", "on", "off")
_LOAD_COMMANDS = {"automatic": "automatic", "on": "activate", "off": "deactivate"}


def load_mode(load: dict) -> str:
    """Manual on / off overrides automatic operation."""
    if load.get("activatedManually"):
        return "on"
    if load.get("deactivatedManually"):
        return "off"
    return "automatic"


class EnergyManager2LoadSelect(ControlEntity, SelectEntity):
    """One load of an EnergyManager2: automatic / on / off (until midnight)."""

    _attr_options = list(LOAD_MODES)
    _attr_icon = "mdi:power-plug-outline"

    def __init__(self, control: dict, load: dict) -> None:
        self.load_uuid = load["uuid"]
        super().__init__(
            control,
            key=f"load-{self.load_uuid}",
            suffix=load.get("name") or self.load_uuid,
            watch=("loads",),
        )
        self._load: dict = {}
        self._update(load)

    def _update(self, load: dict) -> None:
        self._load = load
        self._attr_current_option = load_mode(load)

    def _handle_states(self, changes: dict[str, Any]) -> None:
        for load in _loads(changes["loads"]):
            if load.get("uuid") == self.load_uuid:
                self._update(load)

    async def async_select_option(self, option: str) -> None:
        self.send(f"{self.load_uuid}/{_LOAD_COMMANDS[option]}")

    def _extra_attributes(self) -> dict[str, Any]:
        load = self._load
        return {
            "priority": load.get("prio"),
            "active": load.get("active"),
            "power": load.get("pwr"),
            "provided_power": load.get("ppwr"),
            "has_actual": load.get("hasActual"),
            "minimum_active_until": from_loxone_time(load.get("minimumActiveUntil"), utc=True),
            "active_due_to_daily_runtime": load.get("activeDueToDailyRuntime"),
        }


class EnergyManager2ActiveLoads(ControlEntity, SensorEntity):
    """Number of active loads; the loads as an attribute."""

    _attr_icon = "mdi:transmission-tower"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, control: dict) -> None:
        super().__init__(control, key="loads", suffix="Active Loads", watch=("loads",))
        self._attr_native_value = None
        self._loads: list[dict] = []

    def _handle_states(self, changes: dict[str, Any]) -> None:
        self._loads = _loads(changes["loads"])
        self._attr_native_value = sum(1 for load in self._loads if load.get("active"))

    def _extra_attributes(self) -> dict[str, Any]:
        return {
            "loads": [
                {
                    "name": load.get("name"),
                    "active": load.get("active"),
                    "power": load.get("pwr"),
                    "mode": load_mode(load),
                }
                for load in self._loads
            ]
        }


def _em2_flag(details: dict, key: str) -> bool:
    """A missing Has* flag counts as connected (older structure files)."""
    return bool(details.get(key, True))


@register(Platform.SENSOR, "EnergyManager2")
def _em2_sensors(_ctx: SetupContext, control: dict) -> list:
    details = control.get("details") or {}
    kw = UnitOfPower.KILO_WATT
    specs = [_power_spec("Gpwr", "Grid Power", kw), _power_spec("Ppwr", "Production Power", kw)]
    if _em2_flag(details, "HasSpwr"):
        specs.append(_power_spec("Spwr", "Storage Power", kw))
    if _em2_flag(details, "HasSsoc"):
        specs.append(
            StateSpec(
                key="Ssoc",
                suffix="Storage State of Charge",
                unit=PERCENTAGE,
                device_class=SensorDeviceClass.BATTERY,
                state_class=SensorStateClass.MEASUREMENT,
            )
        )
    # Parameters driven by logic cannot be set - shown read-only.
    if details.get("MinSocLocked"):
        specs.append(StateSpec(key="MinSoc", suffix="Minimum State of Charge", unit=PERCENTAGE))
    if details.get("MaxSpwrLocked"):
        specs.append(StateSpec(key="MaxSpwr", suffix="Maximum Storage Power", unit=kw))
    entities = state_entities(control, tuple(specs), ControlStateSensor)
    if (control.get("states") or {}).get("loads"):
        entities.append(EnergyManager2ActiveLoads(control))
    return entities


@register(Platform.NUMBER, "EnergyManager2")
def _em2_numbers(_ctx: SetupContext, control: dict) -> list:
    details = control.get("details") or {}
    states = control.get("states") or {}
    entities = []
    if states.get("MinSoc") and not details.get("MinSocLocked"):
        entities.append(
            ControlNumber(
                control,
                key="MinSoc",
                suffix="Minimum State of Charge",
                command="setMinSoc/{value}",
                state="MinSoc",
                minimum=0,
                maximum=100,
                step=1,
                unit=PERCENTAGE,
                mode=NumberMode.SLIDER,
            )
        )
    if states.get("MaxSpwr") and not details.get("MaxSpwrLocked"):
        entities.append(
            ControlNumber(
                control,
                key="MaxSpwr",
                suffix="Maximum Storage Power",
                command="setMaxSpwr/{value}",
                state="MaxSpwr",
                minimum=0,
                maximum=1000,
                step=0.1,
                unit=UnitOfPower.KILO_WATT,
                mode=NumberMode.BOX,
            )
        )
    return entities


@register(Platform.BUTTON, "EnergyManager2")
def _em2_buttons(_ctx: SetupContext, control: dict) -> list:
    return [ControlButton(control, "manage", "Manage Now", icon="mdi:refresh")]


@register(Platform.SELECT, "EnergyManager2")
def _em2_load_selects(ctx: SetupContext, control: dict) -> list:
    """Loads are only known from the ``loads`` state: add them as they appear."""
    loads_uuid = (control.get("states") or {}).get("loads")
    if not loads_uuid:
        return []
    known: set[str] = set()

    @callback
    def _discover(event) -> None:
        if loads_uuid not in event.data:
            return
        new = [
            EnergyManager2LoadSelect(control, load)
            for load in _loads(event.data[loads_uuid])
            if isinstance(load.get("uuid"), str) and load["uuid"] not in known
        ]
        if new:
            known.update(entity.load_uuid for entity in new)
            ctx.async_add_entities(new)

    ctx.config_entry.async_on_unload(ctx.hass.bus.async_listen(EVENT, _discover))
    return []


# --- EnergyFlowMonitor ----------------------------------------------------


@register(Platform.SENSOR, "EnergyFlowMonitor")
def _efm_sensors(_ctx: SetupContext, control: dict) -> list:
    details = control.get("details") or {}
    unit = unit_from_format(details.get("actualFormat"))
    specs = [
        _power_spec("Ppwr", "Production Power", unit),
        _power_spec("Gpwr", "Grid Power", unit),
        _power_spec("Spwr", "Storage Power", unit),
        StateSpec(key="Pri", suffix="Import Price", state_class=SensorStateClass.MEASUREMENT, icon="mdi:cash-minus"),
        StateSpec(key="Pre", suffix="Export Price", state_class=SensorStateClass.MEASUREMENT, icon="mdi:cash-plus"),
        StateSpec(
            key="CO2",
            suffix="CO2 Factor",
            unit="kg/kWh",
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:molecule-co2",
        ),
    ]
    # Root nodes with a live value delivered by the EFM itself.
    seen = {spec.key for spec in specs}
    for node in details.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        key = node.get("actualEfmState")
        if isinstance(key, str) and key not in seen:
            seen.add(key)
            specs.append(_power_spec(key, node.get("title") or key, unit))
    return state_entities(control, tuple(specs), ControlStateSensor)
