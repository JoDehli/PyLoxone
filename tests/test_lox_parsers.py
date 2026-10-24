"""Light mood / color states are parsed as data, never ``eval``'d."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from custom_components.loxone.helpers import parse_lox_color, parse_lox_json
from custom_components.loxone.lights.colorpickers import _parse_color
from custom_components.loxone.lights.lightcontroller import \
    LoxoneLightControllerV2

INJECTION = "__import__('os').system('echo pwned')"


def test_parse_lox_color():
    assert parse_lox_color("hsv(0,100,100)") == ("hsv", [0, 100, 100])
    assert parse_lox_color("temp(100,4483)") == ("temp", [100, 4483])
    assert parse_lox_color("hsv(12.5,50,7.5)") == ("hsv", [12.5, 50, 7.5])


@pytest.mark.parametrize(
    "text",
    [
        INJECTION,
        f"hsv({INJECTION})",
        "hsv(1,2,(3))",
        "hsv(true,1,1)",
        "hsv()",
        "rgb(1,2,3)",
        "temp(1,2",
    ],
)
def test_parse_lox_color_rejects_non_colors(text):
    with pytest.raises(ValueError):
        parse_lox_color(text)


def test_parse_color_checks_value_count(caplog):
    with caplog.at_level(logging.WARNING):
        assert _parse_color("hsv(1,2)", "Lamp") is None
        assert _parse_color("temp(1,2,3)", "Lamp") is None
    assert _parse_color("temp(80,3000)", "Lamp") == [80, 3000]
    assert "Lamp" in caplog.text


def test_parse_lox_json_rejects_code():
    with pytest.raises(ValueError):
        parse_lox_json(INJECTION)


def _controller():
    entity = LoxoneLightControllerV2.__new__(LoxoneLightControllerV2)
    entity.states = {
        "activeMoods": "uuid-active",
        "moodList": "uuid-moods",
        "additionalMoods": "uuid-additional",
    }
    entity._attr_name = "Living room"
    return entity


def test_mood_names_containing_true_are_kept():
    """The old ``replace("true", "True")`` + eval renamed such moods."""
    entity = _controller()
    data = {
        "uuid-moods": '[{"name": "true colors", "id": 1, "static": false}]'
    }
    assert entity._parse_json_state("moodList", data) == [
        {"name": "true colors", "id": 1, "static": False}
    ]


def test_invalid_mood_state_is_ignored(caplog):
    entity = _controller()
    with caplog.at_level(logging.WARNING):
        assert entity._parse_json_state("activeMoods", {"uuid-active": INJECTION}) is None
    assert "activeMoods" in caplog.text
