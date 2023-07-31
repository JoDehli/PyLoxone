"""
Loxone climate

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""

import logging
from abc import ABC

from homeassistant.components.climate import (PLATFORM_SCHEMA,
                                              SUPPORT_PRESET_MODE,
                                              SUPPORT_TARGET_TEMPERATURE,
                                              ClimateEntity)
from homeassistant.components.climate.const import (HVAC_MODE_AUTO,
                                                    HVAC_MODE_COOL,
                                                    HVAC_MODE_HEAT,
                                                    HVAC_MODE_HEAT_COOL,
                                                    HVAC_MODE_OFF)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from voluptuous import All, Optional, Range

from . import LoxoneEntity, get_miniserver_from_hass
from .const import CONF_HVAC_AUTO_MODE, DOMAIN, SENDDOMAIN
from .helpers import (get_all, get_cat_name_from_cat_uuid,
                      get_room_name_from_room_uuid)

_LOGGER = logging.getLogger(__name__)

OPMODES = {
    None: HVAC_MODE_OFF,
    0: HVAC_MODE_AUTO,
    1: HVAC_MODE_AUTO,
    2: HVAC_MODE_AUTO,
    3: HVAC_MODE_HEAT_COOL,
    4: HVAC_MODE_HEAT,
    5: HVAC_MODE_COOL,
}

OPMODETOLOXONE = {HVAC_MODE_HEAT_COOL: 3, HVAC_MODE_HEAT: 4, HVAC_MODE_COOL: 5}

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
    loxconfig = miniserver.structure
    devices = []

    for climate in get_all(loxconfig, "IRoomControllerV2"):
        climate.update(
            {
                "hass": hass,
                "room": get_room_name_from_room_uuid(
                    loxconfig, climate.get("room", "")
                ),
                "cat": get_cat_name_from_cat_uuid(loxconfig, climate.get("cat", "")),
                CONF_HVAC_AUTO_MODE: 0,
                "config_entry": config_entry,
            }
        )

        new_thermostat = LoxoneRoomControllerV2(**climate)
        devices.append(new_thermostat)

    async_add_entities(devices)


class LoxoneRoomControllerV2(LoxoneEntity, ClimateEntity, ABC):
    """Loxone room controller"""

    def __init__(self, **kwargs):
        _LOGGER.debug(f"Input: {kwargs}")
        LoxoneEntity.__init__(self, **kwargs)
        self.hass = kwargs["hass"]
        self._autoMode = kwargs[CONF_HVAC_AUTO_MODE]

        self._stateAttribUuids = kwargs["states"]
        self._stateAttribValues = {}

        self._modeList = kwargs["details"]["timerModes"]

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.unique_id)},
            name=f"{DOMAIN} {self.name}",
            manufacturer="Loxone",
            suggested_area=self.room,
            model="RoomControllerV2"
        )

    def get_mode_from_id(self, mode_id):
        for mode in self._modeList:
            if mode["id"] == mode_id:
                return mode["name"]

    @property
    def supported_features(self):
        """Flag supported features."""
        return SUPPORT_PRESET_MODE | SUPPORT_TARGET_TEMPERATURE

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        return self.type

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
            "device_typ": self.type,
            "room": self.room,
            "category": self.cat,
            "platform": "loxone",
            "is_overridden": self.is_overridden,
        }

    @property
    def is_overridden(self) -> bool:
        # Needed because loxone uses these variables names. Simply workaround define it also here.
        true = True
        false = False
        null = None
        _override_entries = self.get_state_value("overrideEntries")
        if _override_entries:
            _override_entries = eval(_override_entries)
            if isinstance(_override_entries, list) and len(_override_entries) > 0:
                return True
        return False

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self.get_state_value("tempActual")

    def set_temperature(self, **kwargs):
        """Set new target temperature"""
        if (
            self.get_state_value("operatingMode") > 2
        ):  # Set manual temp if any of the manual modes selected
            self.hass.bus.async_fire(
                SENDDOMAIN,
                dict(
                    uuid=self.uuidAction,
                    value=f'setManualTemperature/{kwargs["temperature"]}',
                ),
            )
        else:  # Set comfort temp offset otherwise
            new_offset = kwargs["temperature"] - self.get_state_value(
                "comfortTemperature"
            )
            self.hass.bus.async_fire(
                SENDDOMAIN,
                dict(uuid=self.uuidAction, value=f"setComfortModeTemp/{new_offset}"),
            )

    @property
    def hvac_mode(self):
        """Return hvac operation ie. heat, cool mode.

        Need to be one of HVAC_MODE_*.
        """
        return OPMODES[self.get_state_value("operatingMode")]

    @property
    def hvac_modes(self):
        """Return the list of available hvac operation modes.

        Need to be a subset of HVAC_MODES.
        """
        return [HVAC_MODE_AUTO, HVAC_MODE_HEAT, HVAC_MODE_HEAT_COOL, HVAC_MODE_COOL]

    @property
    def temperature_unit(self):
        """Return the unit of measurement used by the platform."""
        if "format" in self.details:
            if self.details["format"].find("°"):
                return UnitOfTemperature.CELSIUS
            return UnitOfTemperature.FAHRENHEIT
        return UnitOfTemperature.CELSIUS

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""

        return self.get_state_value("tempTarget")

    @property
    def target_temperature_step(self):
        """Return the supported step of target temperature."""
        return 0.5

    @property
    def preset_mode(self):
        """Return the current preset mode, e.g., home, away, temp.

        Requires SUPPORT_PRESET_MODE.
        """
        # return self._activeMode
        return self.get_mode_from_id(self.get_state_value("activeMode"))

    @property
    def preset_modes(self):
        """Return a list of available preset modes.

        Requires SUPPORT_PRESET_MODE.
        """
        return [mode["name"] for mode in self._modeList]

    def set_hvac_mode(self, hvac_mode: str):
        """Set new target hvac mode."""

        target_mode = (
            self._autoMode if hvac_mode == HVAC_MODE_AUTO else OPMODETOLOXONE[hvac_mode]
        )

        self.hass.bus.async_fire(
            SENDDOMAIN,
            dict(uuid=self.uuidAction, value=f"setOperatingMode/{target_mode}"),
        )

        self.schedule_update_ha_state()

        # if the mode selected is a manual one, we set the target temperature too
        # if (hvac_mode != HVAC_MODE_AUTO):
        #    self.set_temperature({"temperature": self.target_temperature})

    def set_preset_mode(self, preset_mode: str):
        """Set new preset mode."""
        mode_id = next(
            (mode["id"] for mode in self._modeList if mode["name"] == preset_mode), None
        )
        if mode_id is not None:
            self.hass.bus.async_fire(
                SENDDOMAIN, dict(uuid=self.uuidAction, value=f"override/{mode_id}")
            )
            self.schedule_update_ha_state()

