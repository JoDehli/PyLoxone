"""LightController, ColorPicker (generation 1) and LightsceneRGB (spec V17)."""

from __future__ import annotations

import pytest
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN

from _controls import control, entity_id, state, structure_with, uuid_for
from custom_components.loxone.controls.lights_v1 import (
    hsv_to_rgb,
    parse_color,
    parse_rgb_scene_list,
    parse_scene_list,
)

SCENES = '1=\\"Reading\\",2=\\"Dinner\\",7=\\"Party\\"'


def _sub(control_type: str, name: str, states: tuple[str, ...], details: dict | None = None) -> dict:
    uuid = uuid_for("sub", name)
    return {
        "name": name,
        "type": control_type,
        "uuidAction": uuid,
        "details": details or {},
        "states": {s: uuid_for(uuid, s) for s in states},
    }


RGB = _sub("ColorPicker", "RGB Strip", ("color", "favorites"), {"pickerType": "Rgb"})
LUMITECH = _sub("ColorPicker", "Lumitech Spot", ("color", "favorites"), {"pickerType": "Lumitech"})
SWITCH = _sub("Switch", "Wall Lamp", ("active",))
DIMMER = _sub("Dimmer", "Ceiling", ("position", "min", "max", "step"))

CONTROLLER = control(
    "LightController",
    "Kitchen Lights",
    states=("activeScene", "sceneList"),
    details={"movementScene": 1},
    sub_controls={sub["uuidAction"]: sub for sub in (RGB, LUMITECH, SWITCH, DIMMER)},
)
LIGHTSCENE = control(
    "LightsceneRGB",
    "Mood Light",
    states=("activeScene", "color"),
    details={"sceneList": {"1": "Red", "2": "Blue", "5": "Green"}},
)


@pytest.fixture
def loxapp3(loxapp3):
    return structure_with(loxapp3, CONTROLLER, LIGHTSCENE)


@pytest.fixture
def mock_entry(mock_entry):
    # Sub-control entities are disabled by default unless this option is set.
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    return MockConfigEntry(
        domain=mock_entry.domain,
        version=mock_entry.version,
        data=mock_entry.data,
        options={**mock_entry.options, "generate_lightcontroller_subcontrols": True},
        unique_id=mock_entry.unique_id,
    )


@pytest.fixture
async def setup(hass, mock_connection, mock_entry, setup_loxone_entry):
    await setup_loxone_entry(mock_entry)
    return mock_connection


def _commands(setup) -> list:
    return [(c["uuid"], c["value"]) for c in setup.sent]


def test_parse_scene_list():
    assert parse_scene_list(SCENES) == {1: "Reading", 2: "Dinner", 7: "Party"}
    assert parse_scene_list(None) == {}


def test_parse_rgb_scene_list():
    # Object keyed by scene number, as the Miniserver sends it.
    assert parse_rgb_scene_list({"1": "Purple", "3": "Green", "x": "Bad"}) == {1: "Purple", 3: "Green"}
    # Array, as the structure file spec describes it.
    assert parse_rgb_scene_list(["Red", "Blue"]) == {1: "Red", 2: "Blue"}
    assert parse_rgb_scene_list({}) == {}
    assert parse_rgb_scene_list(None) == {}


def test_hsv_to_rgb():
    assert hsv_to_rgb(240, 100, 100) == (0, 0, 255)
    assert hsv_to_rgb(0, 0, 100) == (255, 255, 255)
    assert hsv_to_rgb(360, 100, 50) == (128, 0, 0)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("hsv(120,50,80)", ("hsv", (120.0, 50.0, 80.0))),
        ("lumitech(100,4483)", ("lumitech", (100.0, 4483.0))),
        ("hsv(1,2)", None),
        ("temp(1,2)", None),
        (None, None),
    ],
)
def test_parse_color(text, expected):
    assert parse_color(text) == expected


async def test_light_controller_scenes(hass, setup):
    light = entity_id(hass, "light", CONTROLLER["uuidAction"])
    assert hass.states.get(light).state == STATE_UNKNOWN

    setup.feed(state(CONTROLLER, "sceneList"), SCENES)
    setup.feed(state(CONTROLLER, "activeScene"), 2.0)
    await hass.async_block_till_done()
    current = hass.states.get(light)
    assert current.state == STATE_ON
    assert current.attributes["effect_list"] == ["Reading", "Dinner", "Party"]
    assert current.attributes["effect"] == "Dinner"

    setup.feed(state(CONTROLLER, "activeScene"), 0.0)
    await hass.async_block_till_done()
    assert hass.states.get(light).state == STATE_OFF

    await hass.services.async_call("light", "turn_on", {"entity_id": light, "effect": "Party"}, blocking=True)
    await hass.services.async_call("light", "turn_on", {"entity_id": light}, blocking=True)
    await hass.services.async_call("light", "turn_off", {"entity_id": light}, blocking=True)
    await hass.async_block_till_done()
    uuid = CONTROLLER["uuidAction"]
    assert _commands(setup) == [(uuid, "7"), (uuid, "on"), (uuid, "off")]


async def test_light_controller_scene_buttons(hass, setup):
    nxt = entity_id(hass, "button", f"{CONTROLLER['uuidAction']}-cmd-plus")
    prev = entity_id(hass, "button", f"{CONTROLLER['uuidAction']}-cmd-minus")
    await hass.services.async_call("button", "press", {"entity_id": nxt}, blocking=True)
    await hass.services.async_call("button", "press", {"entity_id": prev}, blocking=True)
    await hass.async_block_till_done()
    assert _commands(setup) == [(CONTROLLER["uuidAction"], "plus"), (CONTROLLER["uuidAction"], "minus")]


async def test_sub_controls_share_the_controller_device(hass, setup):
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    device_ids = {
        registry.async_get(entity_id(hass, "light", uuid)).device_id
        for uuid in (CONTROLLER["uuidAction"], RGB["uuidAction"], LUMITECH["uuidAction"], SWITCH["uuidAction"])
    }
    assert len(device_ids) == 1
    device = dr.async_get(hass).async_get(device_ids.pop())
    assert device.model == "LightController"
    entity_id(hass, "light", DIMMER["uuidAction"])


async def test_rgb_color_picker(hass, setup):
    light = entity_id(hass, "light", RGB["uuidAction"])
    setup.feed(RGB["states"]["color"], "hsv(120,50,100)")
    await hass.async_block_till_done()
    current = hass.states.get(light)
    assert current.state == STATE_ON
    assert current.attributes["hs_color"] == (120.0, 50.0)
    assert current.attributes["brightness"] == 255
    assert current.attributes["friendly_name"].endswith("RGB Strip")

    await hass.services.async_call(
        "light", "turn_on", {"entity_id": light, "hs_color": [240, 100], "brightness": 128}, blocking=True
    )
    await hass.services.async_call("light", "turn_off", {"entity_id": light}, blocking=True)
    await hass.async_block_till_done()
    assert _commands(setup) == [(RGB["uuidAction"], "hsv(240,100,50)"), (RGB["uuidAction"], "off")]


async def test_lumitech_color_picker(hass, setup):
    light = entity_id(hass, "light", LUMITECH["uuidAction"])
    setup.feed(LUMITECH["states"]["color"], "lumitech(0,4000)")
    await hass.async_block_till_done()
    current = hass.states.get(light)
    assert current.state == STATE_OFF

    await hass.services.async_call(
        "light", "turn_on", {"entity_id": light, "color_temp_kelvin": 3000, "brightness": 255}, blocking=True
    )
    await hass.services.async_call("light", "turn_on", {"entity_id": light}, blocking=True)
    await hass.async_block_till_done()
    assert _commands(setup) == [(LUMITECH["uuidAction"], "lumitech(100,3000)"), (LUMITECH["uuidAction"], "on")]


async def test_lightscene_rgb(hass, setup):
    light = entity_id(hass, "light", LIGHTSCENE["uuidAction"])
    setup.feed(state(LIGHTSCENE, "activeScene"), 2.0)
    setup.feed(state(LIGHTSCENE, "color"), "hsv(240,100,100)")
    await hass.async_block_till_done()
    current = hass.states.get(light)
    assert current.state == STATE_ON
    assert current.attributes["effect"] == "Blue"
    assert current.attributes["scene_hs_color"] == (240.0, 100.0)
    assert current.attributes["scene_rgb_color"] == (0, 0, 255)
    assert current.attributes["effect_list"] == ["Red", "Blue", "Green", "All on"]

    # Scene numbers come from the sceneList keys, gaps included.
    setup.feed(state(LIGHTSCENE, "activeScene"), 5.0)
    await hass.async_block_till_done()
    assert hass.states.get(light).attributes["effect"] == "Green"

    # "on" reports an active scene outside the scene list.
    setup.feed(state(LIGHTSCENE, "activeScene"), 6.0)
    await hass.async_block_till_done()
    assert hass.states.get(light).state == STATE_ON
    assert hass.states.get(light).attributes["effect"] == "All on"

    setup.feed(state(LIGHTSCENE, "activeScene"), 0.0)
    await hass.async_block_till_done()
    assert hass.states.get(light).state == STATE_OFF

    for effect in ("Red", "Green", "All on"):
        await hass.services.async_call("light", "turn_on", {"entity_id": light, "effect": effect}, blocking=True)
    await hass.services.async_call("light", "turn_off", {"entity_id": light}, blocking=True)
    await hass.async_block_till_done()
    assert _commands(setup) == [
        (LIGHTSCENE["uuidAction"], "1"),
        (LIGHTSCENE["uuidAction"], "5"),
        (LIGHTSCENE["uuidAction"], "on"),
        (LIGHTSCENE["uuidAction"], "off"),
    ]
