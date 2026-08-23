"""
Loxone climate

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""

from dataclasses import dataclass
from enum import Enum
import json
import logging
from abc import ABC

from homeassistant.components.climate import PLATFORM_SCHEMA, ClimateEntity
from homeassistant.components.climate.const import ClimateEntityFeature, HVACAction, HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from voluptuous import All, Optional, Range

from . import LoxoneEntity
from .const import CLIMATE_EVENT, CONF_HVAC_AUTO_MODE, PRESET_PAUSED_WINDOW, PRESET_SCHEDULE, SENDDOMAIN
from .helpers import add_room_and_cat_to_value_values, get_all, get_or_create_device
from .miniserver import get_miniserver_from_hass

_LOGGER = logging.getLogger(__name__)

OPMODETOLOXONE = {
    HVACMode.HEAT_COOL: 3,
    HVACMode.HEAT: 4,
    HVACMode.COOL: 5,
    HVACMode.OFF: -1,
}

class ActiveMode(Enum):
    ECONOMY = 0
    COMFORT = 1
    BUILDING_PROTECT = 2
    MANUAL = 3
    OFF = 4
    FIXED = 14
    FIXED_DYNAMIC = 112

@dataclass
class ActiveState:
    mode: ActiveMode
    value: float

    @classmethod
    def from_raw(cls, raw_value: float) -> ActiveState:
        base_value = raw_value if raw_value < 112 else ActiveMode.FIXED_DYNAMIC.value
        dynamic_value = 0 if raw_value < 112 else (raw_value - 112) / 2560.0
        mode = ActiveMode(base_value)
        return cls(mode=mode, value=dynamic_value)

class OperatingMode(Enum):
    OFF = (-1, HVACMode.OFF)
    AUTO_HEAT_COOL = (0, HVACMode.AUTO)
    AUTO_HEAT = (1, HVACMode.HEAT)
    AUTO_COOL = (2, HVACMode.COOL)
    MANUAL_HEAT_COOL = (3, HVACMode.HEAT_COOL)
    MANUAL_HEAT = (4, HVACMode.HEAT)
    MANUAL_COOL = (5, HVACMode.COOL)

    @classmethod
    def from_mode(cls, mode: float):
        """Returns the OperatingMode matching the given integer value."""
        for member in cls:
            if member.value[0] == mode:
                return member
        raise ValueError(f"{mode} is not a valid number for {cls.__name__}")

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        Optional(CONF_HVAC_AUTO_MODE, default=0): All(int, Range(min=0, max=2)),
    }
)


# noinspection PyUnusedLocal
async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    # value_template = config.get(CONF_VALUE_TEMPLATE)
    # auto_mode = 0 if config.get(CONF_HVAC_AUTO_MODE) is None else config.get(CONF_HVAC_AUTO_MODE)
    #
    # if value_template is not None:
    #     value_template.hass = hass
    # config = hass.data[DOMAIN]
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up LoxoneRoomControllerV2."""
    miniserver = get_miniserver_from_hass(hass, config_entry)
    loxconfig = miniserver.lox_config.json
    entities = []

    for climate in get_all(loxconfig, "IRoomControllerV2"):
        climate = add_room_and_cat_to_value_values(loxconfig, climate)
        climate.update(
            {
                "hass": hass,
                CONF_HVAC_AUTO_MODE: 0,
            }
        )
        entities.append(LoxoneRoomControllerV2(**climate))

    for climate in get_all(loxconfig, "IRoomController"):
        climate = add_room_and_cat_to_value_values(loxconfig, climate)
        climate.update(
            {
                "hass": hass,
                CONF_HVAC_AUTO_MODE: 0,
            }
        )
        entities.append(LoxoneRoomController(**climate))

    for accontrol in get_all(loxconfig, "AcControl"):
        accontrol = add_room_and_cat_to_value_values(loxconfig, accontrol)
        accontrol.update(
            {
                "hass": hass,
            }
        )
        entities.append(LoxoneAcControl(**accontrol))

    async_add_entities(entities)


class LoxoneRoomController(LoxoneEntity, ClimateEntity, ABC):
    """Loxone room controller (legacy, non-V2)"""

    def __init__(self, **kwargs):
        # Add room name to entity name for better identification in HomeKit
        if "room" in kwargs and kwargs["room"]:
            kwargs["name"] = f"{kwargs['room']} Climate"

        super().__init__(**kwargs)
        self.hass = kwargs["hass"]
        self._autoMode = kwargs[CONF_HVAC_AUTO_MODE]
        self._stateAttribUuids = kwargs["states"]
        self._stateAttribValues = {}
        self.type = "RoomController"

        # Set supported features
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
        )

        # Flatten UUID values - some might be lists (e.g., "temperatures")
        self._all_uuids = set()
        for value in self._stateAttribUuids.values():
            if isinstance(value, list):
                self._all_uuids.update(value)
            else:
                self._all_uuids.add(value)

        self._attr_device_info = get_or_create_device(self.unique_id, self.name, self.type, self.room)

    async def event_handler(self, event):
        update = False

        for key in self._all_uuids & event.data.keys():
            self._stateAttribValues[key] = event.data[key]
            update = True

        if update:
            self.async_write_ha_state()

    def get_state_value(self, name):
        uuid = self._stateAttribUuids.get(name)
        if isinstance(uuid, list):
            # For "temperatures" which is a list of UUIDs
            return [
                self._stateAttribValues.get(u)
                for u in uuid
                if u in self._stateAttribValues
            ]
        return (
            self._stateAttribValues[uuid]
            if uuid and uuid in self._stateAttribValues
            else None
        )

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes."""
        return {
            **self._attr_extra_state_attributes,
            "mode": self.get_state_value("mode"),
            "override": self.get_state_value("override"),
            "open_window": self.get_state_value("openWindow"),
            "curr_heat_temp_ix": self.get_state_value("currHeatTempIx"),
            "curr_cool_temp_ix": self.get_state_value("currCoolTempIx"),
        }

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self.get_state_value("tempActual")

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        return self.get_state_value("tempTarget")

    def set_temperature(self, **kwargs):
        """Set new target temperature"""
        temp = kwargs.get("temperature")
        if temp is None:
            return

        # IRoomController uses setTemp with current temperature index
        # Get the current active temperature index based on mode
        mode = self.get_state_value("mode")

        # Determine which temperature index to use
        temp_idx = self.get_state_value("currHeatTempIx")
        if mode == 2:  # Cooling mode
            cool_idx = self.get_state_value("currCoolTempIx")
            if cool_idx is not None:
                temp_idx = cool_idx

        if temp_idx is not None:
            # Command format: setTemp/<index>/<value>
            self.hass.bus.fire(
                SENDDOMAIN,
                dict(
                    uuid=self.uuidAction,
                    value=f"setTemp/{int(temp_idx)}/{temp}",
                ),
            )
            self.schedule_update_ha_state()

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the current HVAC action (heating, cooling)."""
        valve_heat = self.get_state_value("valveHeat")
        valve_cool = self.get_state_value("valveCool")

        if valve_heat and valve_heat > 0:
            return HVACAction.HEATING
        elif valve_cool and valve_cool > 0:
            return HVACAction.COOLING

        if self.get_state_value("isPreparing") == 1:
            return HVACAction.PREHEATING

        return HVACAction.IDLE

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return hvac operation mode."""
        mode = self.get_state_value("mode")

        # mode: 0=Auto, 1=Heat, 2=Cool, 3=Heat/Cool, 4=Off
        if mode == 0:
            return HVACMode.AUTO
        elif mode == 1:
            return HVACMode.HEAT
        elif mode == 2:
            return HVACMode.COOL
        elif mode == 3:
            return HVACMode.HEAT_COOL
        else:
            return HVACMode.OFF

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return the list of available hvac operation modes."""
        return [
            HVACMode.OFF,
            HVACMode.AUTO,
            HVACMode.HEAT,
            HVACMode.COOL,
            HVACMode.HEAT_COOL,
        ]

    @property
    def temperature_unit(self) -> str:
        """Return the unit of measurement used by the platform."""
        format_str = self.details.get("format")

        if format_str is None:
            return UnitOfTemperature.CELSIUS

        if "°F" in format_str or "F" in format_str:
            return UnitOfTemperature.FAHRENHEIT

        if "°C" in format_str or "C" in format_str:
            return UnitOfTemperature.CELSIUS

        return UnitOfTemperature.CELSIUS

    @property
    def target_temperature_step(self) -> float | None:
        """Return the supported step of target temperature."""
        return 0.5

    @property
    def min_temp(self) -> float:
        """Return the minimum temperature."""
        return 7.0

    @property
    def max_temp(self) -> float:
        """Return the maximum temperature."""
        return 35.0

    def set_hvac_mode(self, hvac_mode: str):
        """Set new target hvac mode."""
        # Map HVAC mode to Loxone mode
        mode_map = {
            HVACMode.OFF: 4,
            HVACMode.AUTO: 0,
            HVACMode.HEAT: 1,
            HVACMode.COOL: 2,
            HVACMode.HEAT_COOL: 3,
        }

        target_mode = mode_map.get(hvac_mode, 0)

        self.hass.bus.fire(
            SENDDOMAIN,
            dict(uuid=self.uuidAction, value=f"setMode/{target_mode}"),
        )

        self.schedule_update_ha_state()


class LoxoneRoomControllerV2(LoxoneEntity, ClimateEntity, ABC):
    """Loxone room controller V2 with demand tracking and dynamic capabilities."""

    _attr_translation_key = "room_controller_v2"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.hass = kwargs["hass"]
        self._autoMode = kwargs[CONF_HVAC_AUTO_MODE]
        self._states = kwargs["states"]
        self._states_reversed = { value: key for key, value in self._states.items() }
        self._state_attr_values = {}
        self._attr_min_temp = 5
        self._attr_max_temp = 40
        self.operating_mode = OperatingMode.OFF
        self.active_state = ActiveState.from_raw(ActiveMode.OFF.value)
        self.type = "RoomControllerV2"
        self._single_comfort_temp = kwargs["details"].get("singleComfortTemperature", False)
        self._demand = 0

        # Copy mode list to avoid mutating shared kwargs data
        self._modeList = list(kwargs["details"]["timerModes"])
        self._modeList.append({"id": "stop", "name": PRESET_SCHEDULE})

        # Determine heating/cooling capabilities from bitmask
        possible_capabilities = kwargs["details"].get("possibleCapabilities", 3)
        heat_possible = possible_capabilities & 1
        cool_possible = possible_capabilities & 2
        self._range_possible = bool(heat_possible and cool_possible)

        self._attr_device_info = get_or_create_device(
            self.unique_id, self.name, self.type, self.room
        )

    async def async_added_to_hass(self):
        """Register event listener once entity is added to HA."""
        await super().async_added_to_hass()
        unsub = self.hass.bus.async_listen(CLIMATE_EVENT, self.climate_handler)
        self.async_on_remove(unsub)

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Return supported features based on device capabilities."""
        op_mode = self.operating_mode
        if op_mode is OperatingMode.OFF:
            return ClimateEntityFeature.TURN_ON

        features = (
            ClimateEntityFeature.PRESET_MODE
            | ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
        )

        active_mode = self.active_mode
        is_dual = op_mode in (OperatingMode.AUTO_HEAT_COOL, OperatingMode.MANUAL_HEAT_COOL)
        is_fixed = active_mode in (ActiveMode.FIXED_DYNAMIC, ActiveMode.FIXED)
        if not is_fixed and self._range_possible and not self._single_comfort_temp and is_dual:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE_RANGE

        return features

    def climate_handler(self, event):
        """Handle climate demand events from ClimateController."""
        if event.data.get("uuid") == self.uuidAction:
            self._demand = event.data.get("value", 0)
            self._demand = event.data["value"]
            self.schedule_update_ha_state()

    def get_mode_from_id(self, mode_id):
        for mode in self._modeList:
            if mode["id"] == mode_id:
                return mode["name"]

    async def event_handler(self, event):
        update = False

        for key in set(self._states.values()) & event.data.keys():
            val = event.data[key]
            self._state_attr_values[key] = val
            if self._states_reversed[key] == "operatingMode":
                self.operating_mode = OperatingMode.from_mode(val)
            elif self._states_reversed[key] == "activeMode":
                self.active_state = ActiveState.from_raw(val)
            update = True

        if update:
            self.schedule_update_ha_state()

    def get_state_value(self, name, default=None):
        uuid = self._states.get(name)
        if uuid is None:
            return default
        return self._state_attr_values.get(uuid, default)

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes."""
        # extra = {}
        # for key in set(self._states.keys()):
        #     extra[key] = self.get_state_value(key)
        return {
            **self._attr_extra_state_attributes,
            "is_overridden": self.is_overridden,
            "demand": self._demand,
            "operating_mode": self.get_state_value("operatingMode"),
            "active_mode": self.get_state_value("activeMode"),
            "current_mode": self.get_state_value("currentMode"),
            "op_mode": self.operating_mode,
            "active_state": self.active_state,
            # "possible": self.details.get("possibleCapabilities", 3),
            # "single_comfort": self._single_comfort_temp,
            # "range_possible": self._range_possible,
            # "mode_list": self._modeList,
            # **extra,
        }

    @property
    def is_overridden(self) -> bool:
        return self.get_state_value("overrideReason", 0) > 0

    @property
    def active_mode(self) -> ActiveMode:
        return self.active_state.mode

    @property
    def temperature_unit(self) -> str:
        """Return the unit of measurement used by the platform."""
        # The Loxone Config app allows the designer to set an arbitrary
        # format string for the room controller's input temperature sensor.
        # We assume that the format string contains the unit of temperature,
        # and default to Celsius if not.
        format_str = self.details.get("format")

        if format_str is None:
            return UnitOfTemperature.CELSIUS

        if "°F" in format_str or "F" in format_str:
            return UnitOfTemperature.FAHRENHEIT

        if "°C" in format_str or "C" in format_str:
            return UnitOfTemperature.CELSIUS

        return UnitOfTemperature.CELSIUS

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self.get_state_value("tempActual")

    def set_temperature(self, **kwargs):
        """Set new target temperature."""
        op_mode = self.operating_mode
        active_mode = self.active_mode
        is_fixed = active_mode in (ActiveMode.FIXED_DYNAMIC, ActiveMode.FIXED)

        if is_fixed or active_mode == ActiveMode.MANUAL or op_mode in (OperatingMode.MANUAL_COOL, OperatingMode.MANUAL_HEAT) or (op_mode is OperatingMode.MANUAL_HEAT_COOL and not self._range_possible):
            # Manual mode — set manual temperature directly
            if "temperature" in kwargs:
                self.hass.bus.fire(
                    SENDDOMAIN,
                    dict(
                        uuid=self.uuidAction,
                        value=f'setManualTemperature/{kwargs["temperature"]}',
                    ),
                )
        elif not is_fixed and self._range_possible and op_mode in (OperatingMode.AUTO_HEAT_COOL, OperatingMode.MANUAL_HEAT_COOL):
            active = self.active_mode
            if "target_temp_high" in kwargs:
                comfort_cool = self.get_state_value("comfortTemperatureCool")
                if comfort_cool is not None:
                    new_temp = kwargs["target_temp_high"]
                    if active == ActiveMode.ECONOMY:
                        new_temp = new_temp - comfort_cool
                        new_temp = new_temp if new_temp >= 0.5 else 0.5
                        absent = self.get_state_value("absentMaxOffset")
                        if new_temp != absent:
                            self.hass.bus.fire(
                                SENDDOMAIN,
                                dict(uuid=self.uuidAction, value=f"setAbsentMaxTemperature/{new_temp}"),
                            )
                    elif active == ActiveMode.COMFORT:
                        if new_temp != comfort_cool:
                            self.hass.bus.fire(
                                SENDDOMAIN,
                                dict(uuid=self.uuidAction, value=f"setComfortTemperatureCool/{new_temp}"),
                            )
                    elif active == ActiveMode.BUILDING_PROTECT:
                        if new_temp != comfort_cool:
                            self.hass.bus.fire(
                                SENDDOMAIN,
                                dict(uuid=self.uuidAction, value=f"setecoplusmaxtemperature/{new_temp}"),
                            )
            if "target_temp_low" in kwargs:
                comfort_heat = self.get_state_value("comfortTemperature")
                if comfort_heat is not None:
                    new_temp = kwargs["target_temp_low"]
                    if active == ActiveMode.ECONOMY:
                        new_temp = comfort_heat - new_temp
                        new_temp = new_temp if new_temp >= 0.5 else 0.5
                        absent = self.get_state_value("absentMinOffset")
                        if new_temp != absent:
                            self.hass.bus.fire(
                                SENDDOMAIN,
                                dict(uuid=self.uuidAction, value=f"setAbsentMinTemperature/{new_temp}"),
                            )
                    elif active == ActiveMode.COMFORT:
                        if new_temp != comfort_heat:
                            self.hass.bus.fire(
                                SENDDOMAIN,
                                dict(uuid=self.uuidAction, value=f"setComfortTemperature/{new_temp}"),
                            )
                    elif active == ActiveMode.BUILDING_PROTECT:
                        if new_temp != comfort_cool:
                            self.hass.bus.fire(
                                SENDDOMAIN,
                                dict(uuid=self.uuidAction, value=f"setecoplusmintemperature/{new_temp}"),
                            )
        else:
            # Auto/single target — set comfort temp offset
            if "temperature" in kwargs:
                if active_mode == ActiveMode.FIXED_DYNAMIC:
                    self.hass.bus.fire(
                        SENDDOMAIN,
                        dict(uuid=self.uuidAction, value=f"override/{(kwargs["temperature"] * 2560) + 112}//{kwargs["temperature"]}"),
                    )
                else:
                    comfort = self.get_state_value("comfortTemperature")
                    if comfort is not None:
                        new_offset = kwargs["temperature"] - comfort
                        self.hass.bus.fire(
                            SENDDOMAIN,
                            dict(uuid=self.uuidAction, value=f"setComfortModeTemp/{new_offset}"),
                        )

        self.schedule_update_ha_state()

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""

        mode = self.operating_mode
        active = self.active_state
        if active.mode is ActiveMode.FIXED_DYNAMIC:
            return active.value
        if mode not in (OperatingMode.AUTO_HEAT_COOL, OperatingMode.MANUAL_HEAT_COOL):
            return self.get_state_value("tempTarget")
        if active.mode is ActiveMode.MANUAL:
            return self.get_state_value("tempTarget")

    @property
    def target_temperature_step(self) -> float | None:
        """Return the supported step of target temperature."""
        return 0.5

    @property
    def target_temperature_high(self) -> float | None:
        """Return the highbound target temperature we try to reach."""

        mode = self.operating_mode
        active = self.active_mode
        if mode in (OperatingMode.AUTO_HEAT_COOL, OperatingMode.MANUAL_HEAT_COOL):
            if active == ActiveMode.COMFORT:
                offset = self.get_state_value("comfortTemperatureOffset")
                return self.get_state_value("comfortTemperatureCool")
            elif active == ActiveMode.ECONOMY:
                temp = self.get_state_value("comfortTemperatureCool")
                offset = self.get_state_value("absentMaxOffset")
                return temp + offset
            elif active == ActiveMode.BUILDING_PROTECT:
                return self.get_state_value("heatProtectTemperature")
            elif active == ActiveMode.OFF:
                return None

    @property
    def target_temperature_low(self) -> float | None:
        """Return the lowbound target temperature we try to reach."""

        mode = self.operating_mode
        active = self.active_mode
        if mode in (OperatingMode.AUTO_HEAT_COOL, OperatingMode.MANUAL_HEAT_COOL):
            if active == ActiveMode.COMFORT:
                return self.get_state_value("comfortTemperature")
            elif active == ActiveMode.ECONOMY:
                temp = self.get_state_value("comfortTemperature")
                offset = self.get_state_value("absentMinOffset")
                return temp - offset
            elif active == ActiveMode.BUILDING_PROTECT:
                return self.get_state_value("frostProtectTemperature")
            elif active == ActiveMode.OFF:
                return None

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the current HVAC action (heating, cooling, idle)."""
        if self.get_state_value("openWindow"):
            return HVACAction.OFF
        if self.get_state_value("prepareState") == 1:
            return HVACAction.PREHEATING
        if self._demand == -1:
            return HVACAction.COOLING
        if self._demand == 1:
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return hvac operation ie. heat, cool mode."""
        is_auto = self.operating_mode in (OperatingMode.AUTO_HEAT_COOL, OperatingMode.AUTO_COOL, OperatingMode.AUTO_HEAT)
        if is_auto and not self.is_overridden:
            return HVACMode.AUTO
        elif self.operating_mode is OperatingMode.AUTO_HEAT_COOL and self.is_overridden:
            return HVACMode.HEAT_COOL
        return self.operating_mode.value[1]

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return the list of available hvac operation modes."""
        capabilities = self.get_state_value("capabilities", 3)
        modes = [HVACMode.AUTO, HVACMode.OFF]

        possible = int(capabilities)
        if possible & 1:
            modes.append(HVACMode.HEAT)
        if possible & 2:
            modes.append(HVACMode.COOL)

        if self._range_possible and possible & 3:
            modes.append(HVACMode.HEAT_COOL)

        return modes

    def set_hvac_mode(self, hvac_mode: HVACMode):
        """Set new target hvac mode."""

        target_mode = (
            self._autoMode if hvac_mode == HVACMode.AUTO else OPMODETOLOXONE[hvac_mode]
        )

        is_auto = self.operating_mode in (OperatingMode.AUTO_HEAT_COOL, OperatingMode.AUTO_HEAT, OperatingMode.AUTO_COOL, OperatingMode.MANUAL_HEAT_COOL)
        if is_auto and self.is_overridden:
            self.hass.bus.fire(
                SENDDOMAIN, dict(uuid=self.uuidAction, value="stopOverride")
            )

        self.hass.bus.fire(
            SENDDOMAIN,
            dict(uuid=self.uuidAction, value=f"setOperatingMode/{target_mode}"),
        )

        self.schedule_update_ha_state()

    @property
    def preset_mode(self):
        """Return the current preset mode."""
        if self.get_state_value("openWindow"):
            return PRESET_PAUSED_WINDOW
        return self.get_mode_from_id(self.active_mode.value)

    @property
    def preset_modes(self):
        """Return a list of available preset modes."""
        modes = [mode["name"] for mode in self._modeList]
        # Hide "Schedule" when not in auto mode and not overriden
        is_auto = self.operating_mode in (OperatingMode.AUTO_HEAT_COOL, OperatingMode.AUTO_HEAT, OperatingMode.AUTO_COOL, OperatingMode.MANUAL_HEAT_COOL)
        if not is_auto or (not self.is_overridden and is_auto):
            modes = [m for m in modes if m != PRESET_SCHEDULE]
        # Include the paused indicator when window is open
        if self.get_state_value("openWindow"):
            modes.append(PRESET_PAUSED_WINDOW)
        return modes

    def set_preset_mode(self, preset_mode: str):
        """Set new preset mode."""
        if preset_mode == PRESET_PAUSED_WINDOW:
            return  # Informational only — controlled by window sensor
        mode_id = next(
            (mode["id"] for mode in self._modeList if mode["name"] == preset_mode), None
        )
        if mode_id is not None:
            if mode_id == "stop" and self.is_overridden and self.operating_mode:
                self.hass.bus.fire(
                    SENDDOMAIN, dict(uuid=self.uuidAction, value="stopOverride")
                )
            elif mode_id == "stop":
                self.hass.bus.fire(
                    SENDDOMAIN, dict(uuid=self.uuidAction, value="setOperationMode/0")
                )
            else:
                self.hass.bus.fire(
                    SENDDOMAIN, dict(uuid=self.uuidAction, value=f"override/{mode_id}")
                )
            self.schedule_update_ha_state()


# ------------------ AC CONTROL --------------------------------------------------------
class LoxoneAcControl(LoxoneEntity, ClimateEntity, ABC):
    """Representation of a ACControl Loxone device."""

    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.SWING_MODE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )

    def __init__(self, **kwargs):
        _LOGGER.debug(f"Input AcControl: {kwargs}")
        super().__init__(**kwargs)
        self.hass = kwargs["hass"]

        self._stateAttribUuids = kwargs["states"]
        self._stateAttribValues = {}
        self.type = "AcControl"
        self._attr_device_info = get_or_create_device(
            self.unique_id, self.name, self.type, self.room
        )

    async def event_handler(self, event):
        # _LOGGER.debug(f"Climate Event data: {event.data}")
        update = False

        for key in set(self._stateAttribUuids.values()) & event.data.keys():
            self._stateAttribValues[key] = event.data[key]
            update = True

        if update:
            self.schedule_update_ha_state()

        # _LOGGER.debug(f"State attribs after event handling: {self._stateAttribValues}")

    def get_state_value(self, name):
        uuid = self._stateAttribUuids[name]
        return (
            self._stateAttribValues[uuid] if uuid in self._stateAttribValues else None
        )

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        return {
            **self._attr_extra_state_attributes,
            "device_type": self.type,
        }

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self.get_state_value("temperature")

    def set_temperature(self, **kwargs):
        """Set new target temperature"""
        temp = kwargs.get("temperature")
        if temp is None:
            return
        self.hass.bus.fire(
            SENDDOMAIN,
            dict(
                uuid=self.uuidAction,
                value=f"setTarget/{temp}",
            ),
        )

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return hvac operation ie. heat, cool mode.

        Need to be one of HVAC_MODE_*.
        """
        if self.get_state_value("status"):
            if self.get_state_value("mode") == 2:
                return HVACMode.HEAT
            elif self.get_state_value("mode") == 3:
                return HVACMode.COOL
            elif self.get_state_value("mode") == 4:
                return HVACMode.DRY
            elif self.get_state_value("mode") == 5:
                return HVACMode.FAN_ONLY
            else:
                return HVACMode.AUTO
        return HVACMode.OFF

    def set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""

        mode = 1
        match hvac_mode:
            case HVACMode.HEAT:
                mode = 2
            case HVACMode.COOL:
                mode = 3
            case HVACMode.DRY:
                mode = 4
            case HVACMode.FAN_ONLY:
                mode = 5

        self.hass.bus.fire(
            SENDDOMAIN,
            dict(
                uuid=self.uuidAction,
                value="off" if hvac_mode == HVACMode.OFF else "on",
            ),
        )

        self.hass.bus.fire(
            SENDDOMAIN,
            dict(
                uuid=self.uuidAction,
                value=f"setMode/{mode}",
            ),
        )

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return the list of available hvac operation modes.

        Need to be a subset of HVAC_MODES.
        """
        return [
            HVACMode.OFF,
            HVACMode.HEAT,
            HVACMode.COOL,
            HVACMode.DRY,
            HVACMode.FAN_ONLY,
            HVACMode.AUTO,
        ]

    @property
    def temperature_unit(self) -> str:
        """Return the unit of measurement used by the platform."""
        if "format" in self.details:
            if self.details["format"].find("°"):
                return UnitOfTemperature.CELSIUS
            return UnitOfTemperature.FAHRENHEIT
        return UnitOfTemperature.CELSIUS

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""

        return self.get_state_value("targetTemperature")

    @property
    def target_temperature_step(self) -> float | None:
        """Return the supported step of target temperature."""
        return 0.5

    @property
    def fan_mode(self) -> str | None:
        """Return current fan mode."""

        if self.get_state_value("fanspeeds") is not None:
            modes = json.loads(self.get_state_value("fanspeeds"))

            for mode in modes:
                if self.get_state_value("fan") == mode["id"]:
                    return mode["name"]

        return "Auto"

    def set_fan_mode(self, fan_mode):
        """Set new target fan mode."""
        self.hass.bus.fire(
            SENDDOMAIN,
            dict(
                uuid=self.uuidAction,
                value=f'setFan/{next((o["id"] for o in json.loads(self.get_state_value("fanspeeds")) if o["name"] == fan_mode), None)}',
            ),
        )

    @property
    def fan_modes(self) -> list[str]:
        """Return the list of available hvac operation modes."""

        if self.get_state_value("fanspeeds") is not None:
            return [o["name"] for o in json.loads(self.get_state_value("fanspeeds"))]
        else:
            return None

    @property
    def swing_mode(self) -> str | None:
        """Return current swing mode."""

        if self.get_state_value("airflows") is not None:
            modes = json.loads(self.get_state_value("airflows"))

            for mode in modes:
                if self.get_state_value("ventMode") == mode["id"]:
                    return mode["name"]

        return "Auto"

    def set_swing_mode(self, swing_mode):
        """Set new target swing mode."""

        self.hass.bus.fire(
            SENDDOMAIN,
            dict(
                uuid=self.uuidAction,
                value=f'setAirDir/{next((o["id"] for o in json.loads(self.get_state_value("airflows")) if o["name"] == swing_mode), None)}',
            ),
        )

    @property
    def swing_modes(self) -> list[str]:
        """Return the list of available swing modes."""

        if self.get_state_value("airflows") is not None:
            return [o["name"] for o in json.loads(self.get_state_value("airflows"))]
        else:
            return None
