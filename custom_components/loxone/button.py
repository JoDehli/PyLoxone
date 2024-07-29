"""
Loxone Buttons

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import LoxoneEntity
from .const import DOMAIN, SENDDOMAIN
from .helpers import add_room_and_cat_to_value_values, get_all
from .miniserver import get_miniserver_from_hass

_LOGGER = logging.getLogger(__name__)

async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up Loxone Button."""
    return True

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entry."""
    miniserver = get_miniserver_from_hass(hass)
    loxconfig = miniserver.lox_config.json
    entities = []

    for button_entity in get_all(loxconfig, ["Pushbutton"]):
        button_entity = add_room_and_cat_to_value_values(loxconfig, button_entity)
        entities.append(LoxoneButton("pulse", **button_entity))

    for button_entity in get_all(loxconfig, "EnergyManager2"):
        button_entity = add_room_and_cat_to_value_values(loxconfig, button_entity)
        entities.append(LoxoneButton("manage", **button_entity))

    async_add_entities(entities)

class LoxoneButton(LoxoneEntity, ButtonEntity):
    """Representation of a Loxone pushbutton."""

    def __init__(self, value, **kwargs):
        super().__init__(**kwargs)
        self.value = value
        self._attr_name = "Check inputs"
        self._attr_icon = None

    def press(self):
        """Press the button."""
        self.hass.bus.fire(SENDDOMAIN, dict(uuid=self.uuidAction, value=self.value))
        self.schedule_update_ha_state()

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes."""
        return {
            "uuid": self.uuidAction,
            "room": self.room,
            "category": self.cat,
            "device_typ": self.type,
            "platform": "loxone",
        }

    @property
    def device_info(self):
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.unique_id)},
            name=self.name,
            manufacturer="Loxone",
            model=self.type,
            suggested_area=self.room,
        )
