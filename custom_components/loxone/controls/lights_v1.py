"""Lighting controller generation 1 (structure file spec V17).

* LightController (lighting / hotel lighting controller): ``activeScene``,
  ``sceneList`` (``1=\\"Scene 1\\",2=\\"Scene 2\\"``); commands ``on``
  (scene 9), ``off`` (scene 0), ``{sceneNumber}``, ``plus``, ``minus``.
  Sub-controls: Switch, Dimmer / EIBDimmer and ColorPicker.
* ColorPicker (only a sub-control of the LightController): ``color`` as
  ``hsv(h,s,v)`` or ``lumitech(brightness,kelvin)``; commands ``on``,
  ``off``, ``hsv(...)``, ``lumitech(...)``.
* LightsceneRGB (RGB lighting controller): ``details.sceneList``,
  ``activeScene``, ``color``; commands ``on``, ``off``, ``{sceneNumber}``.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.const import Platform

from ..helpers import get_or_create_device
from ..lights.dimmer import EIBDimmer, LoxoneDimmer
from ..lights.switch import LoxoneLightSwitch
from . import SetupContext, register
from .base import ControlEntity, ControlButton, to_int

_LOGGER = logging.getLogger(__name__)

# sceneList: 1=\"Szene1\",2=\"Szene2\",7=\"Szene7\"
_SCENE_RE = re.compile(r'(\d+)=\\?"((?:[^"\\]|\\.)*?)\\?"')
_COLOR_RE = re.compile(r"^\s*(hsv|lumitech)\s*\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*(?:,\s*([-\d.]+)\s*)?\)\s*$")

LUMITECH_MIN_KELVIN = 2700
LUMITECH_MAX_KELVIN = 6500


def parse_scene_list(text: Any) -> dict[int, str]:
    """Scene number -> name from the LightController ``sceneList`` text."""
    if not isinstance(text, str):
        return {}
    return {int(number): name for number, name in _SCENE_RE.findall(text)}


def parse_color(text: Any) -> tuple[str, tuple[float, ...]] | None:
    """``hsv(h,s,v)`` or ``lumitech(brightness,kelvin)``; None otherwise."""
    if not isinstance(text, str):
        return None
    match = _COLOR_RE.match(text)
    if match is None:
        return None
    kind = match.group(1)
    values = tuple(float(v) for v in match.groups()[1:] if v is not None)
    if (kind == "hsv" and len(values) != 3) or (kind == "lumitech" and len(values) != 2):
        return None
    return kind, values


def _to_hass_brightness(percent: float) -> int:
    return round(max(0.0, min(100.0, percent)) * 255 / 100)


def _to_lox_percent(brightness: float) -> int:
    return round(max(0.0, min(255.0, brightness)) * 100 / 255)


class SceneLight(ControlEntity, LightEntity):
    """A light whose effects are the scenes of a lighting controller."""

    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_icon = "mdi:lightbulb-group"

    def __init__(self, control: dict, watch: tuple[str, ...]) -> None:
        super().__init__(control, watch=watch)
        self._scenes: dict[int, str] = {}
        self._active: int | None = None

    @property
    def is_on(self) -> bool | None:
        return None if self._active is None else self._active != 0

    @property
    def effect_list(self) -> list[str]:
        return list(self._scenes.values())

    @property
    def effect(self) -> str | None:
        return self._scenes.get(self._active) if self._active else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        effect = kwargs.get(ATTR_EFFECT)
        number = next((n for n, name in self._scenes.items() if name == effect), None)
        self.send(str(number) if number is not None else "on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.send("off")

    def _extra_attributes(self) -> dict[str, Any]:
        return {"active_scene": self._active, "scenes": self._scenes}


class LightControllerLight(SceneLight):
    """LightController: scenes from the ``sceneList`` state."""

    def __init__(self, control: dict) -> None:
        super().__init__(control, watch=("activeScene", "sceneList"))

    def _handle_states(self, changes: dict[str, Any]) -> None:
        if "sceneList" in changes:
            self._scenes = parse_scene_list(changes["sceneList"])
        if "activeScene" in changes:
            self._active = to_int(changes["activeScene"])

    def _extra_attributes(self) -> dict[str, Any]:
        return {**super()._extra_attributes(), "movement_scene": self.details.get("movementScene")}


class LightsceneRGBLight(SceneLight):
    """LightsceneRGB: scenes from ``details.sceneList``, colour as attribute.

    The scene list holds the names of scenes 1..n (scene 0 is "all off").
    The colour can only be learned into a scene, not set directly, so the
    light stays on/off with scene effects.
    """

    def __init__(self, control: dict) -> None:
        super().__init__(control, watch=("activeScene", "color"))
        names = self.details.get("sceneList") or []
        self._scenes = {index: str(name) for index, name in enumerate(names, start=1)}
        self._color: str | None = None

    def _handle_states(self, changes: dict[str, Any]) -> None:
        if "activeScene" in changes:
            self._active = to_int(changes["activeScene"])
        if "color" in changes:
            self._color = changes["color"] if isinstance(changes["color"], str) else None

    def _extra_attributes(self) -> dict[str, Any]:
        attributes = super()._extra_attributes()
        parsed = parse_color(self._color)
        attributes["scene_color"] = self._color
        if parsed and parsed[0] == "hsv":
            attributes["scene_hs_color"] = (parsed[1][0], parsed[1][1])
        return attributes


class ColorPickerV1Light(ControlEntity, LightEntity):
    """ColorPicker (generation 1) of a LightController: RGB or Lumitech."""

    def __init__(self, control: dict, controller: dict, *, enabled_default: bool) -> None:
        picker = dict(control)
        picker.setdefault("room", controller.get("room", ""))
        picker.setdefault("cat", controller.get("cat", ""))
        picker["name"] = f"{controller.get('name', '')}-{control.get('name', '')}"
        super().__init__(picker, watch=("color",), enabled_default=enabled_default)
        # All entities of a lighting controller share its device.
        self._attr_device_info = get_or_create_device(
            controller["uuidAction"], controller.get("name", ""), controller.get("type", ""), controller.get("room", "")
        )
        self.lumitech = (self.details.get("pickerType") or "Rgb") == "Lumitech"
        if self.lumitech:
            self._attr_supported_color_modes = {ColorMode.COLOR_TEMP}
            self._attr_color_mode = ColorMode.COLOR_TEMP
            self._attr_min_color_temp_kelvin = LUMITECH_MIN_KELVIN
            self._attr_max_color_temp_kelvin = LUMITECH_MAX_KELVIN
        else:
            self._attr_supported_color_modes = {ColorMode.HS}
            self._attr_color_mode = ColorMode.HS
        self._attr_is_on = None
        self._attr_brightness = None
        self._attr_hs_color = None
        self._attr_color_temp_kelvin = None

    def _handle_states(self, changes: dict[str, Any]) -> None:
        parsed = parse_color(changes["color"])
        if parsed is None:
            _LOGGER.debug("Ignoring color %r of %s", changes["color"], self.name)
            return
        kind, values = parsed
        if kind == "hsv":
            hue, saturation, value = values
            self._attr_hs_color = (hue, saturation)
            brightness = value
        else:
            brightness, kelvin = values
            self._attr_color_temp_kelvin = int(kelvin)
        self._attr_brightness = _to_hass_brightness(brightness)
        self._attr_is_on = brightness > 0

    async def async_turn_on(self, **kwargs: Any) -> None:
        if not any(key in kwargs for key in (ATTR_BRIGHTNESS, ATTR_HS_COLOR, ATTR_COLOR_TEMP_KELVIN)):
            self.send("on")
            return
        brightness = _to_lox_percent(kwargs.get(ATTR_BRIGHTNESS, self._attr_brightness or 255))
        if self.lumitech:
            kelvin = int(kwargs.get(ATTR_COLOR_TEMP_KELVIN, self._attr_color_temp_kelvin or LUMITECH_MIN_KELVIN))
            self.send(f"lumitech({brightness},{kelvin})")
        else:
            hue, saturation = kwargs.get(ATTR_HS_COLOR, self._attr_hs_color or (0, 0))
            self.send(f"hsv({round(hue)},{round(saturation)},{brightness})")

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.send("off")


def _sub_controls(control: dict) -> list[dict]:
    return [sub for sub in (control.get("subControls") or {}).values() if isinstance(sub, dict)]


@register(Platform.LIGHT, "LightController")
def _light_controller(ctx: SetupContext, control: dict) -> list:
    entities: list = [LightControllerLight(control)]
    enabled_default = ctx.config_entry.options.get("generate_lightcontroller_subcontrols", False)
    for sub in _sub_controls(control):
        kwargs = {
            **sub,
            "room": control.get("room", ""),
            "cat": control.get("cat", ""),
            "lightcontroller_id": control["uuidAction"],
            "lightcontroller_name": control.get("name"),
            "async_add_devices": ctx.async_add_entities,
            "enabled_default": enabled_default,
        }
        sub_type = sub.get("type")
        if sub_type == "Switch":
            entities.append(LoxoneLightSwitch(**kwargs))
        elif sub_type == "Dimmer":
            entities.append(LoxoneDimmer(**kwargs))
        elif sub_type == "EIBDimmer":
            entities.append(EIBDimmer(**kwargs))
        elif sub_type == "ColorPicker":
            entities.append(ColorPickerV1Light(sub, control, enabled_default=enabled_default))
        else:
            _LOGGER.debug("LightController %s: sub-control type %s not handled", control.get("name"), sub_type)
    return entities


@register(Platform.BUTTON, "LightController")
def _light_controller_buttons(_ctx: SetupContext, control: dict) -> list:
    # plus / minus step through the scenes (since Miniserver 8.1).
    return [
        ControlButton(control, "plus", "Next Scene", icon="mdi:skip-next"),
        ControlButton(control, "minus", "Previous Scene", icon="mdi:skip-previous"),
    ]


@register(Platform.LIGHT, "LightsceneRGB")
def _lightscene_rgb(_ctx: SetupContext, control: dict) -> list:
    return [LightsceneRGBLight(control)]
