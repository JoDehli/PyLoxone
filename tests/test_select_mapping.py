"""Tests for Loxone Radio block to select option mapping."""

import asyncio
from types import SimpleNamespace

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.loxone.helpers import parse_control_lock
from custom_components.loxone.select import (
    ALL_OFF_DEFAULT_LABEL,
    ALL_OFF_VALUE,
    LoxoneSelect,
    build_option_maps,
)


# Sample "Ventilatie" Radio block taken from a real LoxAPP3.json structure file.
VENTILATIE_DETAILS = {
    "jLockable": True,
    "allOff": "",
    "outputs": {
        "1": "Stand 1",
        "2": "Stand 2",
        "3": "Stand 3",
        "4": "Stand 4",
    },
}


class TestBuildOptionMaps:
    """Test build_option_maps — the pure Radio-to-select mapping function."""

    def test_outputs_become_options(self):
        options, _, _, _ = build_option_maps(VENTILATIE_DETAILS)
        assert "Stand 1" in options
        assert "Stand 4" in options

    def test_options_are_sorted_by_output_number(self):
        options, _, _, _ = build_option_maps(VENTILATIE_DETAILS)
        # The "all off" entry is first, followed by outputs in numeric order.
        assert options == [
            ALL_OFF_DEFAULT_LABEL,
            "Stand 1",
            "Stand 2",
            "Stand 3",
            "Stand 4",
        ]

    def test_empty_all_off_uses_default_label(self):
        options, num_to_opt, opt_to_num, all_off_num = build_option_maps(
            VENTILATIE_DETAILS
        )
        assert ALL_OFF_DEFAULT_LABEL in options
        assert num_to_opt[ALL_OFF_VALUE] == ALL_OFF_DEFAULT_LABEL
        assert opt_to_num[ALL_OFF_DEFAULT_LABEL] == ALL_OFF_VALUE
        assert all_off_num == ALL_OFF_VALUE

    def test_custom_all_off_label(self):
        details = {"allOff": "Uit", "outputs": {"1": "Stand 1"}}
        options, num_to_opt, opt_to_num, all_off_num = build_option_maps(details)
        assert options == ["Uit", "Stand 1"]
        assert num_to_opt[ALL_OFF_VALUE] == "Uit"
        assert opt_to_num["Uit"] == ALL_OFF_VALUE
        assert all_off_num == ALL_OFF_VALUE

    def test_no_all_off_when_detail_absent(self):
        details = {"outputs": {"1": "Stand 1", "2": "Stand 2"}}
        options, num_to_opt, opt_to_num, all_off_num = build_option_maps(details)
        assert options == ["Stand 1", "Stand 2"]
        assert ALL_OFF_VALUE not in num_to_opt
        assert all_off_num is None

    def test_number_to_option_mapping(self):
        _, num_to_opt, _, _ = build_option_maps(VENTILATIE_DETAILS)
        assert num_to_opt[1] == "Stand 1"
        assert num_to_opt[2] == "Stand 2"
        assert num_to_opt[3] == "Stand 3"
        assert num_to_opt[4] == "Stand 4"

    def test_option_to_number_mapping(self):
        _, _, opt_to_num, _ = build_option_maps(VENTILATIE_DETAILS)
        assert opt_to_num["Stand 1"] == 1
        assert opt_to_num["Stand 4"] == 4

    def test_round_trip_number_option_number(self):
        _, num_to_opt, opt_to_num, _ = build_option_maps(VENTILATIE_DETAILS)
        for number in (0, 1, 2, 3, 4):
            assert opt_to_num[num_to_opt[number]] == number

    def test_duplicate_output_names_are_deduplicated(self):
        details = {"outputs": {"1": "Stand", "2": "Stand", "3": "Stand"}}
        options, _, opt_to_num, _ = build_option_maps(details)
        # All labels remain unique as required by Home Assistant.
        assert len(options) == len(set(options))
        assert options == ["Stand", "Stand (2)", "Stand (3)"]
        assert opt_to_num["Stand"] == 1
        assert opt_to_num["Stand (2)"] == 2
        assert opt_to_num["Stand (3)"] == 3

    def test_missing_outputs_key(self):
        options, num_to_opt, opt_to_num, all_off_num = build_option_maps({})
        assert options == []
        assert num_to_opt == {}
        assert opt_to_num == {}
        assert all_off_num is None


# --- jLocked: the lock state is JSON, not a boolean --------------------------


def _select() -> LoxoneSelect:
    select = LoxoneSelect(
        uuidAction="uuid-select",
        name="Radio",
        type="Radio",
        room="Raum",
        cat="Kat",
        states={"activeOutput": "uuid-active", "jLocked": "uuid-lock"},
        details={"outputs": {"1": "Stand 1"}},
    )
    select.async_schedule_update_ha_state = lambda: None
    return select


def test_select_locked_false_for_locked_zero_json():
    """Bug: bool() of the *text* read the unlocked JSON as locked - every
    non-empty jLocked value was True."""
    select = _select()

    asyncio.run(
        select.event_handler(
            SimpleNamespace(data={"uuid-lock": '{"locked": 0, "reason": "Urlaub."}'})
        )
    )

    assert select._locked is False


def test_select_locked_true_for_locked_by_visualisation():
    select = _select()

    asyncio.run(
        select.event_handler(
            SimpleNamespace(data={"uuid-lock": '{"locked": 1, "reason": "Manuell"}'})
        )
    )

    assert select._locked is True


def test_select_locked_any_nonzero_lock():
    select = _select()

    asyncio.run(
        select.event_handler(
            SimpleNamespace(data={"uuid-lock": '{"locked": 2, "reason": "Logik"}'})
        )
    )

    assert select._locked is True


def test_select_garbage_lock_reads_not_locked():
    select = _select()

    asyncio.run(select.event_handler(SimpleNamespace(data={"uuid-lock": "garbage"})))

    assert select._locked is False


def test_select_active_output_still_updates_option():
    select = _select()

    asyncio.run(
        select.event_handler(
            SimpleNamespace(
                data={"uuid-active": 1.0, "uuid-lock": '{"locked": 0}'}
            )
        )
    )

    assert select.current_option == "Stand 1"
    assert select._locked is False


def test_select_both_streams_write_state_once():
    """PS-19: activeOutput and jLocked arrive together; one event is one
    state write, not two."""
    select = _select()
    writes = []
    select.async_schedule_update_ha_state = lambda: writes.append(1)

    asyncio.run(
        select.event_handler(
            SimpleNamespace(
                data={"uuid-active": 1.0, "uuid-lock": '{"locked": 1}'}
            )
        )
    )

    assert len(writes) == 1
    assert select.current_option == "Stand 1"
    assert select._locked is True


# --- parse_control_lock (as used by the handler above) ----------------------


def test_parse_control_lock_numbers():
    assert parse_control_lock("") == (0, "")
    assert parse_control_lock(None) == (0, "")
    assert parse_control_lock(1) == (1, "")
    assert parse_control_lock(2.0) == (2, "")
    assert parse_control_lock(True) == (1, "")


def test_parse_control_lock_json():
    assert parse_control_lock('{"locked": 1, "reason": "Manuell"}') == (1, "Manuell")
    assert parse_control_lock('{"locked": 0}') == (0, "")
    # Out-of-range and unreadable values read as not locked, never block.
    assert parse_control_lock('{"locked": 7}') == (0, "")
    assert parse_control_lock('{"locked": "x"}') == (0, "")
    assert parse_control_lock("{}") == (0, "")
    assert parse_control_lock("[1]") == (0, "")
    assert parse_control_lock("not json") == (0, "")


# --- PS-19 remainder: options property and lock enforcement -----------------


def test_select_options_built_from_base_class_property():
    """The redundant options/current_option overrides are gone; the base
    class properties read the _attr_* attributes."""
    select = _select()

    assert select.options == ["Stand 1"]
    assert select.current_option is None


async def _raise_locked_selection():
    select = _select()
    select._locked = True

    await select.async_select_option("Stand 1")


def test_select_locked_refuses_selection():
    """A locked block ignores selections; HA renders the raised error to
    the service caller."""
    with pytest.raises(HomeAssistantError):
        asyncio.run(_raise_locked_selection())


def test_select_unlocked_selection_is_not_refused():
    select = _select()
    select._locked = False
    select.hass = SimpleNamespace(bus=SimpleNamespace(async_fire=lambda *_: None))
    select.async_schedule_update_ha_state = lambda: None

    asyncio.run(select.async_select_option("Stand 1"))
