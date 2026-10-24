"""ColorPickerV2 range and command encoding (Structure File, ColorPickerV2).

The spec has TWMin/TWMax in details (default 2700/6500); the Miniserver
never accepts a temp() value with a missing Kelvin part.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from homeassistant.components.light import ColorMode

from custom_components.loxone.lights.colorpickers import (
    RGBColorPicker,
    TunableWhiteLight,
)


def _picker(cls, details=None, **extra):
    sent: list = []
    picker = cls(
        uuidAction="cp-uuid",
        name="Picker",
        type="ColorPickerV2",
        room="",
        cat="",
        states={},
        details=details or {},
        async_add_devices=lambda entities: None,
        **extra,
    )
    picker.hass = SimpleNamespace(
        bus=SimpleNamespace(
            async_fire=lambda domain, data: sent.append(data["value"]),
        )
    )
    picker.async_schedule_update_ha_state = lambda: None
    return picker, sent


def test_tunable_white_range_from_details():
    picker, _ = _picker(TunableWhiteLight, details={"TWMin": 2800, "TWMax": 6000})

    assert picker._attr_min_color_temp_kelvin == 2800
    assert picker._attr_max_color_temp_kelvin == 6000


def test_tunable_white_range_defaults_to_spec():
    picker, _ = _picker(TunableWhiteLight, details={})

    assert picker._attr_min_color_temp_kelvin == 2700
    assert picker._attr_max_color_temp_kelvin == 6500


def test_tunable_white_brightness_only_sends_complete_temp():
    """Bug: first brightness-only turn_on sent ``temp(100,None)``."""
    picker, sent = _picker(TunableWhiteLight)
    picker._attr_brightness = 128

    asyncio.run(picker.async_turn_on(brightness=255))

    assert sent == ["temp(100,2700)"]


def test_tunable_white_plain_turn_on_uses_spec_command():
    """Bug: plain turn_on sent ``On`` - not a V2 command."""
    picker, sent = _picker(TunableWhiteLight)

    asyncio.run(picker.async_turn_on())

    assert sent == ["setBrightness/100"]


def test_rgb_brightness_only_with_unknown_mode_sets_brightness():
    """Bug: brightness-only turn_on with no colour state sent nothing."""
    picker, sent = _picker(RGBColorPicker)
    picker._attr_color_mode = ColorMode.UNKNOWN

    asyncio.run(picker.async_turn_on(brightness=255))

    assert sent == ["setBrightness/100"]
