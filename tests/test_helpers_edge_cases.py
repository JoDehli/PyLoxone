"""Edge cases of helper functions reported by the University of Ulm fuzzing work (#292)."""

from custom_components.loxone.helpers import get_all, map_range


def test_map_range_maps_within_range():
    assert map_range(50, 0, 100, 100, 0) == 50
    assert map_range(0, 0, 100, 100, 0) == 100


def test_map_range_with_equal_input_bounds_does_not_divide_by_zero():
    assert map_range(5, 3, 3, 10, 20) == 10


def test_get_all_returns_matching_controls():
    config = {
        "controls": {
            "a": {"type": "Switch", "name": "A"},
            "b": {"type": "Dimmer", "name": "B"},
            "c": {"type": "Switch", "name": "C"},
        }
    }
    assert [c["name"] for c in get_all(config, "Switch")] == ["A", "C"]
    assert [c["name"] for c in get_all(config, ["Switch", "Dimmer"])] == ["A", "B", "C"]


def test_get_all_without_controls_section_returns_empty_list():
    assert get_all({}, "Switch") == []
    assert get_all({"controls": None}, "Switch") == []


def test_get_all_skips_controls_without_type():
    config = {"controls": {"a": {"name": "no type"}, "b": {"type": "Switch", "name": "B"}}}
    assert [c["name"] for c in get_all(config, "Switch")] == ["B"]
