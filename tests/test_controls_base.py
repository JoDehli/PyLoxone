"""The ``controls`` package: value conversion and the builder registry."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from homeassistant.const import Platform
from homeassistant.util import dt as dt_util

from custom_components.loxone import controls
from custom_components.loxone.controls.base import (
    ControlStateSensor,
    StateSpec,
    from_loxone_time,
    parse_json,
    seconds_of_day,
    to_bool,
    to_float,
    to_text,
    unit_from_format,
)

from _controls import control, entity_id, state, structure_with


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(1.0, True), (0.0, False), ("true", True), ("false", False), ("", False), ("x", None), (None, None)],
)
def test_to_bool(raw, expected):
    assert to_bool(raw) is expected


def test_to_float_and_text():
    assert to_float("2.5") == 2.5
    assert to_float("n/a") is None
    assert to_text("x" * 300) == "x" * 255
    assert to_text(None) is None


def test_parse_json():
    assert parse_json('{"a": 1}') == {"a": 1}
    assert parse_json("") is None
    assert parse_json("not json", default=[]) == []
    assert parse_json([1]) == [1]


def test_from_loxone_time():
    assert from_loxone_time(0) is None
    assert from_loxone_time(86400, utc=True) == datetime(2009, 1, 2, tzinfo=UTC)
    local = from_loxone_time(3600)
    assert local.tzinfo == dt_util.get_default_time_zone()
    assert (local.year, local.month, local.day, local.hour) == (2009, 1, 1, 1)


def test_seconds_of_day():
    assert seconds_of_day(29940) == "08:19"
    assert seconds_of_day(3661) == "01:01:01"
    assert seconds_of_day(-1) is None


def test_unit_from_format():
    assert unit_from_format("%.3f kW") == "kW"
    assert unit_from_format("%.0f%%") == "%"
    assert unit_from_format("%.1f") is None
    assert unit_from_format(None) is None


# --- registry against the real integration ----------------------------------

GOOD = control("TestGood", "Test Good", states=("value",))
BAD = control("TestBad", "Test Bad", states=("value",))


@pytest.fixture
def loxapp3(loxapp3):
    return structure_with(loxapp3, GOOD, BAD)


@pytest.fixture
def test_builders():
    """Register builders for two fake types; the broken one must be skipped."""

    def good(ctx, item):
        return [ControlStateSensor(item, StateSpec(key="value", main=True))]

    def bad(ctx, item):
        message = "broken control"
        raise RuntimeError(message)

    platform = str(Platform.SENSOR)
    controls.handled_types()  # load the real modules before taking the snapshot
    before = list(controls._BUILDERS.get(platform, []))
    controls.register(Platform.SENSOR, "TestGood")(good)
    controls.register(Platform.SENSOR, "TestBad")(bad)
    yield
    controls._BUILDERS[platform] = before


async def test_broken_builder_does_not_block_others(
    hass, mock_connection, mock_entry, setup_loxone_entry, test_builders, caplog
):
    await setup_loxone_entry(mock_entry)
    sensor = entity_id(hass, "sensor", GOOD["uuidAction"])
    assert "Skipping TestBad control Test Bad" in caplog.text

    mock_connection.feed(state(GOOD, "value"), 4.5)
    await hass.async_block_till_done()
    current = hass.states.get(sensor)
    assert current.state == "4.5"
    assert current.attributes["device_type"] == "TestGood"


def test_handled_types_lists_registered_types(test_builders):
    assert {"TestGood", "TestBad"} <= controls.handled_types(Platform.SENSOR)
