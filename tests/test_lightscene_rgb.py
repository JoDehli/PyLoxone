"""RGB Lighting Controller (Structure File, LightsceneRGB).

Spec: commands ``on``, ``off`` and ``{sceneNumber}``; scene 0 is all off.
Observed: ``details.sceneList`` is an object keyed by scene number.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from custom_components.loxone.lights.lightscene_rgb import LoxoneLightsceneRGB

STATES = {
    "activeScene": "scene-uuid",
    "color": "color-uuid",
    "red": "red-uuid",
    "green": "green-uuid",
    "blue": "blue-uuid",
}


def _lightscene(scene_list=None) -> tuple:
    sent: list = []
    if scene_list is None:
        scene_list = {"1": "Purple", "2": "Red", "3": "Green", "4": "Blue"}
    lightscene = LoxoneLightsceneRGB(
        uuidAction="rgb-uuid",
        name="Test RGB",
        type="LightsceneRGB",
        room="",
        cat="",
        states=dict(STATES),
        details={"sceneList": scene_list},
    )
    lightscene.hass = SimpleNamespace(
        bus=SimpleNamespace(
            async_fire=lambda domain, data: sent.append(data["value"]),
        )
    )
    lightscene.async_schedule_update_ha_state = lambda: None
    return lightscene, sent


def _event(lightscene, data: dict) -> None:
    asyncio.run(lightscene.event_handler(SimpleNamespace(data=data)))


# --- scenes as effects -------------------------------------------------------


def test_effect_list_is_sorted_alphabetically():
    lightscene, _ = _lightscene()

    assert lightscene.effect_list == ["Blue", "Green", "Purple", "Red"]


def test_effect_list_sort_ignores_case():
    lightscene, _ = _lightscene({"1": "red", "2": "Blue"})

    assert lightscene.effect_list == ["Blue", "red"]


def test_empty_or_unsupported_scene_list_gives_no_effects():
    assert _lightscene({})[0].effect_list == []
    assert _lightscene(["Purple"])[0].effect_list == []


def test_invalid_scene_number_is_skipped():
    lightscene, _ = _lightscene({"1": "Purple", "x": "Broken"})

    assert lightscene.effect_list == ["Purple"]


# --- commands -----------------------------------------------------------------


def test_effect_sends_scene_number():
    lightscene, sent = _lightscene()

    asyncio.run(lightscene.async_turn_on(effect="Red"))

    assert sent == ["2"]


def test_unknown_effect_sends_nothing():
    lightscene, sent = _lightscene()

    asyncio.run(lightscene.async_turn_on(effect="Yellow"))

    assert sent == []


def test_plain_turn_on_without_known_scene_sends_on():
    lightscene, sent = _lightscene()

    asyncio.run(lightscene.async_turn_on())

    assert sent == ["on"]


def test_plain_turn_on_restores_last_scene():
    """``on`` switches to full white, so the last scene is restored instead."""
    lightscene, sent = _lightscene()
    _event(lightscene, {"scene-uuid": 2.0})
    _event(lightscene, {"scene-uuid": 0.0})

    asyncio.run(lightscene.async_turn_on())

    assert sent == ["2"]


def test_plain_turn_on_when_already_on_sends_nothing():
    lightscene, sent = _lightscene()
    _event(lightscene, {"scene-uuid": 3.0})

    asyncio.run(lightscene.async_turn_on())

    assert sent == []


def test_turn_off_sends_off():
    lightscene, sent = _lightscene()

    asyncio.run(lightscene.async_turn_off())

    assert sent == ["off"]


# --- state --------------------------------------------------------------------


def test_unavailable_until_first_active_scene():
    lightscene, _ = _lightscene()

    assert lightscene._attr_available is False
    assert lightscene.is_on is None

    _event(lightscene, {"scene-uuid": 0.0})

    assert lightscene._attr_available is True


def test_active_scene_sets_on_and_effect():
    lightscene, _ = _lightscene()

    _event(lightscene, {"scene-uuid": 3.0})

    assert lightscene.is_on is True
    assert lightscene.effect == "Green"


def test_scene_zero_is_off_without_effect():
    lightscene, _ = _lightscene()

    _event(lightscene, {"scene-uuid": 0.0})

    assert lightscene.is_on is False
    assert lightscene.effect is None


def test_scene_not_in_list_is_on_without_effect():
    lightscene, _ = _lightscene()

    _event(lightscene, {"scene-uuid": 9.0})

    assert lightscene.is_on is True
    assert lightscene.effect is None


def test_invalid_active_scene_is_ignored():
    lightscene, _ = _lightscene()
    _event(lightscene, {"scene-uuid": 2.0})

    _event(lightscene, {"scene-uuid": "garbage"})

    assert lightscene.effect == "Red"


def test_colour_is_reported_read_only_in_attributes():
    lightscene, _ = _lightscene()

    _event(
        lightscene,
        {
            "scene-uuid": 4.0,
            "color-uuid": "hsv(225,100,100)",
            "red-uuid": 0.0,
            "green-uuid": 33.0,
            "blue-uuid": 100.0,
        },
    )

    attributes = lightscene.extra_state_attributes
    assert attributes["active_scene"] == 4
    assert attributes["color"] == "hsv(225,100,100)"
    assert (attributes["red"], attributes["green"], attributes["blue"]) == (0.0, 33.0, 100.0)
    assert lightscene.supported_color_modes == {"onoff"}
