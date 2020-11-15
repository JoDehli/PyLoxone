import logging

from homeassistant.components.scene import Scene
from homeassistant.const import (
    CONF_VALUE_TEMPLATE)
from homeassistant.helpers.entity_platform import async_call_later
from homeassistant.core import callback

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = 'Loxone Scene'
DEFAULT_FORCE_UPDATE = False

CONF_UUID = "uuid"
DOMAIN = 'loxone'
SENDDOMAIN = "loxone_send"
CONF_SCENE_GEN = "generate_scenes"

from homeassistant.loader import bind_hass


async def async_setup_entry(hass, config_entry, async_add_devices):
    """Set up Scenes."""
    return True


async def async_setup_platform(hass, config, async_add_devices,
                               discovery_info=None):
    """Set up Scenes."""
    if discovery_info is None:
        return
    value_template = config.get(CONF_VALUE_TEMPLATE)
    if value_template is not None:
        value_template.hass = hass

    async def gen_scenes(_):
        devices = []
        entity_ids = hass.states.async_entity_ids("LIGHT")
        for _ in entity_ids:
            state = hass.states.get(_)
            att = state.attributes
            if "plattform" in att and att['plattform'] == DOMAIN:
                entity = hass.data['light'].get_entity(state.entity_id)
                if entity.device_class == "LightControllerV2":
                    for effect in entity.effect_list:
                        mood_id = entity.get_id_by_moodname(effect)
                        uuid = entity.uuidAction
                        devices.append(Loxonelightscene("{}-{}".format(entity.name, effect), mood_id, uuid))
        async_add_devices(devices)

    if hass.data[DOMAIN].get(CONF_SCENE_GEN):
        async_call_later(hass, 0.5, gen_scenes)
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
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="changeTo/{}".format(self.mood_id)))
