"""
Loxone climate

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""

import logging
from abc import ABC

from homeassistant.components.climate import PLATFORM_SCHEMA, ClimateEntity
from homeassistant.components.climate.const import (ClimateEntityFeature,
                                                    HVACAction, HVACMode)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from propcache import cached_property
from pyexpat import features
from voluptuous import All, Optional, Range

from . import LoxoneEntity
from .const import CONF_HVAC_AUTO_MODE, SENDDOMAIN
from .helpers import (add_room_and_cat_to_value_values, get_all,
                      get_or_create_device)
from .miniserver import get_miniserver_from_hass

_LOGGER = logging.getLogger(__name__)

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
    miniserver = get_miniserver_from_hass(hass)
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

    for accontrol in get_all(loxconfig, "AcControl"):
        accontrol = add_room_and_cat_to_value_values(loxconfig, accontrol)
        accontrol.update(
            {
                "hass": hass,
            }
        )
        entities.append(LoxoneAcControl(**accontrol))

    async_add_entities(entities)


class LoxoneRoomControllerV2(LoxoneEntity, ClimateEntity, ABC):
    """Loxone room controller"""

    # attr_supported_features = (ClimateEntityFeature.TARGET_TEMPERATURE)

    # attr_supported_features = (
    #     ClimateEntityFeature.PRESET_MODE
    #     | ClimateEntityFeature.TARGET_TEMPERATURE
    #     | ClimateEntityFeature.TURN_OFF
    #     | ClimateEntityFeature.TURN_ON
    # )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.hass = kwargs["hass"]
        self.type = "RoomControllerV2"
        self._kwargs = kwargs
        self._mode_list = kwargs["details"]["timerModes"]
        self._state_uuid = kwargs["states"]  # dictionary with state names and uuid
        self._state_values = {}

    @property
    def supported_features(self):
        _features = (
            ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
        )  # | ClimateEntityFeature.PRESET_MODE
        if self.hvac_mode == HVACMode.AUTO:
            _features |= ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
        elif self.hvac_mode in [HVACMode.HEAT, HVACMode.COOL, HVACMode.HEAT_COOL]:
            _features |= ClimateEntityFeature.TARGET_TEMPERATURE
        return _features

    def set_hvac_mode(self, hvac_mode: str) -> None:
        """Set new target hvac mode."""
        if hvac_mode == HVACMode.OFF:
            self.hass.bus.fire(
                SENDDOMAIN, dict(uuid=self.uuidAction, value=f"setOperatingMode/-1")
            )
        elif hvac_mode == HVACMode.AUTO:
            self.hass.bus.fire(
                SENDDOMAIN, dict(uuid=self.uuidAction, value=f"setOperatingMode/0")
            )
        elif hvac_mode == HVACMode.HEAT_COOL:
            self.hass.bus.fire(
                SENDDOMAIN, dict(uuid=self.uuidAction, value=f"setOperatingMode/3")
            )
        elif hvac_mode == HVACMode.HEAT:
            self.hass.bus.fire(
                SENDDOMAIN, dict(uuid=self.uuidAction, value=f"setOperatingMode/4")
            )
        elif hvac_mode == HVACMode.COOL:
            self.hass.bus.fire(
                SENDDOMAIN, dict(uuid=self.uuidAction, value=f"setOperatingMode/5")
            )
        self.schedule_update_ha_state()

    async def event_handler(self, event):
        """event_handler"""
        update = False

        for key in set(self._state_uuid.values()) & event.data.keys():
            self._state_values[key] = event.data[key]
            update = True

        if update:
            self.schedule_update_ha_state()

    def set_temperature(self, **kwargs):
        """Set new target temperature"""
        update = False

        if self.hvac_mode in [HVACMode.HEAT, HVACMode.COOL, HVACMode.HEAT_COOL]:
            self.hass.bus.fire(
                SENDDOMAIN,
                dict(
                    uuid=self.uuidAction,
                    value=f'setManualTemperature/{kwargs["temperature"]}',
                ),
            )
            update = True
        elif self.hvac_mode in HVACMode.AUTO:
            target_temp_high = kwargs.get("target_temp_high", None)
            target_temp_low = kwargs.get("target_temp_low", None)
            if target_temp_low:
                comfort_temperature = self._state_values.get(
                    self.get_key_or_value_from_states("comfortTemperature"), None
                )
                if comfort_temperature != target_temp_low:
                    self.hass.bus.fire(
                        SENDDOMAIN,
                        dict(
                            uuid=self.uuidAction,
                            value=f"setComfortTemperature/{target_temp_low}",
                        ),
                    )
                    update = True
            if target_temp_high:
                comfort_temperature_cool = self._state_values.get(
                    self.get_key_or_value_from_states("comfortTemperatureCool"), None
                )
                if comfort_temperature_cool != target_temp_high:
                    self.hass.bus.fire(
                        SENDDOMAIN,
                        dict(
                            uuid=self.uuidAction,
                            value=f"setComfortTemperatureCool/{target_temp_high}",
                        ),
                    )
                    update = True
        if update:
            self.schedule_update_ha_state()

    @property
    def hvac_mode(self) -> HVACMode | None:
        """
        # From the loxone config pdf
        activeMode
            - The active mode
                - Available modes:
                - 0 = Economy
                - 1 = Comfort temperature
                - 2 = Building protection
                - 3 = Manual
        operatingMode
            Available modes
                - 0 = Automatic, heating and cooling allowed
                - 1 = Automatic, only heating allowed
                - 2 = Automatic, only cooling allowed
                - 3 = Manual, heating and cooling allowed
                - 4 = Manual, only heating allowed
                - 5 = Manual, only cooling allowed
        :return:
        """

        active_mode = int(
            self._state_values.get(self.get_key_or_value_from_states("activeMode"), -1)
        )
        operating_mode = int(
            self._state_values.get(
                self.get_key_or_value_from_states("operatingMode"), -1
            )
        )
        # print("loxone_mode", loxone_mode, "operating_mode", operating_mode)
        if operating_mode == -1:
            return HVACMode.OFF
        if operating_mode in [0, 1]:
            return HVACMode.AUTO
        elif operating_mode in [3]:
            return HVACMode.HEAT_COOL
        elif operating_mode in [4]:
            return HVACMode.HEAT
        elif operating_mode in [5]:
            return HVACMode.COOL
        return None

    @cached_property
    def hvac_modes(self) -> list[HVACMode]:
        """Return the list of available hvac operation modes.

        Need to be a subset of HVAC_MODES.
        """
        return [
            HVACMode.AUTO,
            HVACMode.HEAT_COOL,
            HVACMode.COOL,
            HVACMode.HEAT,
            HVACMode.OFF,
        ]

    @property
    def fan_modes(self) -> list[str] | None:
        return None

    @property
    def fan_mode(self) -> str | None:
        return None

    @property
    def preset_mode(self) -> str | None:
        return None

    @property
    def preset_modes(self) -> list[str] | None:
        return None

    @property
    def swing_mode(self) -> str | None:
        return None

    @property
    def swing_modes(self) -> list[str] | None:
        return None

    @property
    def current_temperature(self) -> float | None:
        return self._state_values.get(
            self.get_key_or_value_from_states("tempActual"), None
        )

    @property
    def target_temperature(self) -> float | None:
        if self.hvac_mode in [HVACMode.HEAT, HVACMode.COOL, HVACMode.HEAT_COOL]:
            return self._state_values.get(
                self.get_key_or_value_from_states("tempTarget"), None
            )
        elif self.hvac_mode == HVACMode.OFF:
            return self._state_values.get(
                self.get_key_or_value_from_states("frostProtectTemperature"), None
            )
        else:
            return self._state_values.get(
                self.get_key_or_value_from_states("comfortTemperature"), None
            )

    @property
    def target_temperature_high(self) -> float | None:
        return self._state_values.get(
            self.get_key_or_value_from_states("comfortTemperatureCool"), None
        )

    @property
    def target_temperature_low(self) -> float | None:
        return self._state_values.get(
            self.get_key_or_value_from_states("comfortTemperature"), None
        )

    @property
    def temperature_unit(self) -> str:
        """Return the unit of measurement used by the platform."""
        if "format" in self.details:
            if self.details["format"].find("°"):
                return UnitOfTemperature.CELSIUS
            return UnitOfTemperature.FAHRENHEIT
        return UnitOfTemperature.CELSIUS

    def get_key_or_value_from_states(self, input_value) -> str | None:
        """
        Returns the key if the input is a value, or the value if the input is a key.
        If the input is not found in the dictionary, returns None.

        Args:
            input_value: The key or value to look up.

        Returns:
            The corresponding value or key, or None if not found.
        """
        if input_value in self._state_uuid:
            # Input is a key; return the corresponding value
            return self._state_uuid[input_value]
        elif input_value in self._state_uuid.values():
            # Input is a value; find and return the corresponding key
            for key, value in self._state_uuid.items():
                if value == input_value:
                    return key
        return None  # Return None if input is neither a key nor a value

    def get_mod_name_by_id(self, mood_id) -> str | None:
        """
        Returns the 'name' corresponding to the given 'id' from a list of self._mode_list.

        Args:
            mood_id: The id to search for.

        Returns:
            str: The corresponding name if found, or None if the id does not exist.
        """
        for item in self._mode_list:
            if item["id"] == mood_id:
                return item["name"]
        return None  # Return None if the id is not found

    #     self._autoMode = kwargs[CONF_HVAC_AUTO_MODE]
    #     self._stateAttribUuids = kwargs["states"]
    #     self._stateAttribValues = {}
    #     self.type = "RoomControllerV2"
    #     self._modeList = kwargs["details"]["timerModes"]
    #
    #     self._attr_device_info = get_or_create_device(
    #         self.unique_id, self.name, self.type, self.room
    #     )
    #
    # def get_mode_from_id(self, mode_id):
    #     for mode in self._modeList:
    #         if mode["id"] == mode_id:
    #             return mode["name"]
    #
    # async def event_handler(self, event):
    #     # _LOGGER.debug(f"Climate Event data: {event.data}")
    #     update = False
    #
    #     for key in set(self._stateAttribUuids.values()) & event.data.keys():
    #         self._stateAttribValues[key] = event.data[key]
    #         update = True
    #
    #     if update:
    #         self.schedule_update_ha_state()
    #
    #     # _LOGGER.debug(f"State attribs after event handling: {self._stateAttribValues}")
    #
    # def get_state_value(self, name):
    #     uuid = self._stateAttribUuids[name]
    #     return (
    #         self._stateAttribValues[uuid] if uuid in self._stateAttribValues else None
    #     )
    #
    # @property
    # def extra_state_attributes(self):
    #     """Return device specific state attributes.
    #
    #     Implemented by platform classes.
    #     """
    #     return {
    #         "is_overridden": self.is_overridden,
    #     }
    #
    # @property
    # def is_overridden(self) -> bool:
    #     # Needed because loxone uses these variables names. Simply workaround define it also here.
    #     true = True
    #     false = False
    #     null = None
    #     _override_entries = self.get_state_value("overrideEntries")
    #     if _override_entries:
    #         _override_entries = eval(_override_entries)
    #         if isinstance(_override_entries, list) and len(_override_entries) > 0:
    #             return True
    #     return False
    #
    # @property
    # def current_temperature(self):
    #     """Return the current temperature."""
    #     return self.get_state_value("tempActual")
    #
    # @property
    # def target_temperature(self) -> float | None:
    #     """Return the temperature we try to reach."""
    #     return self.get_state_value("tempActual")
    #
    # def set_temperature(self, **kwargs):
    #     """Set new target temperature"""
    #     if (
    #         self.get_state_value("operatingMode") > 2
    #     ):  # Set manual temp if any of the manual modes selected
    #         self.hass.bus.fire(
    #             SENDDOMAIN,
    #             dict(
    #                 uuid=self.uuidAction,
    #                 value=f'setManualTemperature/{kwargs["temperature"]}',
    #             ),
    #         )
    #     else:  # Set comfort temp offset otherwise
    #         new_offset = kwargs["temperature"] - self.get_state_value(
    #             "comfortTemperature"
    #         )
    #         self.hass.bus.fire(
    #             SENDDOMAIN,
    #             dict(uuid=self.uuidAction, value=f"setComfortModeTemp/{new_offset}"),
    #         )
    #
    # @property
    # def hvac_action(self) -> HVACAction | None:
    #     """Return the current HVAC action (heating, cooling)."""
    #     if self.get_state_value("prepareState") == 1:
    #         return HVACAction.PREHEATING
    #     return None  # return none due to unknown other state (HVACAction.IDLE, HVACAction.COOLING, HVACAction.HEATING)
    #
    # @property
    # def hvac_mode(self) -> HVACMode | None:
    #     """Return hvac operation ie. heat, cool mode.
    #
    #     Need to be one of HVAC_MODE_*.
    #     """
    #     return OPMODES[self.get_state_value("operatingMode")]
    #
    # @property
    # def hvac_modes(self) -> list[HVACMode]:
    #     """Return the list of available hvac operation modes.
    #
    #     Need to be a subset of HVAC_MODES.
    #     """
    #     return [HVACMode.AUTO, HVACMode.HEAT, HVACMode.HEAT_COOL, HVACMode.COOL]
    #
    # @property
    # def temperature_unit(self) -> str:
    #     """Return the unit of measurement used by the platform."""
    #     if "format" in self.details:
    #         if self.details["format"].find("°"):
    #             return UnitOfTemperature.CELSIUS
    #         return UnitOfTemperature.FAHRENHEIT
    #     return UnitOfTemperature.CELSIUS
    #
    # @property
    # def target_temperature(self) -> float | None:
    #     """Return the temperature we try to reach."""
    #
    #     return self.get_state_value("tempTarget")
    #
    # @property
    # def target_temperature_step(self) -> float | None:
    #     """Return the supported step of target temperature."""
    #     return 0.5
    #
    # @property
    # def preset_mode(self):
    #     """Return the current preset mode, e.g., home, away, temp.
    #
    #     Requires SUPPORT_PRESET_MODE.
    #     """
    #     # return self._activeMode
    #     return self.get_mode_from_id(self.get_state_value("activeMode"))
    #
    # @property
    # def preset_modes(self):
    #     """Return a list of available preset modes.
    #
    #     Requires SUPPORT_PRESET_MODE.
    #     """
    #     return [mode["name"] for mode in self._modeList]
    #
    # def set_hvac_mode(self, hvac_mode: str):
    #     """Set new target hvac mode."""
    #
    #     target_mode = (
    #         self._autoMode if hvac_mode == HVACMode.AUTO else OPMODETOLOXONE[hvac_mode]
    #     )
    #
    #     self.hass.bus.fire(
    #         SENDDOMAIN,
    #         dict(uuid=self.uuidAction, value=f"setOperatingMode/{target_mode}"),
    #     )
    #
    #     self.schedule_update_ha_state()
    #
    #     # if the mode selected is a manual one, we set the target temperature too
    #     # if (hvac_mode != HVAC_MODE_AUTO):
    #     #    self.set_temperature({"temperature": self.target_temperature})
    #
    # def set_preset_mode(self, preset_mode: str):
    #     """Set new preset mode."""
    #     mode_id = next(
    #         (mode["id"] for mode in self._modeList if mode["name"] == preset_mode), None
    #     )
    #     if mode_id is not None:
    #         self.hass.bus.fire(
    #             SENDDOMAIN, dict(uuid=self.uuidAction, value=f"override/{mode_id}")
    #         )
    #         self.schedule_update_ha_state()


# ------------------ AC CONTROL --------------------------------------------------------
class LoxoneAcControl(LoxoneEntity, ClimateEntity, ABC):
    """Representation of a ACControl Loxone device."""

    attr_supported_features = (
        ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TARGET_TEMPERATURE
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
            "uuid": self.uuidAction,
            "device_type": self.type,
            "room": self.room,
            "category": self.cat,
            "platform": "loxone",
        }

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self.get_state_value("temperature")

    def set_temperature(self, **kwargs):
        """Set new target temperature"""
        self.hass.bus.fire(
            SENDDOMAIN,
            dict(
                uuid=self.uuidAction,
                value=f'setTarget/{kwargs["targetTemperature"]}',
            ),
        )

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return hvac operation ie. heat, cool mode.

        Need to be one of HVAC_MODE_*.
        """
        if self.get_state_value("status"):
            return HVACMode.AUTO
        return HVACMode.OFF

    def set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""
        self.hass.bus.fire(
            SENDDOMAIN,
            dict(
                uuid=self.uuidAction,
                value="off" if hvac_mode == HVACMode.OFF else "on",
            ),
        )

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return the list of available hvac operation modes.

        Need to be a subset of HVAC_MODES.
        """
        return [HVACMode.OFF, HVACMode.AUTO]

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
        return 1
