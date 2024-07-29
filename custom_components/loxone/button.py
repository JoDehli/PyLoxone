"""
Loxone Buttons

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import LoxoneEntity
from .const import DOMAIN, SENDDOMAIN
from .helpers import (get_all, get_cat_name_from_cat_uuid,
                      get_room_name_from_room_uuid)
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
        button_entity.update(
            {
                "room": get_room_name_from_room_uuid(
                    loxconfig, button_entity.get("room", "")
                ),
                "cat": get_cat_name_from_cat_uuid(
                    loxconfig, button_entity.get("cat", "")
                ),
                "config_entry": config_entry,
            }
        )
        entities.append(LoxoneButton(**button_entity))

    async_add_entities(entities)


class LoxoneButton(LoxoneEntity, ButtonEntity):
    """Representation of a Loxone pushbutton."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._attr_icon = None

    @property
    def icon(self):
        """Return the icon to use for device if any."""
        return self._attr_icon

    def press(self, **kwargs):
        """Press the button."""
        self.hass.bus.fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="pulse"))
        self.schedule_update_ha_state()

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes."""
        return {
            "uuid": self.uuidAction,
            "state_uuid": self.states["active"],
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
