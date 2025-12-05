"""
Loxone Scenes

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""

import logging

from homeassistant.components.scene import Scene
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
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
    """Set up Scenes after all other platforms are loaded."""
    delay_scene = config_entry.options.get(CONF_SCENE_GEN_DELAY, DEFAULT_DELAY_SCENE)
    create_scene = config_entry.options.get(CONF_SCENE_GEN, False)

    if not create_scene:
        return True

    async def gen_scenes():
        """Generate scenes from light entities."""
        _LOGGER.debug("Loading scenes...")
        scenes = []

        # Wait for light platform to be ready
        if "light" not in hass.data:
            _LOGGER.warning("Light platform not ready, skipping scene generation")
            return

        entity_ids = hass.states.async_entity_ids("light")

        for entity_id in entity_ids:
            state = hass.states.get(entity_id)
            if not state:
                continue

            att = state.attributes
            if att.get("platform") != DOMAIN:
                continue

            entity = hass.data["light"].get_entity(entity_id)
            if not entity or entity.device_class != "LightControllerV2":
                continue

            for effect in entity.effect_list:
                mood_id = entity.get_id_by_moodname(effect)
                uuid = entity.uuidAction
                scenes.append(
                    Loxonelightscene(
                        f"{entity.name}-{effect}",
                        mood_id,
                        uuid,
                        entity.unique_id,
                    )
                )

        if scenes:
            async_add_entities(scenes)
            _LOGGER.info(f"Generated {len(scenes)} scenes")
        else:
            _LOGGER.warning("No scenes generated")

    # Wait for platforms to be ready and then generate scenes
    hass.loop.call_later(delay_scene, lambda: hass.async_create_task(gen_scenes()))

    return True


class Loxonelightscene(Scene):
    """Representation of a Loxone light scene."""

    def __init__(self, name, mood_id, uuid, light_controller_id):
        """Initialize the scene."""
        self.name = name
        self.mood_id = mood_id
        self.uuidAction = uuid
        self._light_controller_id = light_controller_id

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._light_controller_id}-{self.mood_id}"

    async def async_activate(self, **kwargs):
        """Activate scene. Try to get entities into requested state."""
        self.hass.bus.async_fire(
            SENDDOMAIN,
            {"uuid": self.uuidAction, "value": f"changeTo/{self.mood_id}"},
        )
