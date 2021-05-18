"""
Loxone Scenes

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""

import logging

from homeassistant.components.scene import Scene
from homeassistant.helpers.entity_platform import async_call_later

from .const import CONF_SCENE_GEN,  DOMAIN, SENDDOMAIN, DEFAULT_DELAY_SCENE
from .miniserver import get_miniserver_from_config

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_devices):
    """Set up Scenes."""
    delay_scene = config_entry.options.get("generate_scenes_delay", DEFAULT_DELAY_SCENE)

    miniserver = get_miniserver_from_config(hass, hass.data[DOMAIN])
    if miniserver is None:
        return False

    async def gen_scenes(_):
        devices = []
        entity_ids = hass.states.async_entity_ids("LIGHT")
        for _ in entity_ids:
            state = hass.states.get(_)
            att = state.attributes
            if "plattform" in att and att["plattform"] == DOMAIN:
                entity = hass.data["light"].get_entity(state.entity_id)
                if entity.device_class == "LightControllerV2":
                    for effect in entity.effect_list:
                        mood_id = entity.get_id_by_moodname(effect)
                        uuid = entity.uuidAction
                        devices.append(
                            Loxonelightscene(
                                "{}-{}".format(entity.name, effect), mood_id, uuid
                            )
                        )
        async_add_devices(devices, True)

    if miniserver.config_entry.options.get(CONF_SCENE_GEN, False):
        async_call_later(hass, delay_scene, gen_scenes)

    return True


async def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    """Set up Scenes."""
    return True


class Loxonelightscene(Scene):
    def __init__(self, name, mood_id, uuid):
        self._name = name
        self.mood_id = mood_id
        self.uuidAction = uuid

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
