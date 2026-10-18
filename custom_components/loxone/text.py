"""
Loxone Texts

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""

import logging

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import LoxoneEntity
from .const import SENDDOMAIN
from .helpers import (add_room_and_cat_to_value_values, get_all,
                      get_or_create_device)
from .miniserver import get_miniserver_from_hass

_LOGGER = logging.getLogger(__name__)

# HA rejects a text state longer than the entity's max (default 255).
MAX_TEXT_LENGTH = 255


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up Loxone Text."""
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entry."""
    miniserver = get_miniserver_from_hass(hass, config_entry)
    loxconfig = miniserver.lox_config.json
    entities = []

    for text_entity in get_all(loxconfig, ["TextInput"]):

        text_entity = add_room_and_cat_to_value_values(loxconfig, text_entity)
        text_entity.update(
            {
                "config_entry": config_entry,
            }
        )
        new_text = LoxoneText(**text_entity)
        entities.append(new_text)

    async_add_entities(entities)


class LoxoneText(LoxoneEntity, TextEntity):
    """Representation of a loxone text"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        """Initialize the Loxone text."""
        self._icon = None
        self._assumed = False
        # Unknown until the Miniserver sends the "text" state.
        self._attr_native_value = None

        self.type = "TextInput"
        self._attr_device_info = get_or_create_device(
            self.unique_id, self.name, self.type, self.room
        )

    @property
    def should_poll(self):
        """No polling needed for a demo text."""
        return False

    @property
    def icon(self):
        """Return the icon to use for device if any."""
        return self._icon

    @property
    def assumed_state(self):
        """Return if the state is based on assumptions."""
        return self._assumed

    async def event_handler(self, e):
        # The value arrives as the "text" state (spec), not under the
        # control uuid; and it has to land in ``_attr_native_value``,
        # which ``native_value`` returns - the old handler wrote an
        # unused ``_state``, so the entity always showed "".
        text_uuid = self.states.get("text")
        if text_uuid is not None and text_uuid in e.data:
            value = e.data[text_uuid]
            if not isinstance(value, str):
                value = str(value)
            self._attr_native_value = value[:MAX_TEXT_LENGTH]
            self.async_write_ha_state()

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        return {
            **self._attr_extra_state_attributes,
            "state_uuid": self.states.get("text"),
            "device_type": self.type,
        }

    async def async_set_value(self, value: str):
        """Set new value."""
        self.hass.bus.async_fire(
            SENDDOMAIN, dict(uuid=self.uuidAction, value="{}".format(value))
        )
        self.async_schedule_update_ha_state()
