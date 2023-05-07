"""
Loxone Scenes

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""

import logging

from homeassistant.components.scene import Scene
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import (AddEntitiesCallback,
                                                   async_call_later)
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (CONF_SCENE_GEN, CONF_SCENE_GEN_DELAY, DEFAULT_DELAY_SCENE,
                    DOMAIN, SENDDOMAIN)

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up Scenes."""
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Scenes."""
    delay_scene = config_entry.options.get(CONF_SCENE_GEN_DELAY, DEFAULT_DELAY_SCENE)
    create_scene = config_entry.options.get(CONF_SCENE_GEN, False)

    async def gen_scenes(_):
        devices = []
        entity_ids = hass.states.async_entity_ids("LIGHT")
        for _ in entity_ids:
            state = hass.states.get(_)
            att = state.attributes
            if "platform" in att and att["platform"] == DOMAIN:
                entity = hass.data["light"].get_entity(state.entity_id)
                if entity.device_class == "LightControllerV2":
                    for effect in entity.effect_list:
                        mood_id = entity.get_id_by_moodname(effect)
                        uuid = entity.uuidAction
                        devices.append(
                            Loxonelightscene(
                                "{}-{}".format(entity.name, effect),
                                mood_id,
                                uuid,
                                entity.unique_id,
                            )
                        )
        async_add_entities(devices)

    if create_scene:
        async_call_later(hass, delay_scene, gen_scenes)

    return True


class Loxonelightscene(Scene):
    def __init__(self, name, mood_id, uuid, light_controller_id):
        self._name = name
        self.mood_id = mood_id
        self.uuidAction = uuid
        self._light_controller_id = light_controller_id

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._light_controller_id}-{self.mood_id}"

    @property
    def name(self):
        """Return the name of the scene."""
        return self._name

    def activate(self):
        """Activate scene. Try to get entities into requested state."""
        self.hass.bus.async_fire(
            SENDDOMAIN,
            dict(uuid=self.uuidAction, value="changeTo/{}".format(self.mood_id)),
        )
