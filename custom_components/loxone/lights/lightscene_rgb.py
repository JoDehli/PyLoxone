"""Loxone RGB Lighting Controller (structure-file type ``LightsceneRGB``).

Spec facts (Structure File, LightsceneRGB):
- commands: ``on``, ``off`` (scene 0, all off) and ``{sceneNumber}``
- states: ``activeScene``, ``color`` (``hsv(h,s,v)``) and, not in the
  spec but sent by the Miniserver, ``red`` / ``green`` / ``blue``

Observed on a Miniserver Gen 2:
- ``details.sceneList`` is a JSON object keyed by scene number, not an array
- ``hsv(h,s,v)`` is rejected (response value 0), so the colour cannot be
  set over the API; it is only reported as state attributes
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_EFFECT,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)

from .. import LoxoneEntity
from ..const import SENDDOMAIN
from ..helpers import get_or_create_device

_LOGGER = logging.getLogger(__name__)

# Scene number that means "all off" (Structure File, LightsceneRGB).
OFF_SCENE = 0

# Colour channel states, reported read-only as state attributes.
RGB_CHANNELS = ("red", "green", "blue")


class LoxoneLightsceneRGB(LoxoneEntity, LightEntity):
    """Representation of a Loxone RGB Lighting Controller.

    The block accepts only on, off and scene numbers over the API, so the
    scenes are exposed as effects and the colour is reported read-only.
    """

    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_icon = "mdi:palette"
    _attr_is_on: bool | None = None
    _attr_available = False

    def __init__(self, **kwargs):
        """Initialize the RGB Lighting Controller from its structure-file entry."""
        super().__init__(**kwargs)
        self._attr_unique_id = self.uuidAction
        self._active_scene: int | None = None
        self._color: str | None = None
        self._channels: dict[str, Any] = {}
        self._scenes = self._parse_scene_list(kwargs.get("details", {}).get("sceneList"))

        self.type = "LightsceneRGB"
        self._attr_device_info = get_or_create_device(self.unique_id, self.name, self.type, self.room)

    @staticmethod
    def _parse_scene_list(scene_list: Any) -> dict[int, str]:
        """Return the scenes as ``{scene number: name}``."""
        if not isinstance(scene_list, dict):
            # The spec describes an array, but its numbering is undefined; only the observed object is supported.
            if scene_list:
                _LOGGER.warning("Unsupported sceneList format: %r", scene_list)
            return {}

        scenes = {}
        for number, name in scene_list.items():
            try:
                scenes[int(number)] = str(name)
            except (TypeError, ValueError):
                _LOGGER.warning("Ignoring scene with invalid number %r (%r)", number, name)
        return scenes

    def _scene_number(self, name: str) -> int | None:
        """Return the scene number for a scene name, or None if unknown."""
        for number, scene_name in self._scenes.items():
            if scene_name == name:
                return number
        return None

    @property
    def effect_list(self) -> list[str]:
        """Return the scene names, sorted alphabetically."""
        return sorted(self._scenes.values(), key=str.casefold)

    @property
    def effect(self) -> str | None:
        """Return the name of the active scene, or None if off or unknown."""
        if self._active_scene in (None, OFF_SCENE):
            return None
        return self._scenes.get(self._active_scene)

    def _send(self, command: str) -> None:
        """Send a command to the RGB Lighting Controller."""
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value=command))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on, or activate the scene given as effect."""
        if ATTR_EFFECT in kwargs:
            number = self._scene_number(kwargs[ATTR_EFFECT])
            if number is None:
                _LOGGER.warning("Unknown scene %r for %s", kwargs[ATTR_EFFECT], self.name)
                return
            self._send(str(number))
        else:
            self._send("on")
        self.async_schedule_update_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off (scene 0)."""
        self._send("off")
        self.async_schedule_update_ha_state()

    async def event_handler(self, event):
        """Update the state from Miniserver state events."""
        request_update = False

        scene_uuid = self.states.get("activeScene")
        if scene_uuid and scene_uuid in event.data:
            try:
                self._active_scene = int(float(event.data[scene_uuid]))
            except (TypeError, ValueError):
                _LOGGER.warning("Ignoring invalid activeScene of %s: %r", self.name, event.data[scene_uuid])
            else:
                self._attr_is_on = self._active_scene != OFF_SCENE
                self._attr_available = True
                request_update = True

        color_uuid = self.states.get("color")
        if color_uuid and color_uuid in event.data:
            self._color = event.data[color_uuid]
            request_update = True

        for channel in RGB_CHANNELS:
            channel_uuid = self.states.get(channel)
            if channel_uuid and channel_uuid in event.data:
                self._channels[channel] = event.data[channel_uuid]
                # The scale of these states is not in the spec; log raw values to verify it.
                _LOGGER.debug("%s %s raw value: %r", self.name, channel, event.data[channel_uuid])
                request_update = True

        if request_update:
            self.async_schedule_update_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the active scene and the read-only colour of the block."""
        attributes = {
            **self._attr_extra_state_attributes,
            "device_type": self.type,
            "active_scene": self._active_scene,
            **self._channels,
        }
        if self._color is not None:
            attributes["color"] = self._color
        return attributes
