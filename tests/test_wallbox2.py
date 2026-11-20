"""Wallbox2 (Wallbox Gen. 2) support against the Loxone structure file spec.

Spec: structure file V17.0, section "Wallbox2" (pp. 145-147).

- Commands: ``allow/on``, ``allow/off``, ``setmode/<1-5|99>``,
  ``manualLimit/<kW>`` (activates manual mode 99).
- States: ``enabled``, ``connected``, ``active``, ``mode``, ``limit``,
  ``loadshed``, ``phaseSwitching``.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from custom_components.loxone.const import SENDDOMAIN
from custom_components.loxone.wallbox2 import (
    LoxoneWallbox2BinarySensor,
    LoxoneWallbox2Number,
    LoxoneWallbox2Select,
    LoxoneWallbox2Switch,
    build_binary_sensors,
    build_mode_options,
    build_numbers,
    build_selects,
    build_switches,
)

UUID = "00000000-0000-0000-ffff000000000001"

STATES = {
    "enabled": "s-enabled",
    "connected": "s-connected",
    "active": "s-active",
    "loadshed": "s-loadshed",
    "phaseSwitching": "s-phase",
    "mode": "s-mode",
    "limit": "s-limit",
}


def _control(**over):
    control = {
        "name": "Wallbox",
        "type": "Wallbox2",
        "uuidAction": UUID,
        "room": "room-uuid",
        "cat": "cat-uuid",
        "details": {
            "min": 1.4,
            "max": 11.0,
            "modes": [
                {"id": 1, "setByLogic": True},
                {"id": 2, "setByLogic": False},
                {"id": 3, "name": "Eco", "setByLogic": False},
                {"id": 99, "setByLogic": False},
            ],
        },
        "states": dict(STATES),
    }
    control.update(over)
    return control


def _loxconfig(*controls):
    return {
        "controls": {c["uuidAction"] + str(i): c for i, c in enumerate(controls)},
        "rooms": {"room-uuid": {"name": "Garage"}},
        "cats": {"cat-uuid": {"name": "Energy"}},
    }


def _wired(entity):
    """Capture the commands an entity sends and the state writes it makes."""
    sent: list = []
    entity.hass = SimpleNamespace(
        bus=SimpleNamespace(
            async_fire=lambda domain, data: sent.append((domain, data))
        )
    )
    entity.async_write_ha_state = lambda: None
    return sent


def _commands(sent) -> list:
    return [(d["uuid"], d["value"]) for domain, d in sent if domain == SENDDOMAIN]


def _event(**values):
    return SimpleNamespace(data={STATES[k]: v for k, v in values.items()})


# --- Setup ------------------------------------------------------------------


def test_builders_create_expected_entities():
    cfg = _loxconfig(_control())
    assert len(build_switches(cfg)) == 1
    assert len(build_selects(cfg)) == 1
    assert len(build_numbers(cfg)) == 1
    assert len(build_binary_sensors(cfg)) == 4


def test_other_controls_are_ignored():
    cfg = _loxconfig(_control(type="Meter"))
    assert build_switches(cfg) == []
    assert build_binary_sensors(cfg) == []


def test_unique_ids_are_distinct_and_stable():
    cfg = _loxconfig(_control())
    entities = (
        build_switches(cfg)
        + build_selects(cfg)
        + build_numbers(cfg)
        + build_binary_sensors(cfg)
    )
    ids = [e.unique_id for e in entities]
    assert len(ids) == len(set(ids)) == 7
    assert all(i.startswith(UUID) for i in ids)


def test_builders_do_not_mutate_the_structure():
    """Every platform resolves room/category on its own copy."""
    cfg = _loxconfig(_control())
    build_switches(cfg)
    build_selects(cfg)
    control = next(iter(cfg["controls"].values()))
    assert control["room"] == "room-uuid"
    assert control["cat"] == "cat-uuid"


def test_missing_state_skips_entity():
    states = {k: v for k, v in STATES.items() if k != "limit"}
    cfg = _loxconfig(_control(states=states))
    assert build_numbers(cfg) == []
    assert len(build_switches(cfg)) == 1


# --- Switch -----------------------------------------------------------------


def test_switch_sends_allow_commands():
    switch = build_switches(_loxconfig(_control()))[0]
    sent = _wired(switch)
    asyncio.run(switch.async_turn_on())
    asyncio.run(switch.async_turn_off())
    assert _commands(sent) == [(UUID, "allow/on"), (UUID, "allow/off")]


def test_switch_follows_enabled_state():
    switch = build_switches(_loxconfig(_control()))[0]
    _wired(switch)
    asyncio.run(switch.event_handler(_event(enabled=1)))
    assert switch.is_on is True
    asyncio.run(switch.event_handler(_event(enabled=0)))
    assert switch.is_on is False


def test_switch_ignores_unrelated_events():
    switch = build_switches(_loxconfig(_control()))[0]
    _wired(switch)
    asyncio.run(switch.event_handler(SimpleNamespace(data={"other": 1})))
    assert switch.is_on is None


# --- Select -----------------------------------------------------------------


def test_mode_options_use_names_and_manual():
    options, id_to_label, label_to_id = build_mode_options(
        _control()["details"]
    )
    assert options == ["Mode 1", "Mode 2", "Eco", "Manual"]
    assert id_to_label[3] == "Eco"
    assert label_to_id["Manual"] == 99


def test_mode_options_always_offer_manual_and_dedupe():
    options, _, label_to_id = build_mode_options(
        {"modes": [{"id": 1, "name": "A"}, {"id": 2, "name": "A"}]}
    )
    assert options == ["A", "A (2)", "Manual"]
    assert label_to_id["Manual"] == 99


def test_select_sends_setmode_and_follows_state():
    select = build_selects(_loxconfig(_control()))[0]
    sent = _wired(select)
    asyncio.run(select.async_select_option("Eco"))
    asyncio.run(select.async_select_option("Manual"))
    assert _commands(sent) == [(UUID, "setmode/3"), (UUID, "setmode/99")]

    asyncio.run(select.event_handler(_event(mode=2)))
    assert select.current_option == "Mode 2"
    asyncio.run(select.event_handler(_event(mode=42)))  # unknown id
    assert select.current_option is None


def test_select_unknown_option_sends_nothing():
    select = build_selects(_loxconfig(_control()))[0]
    sent = _wired(select)
    asyncio.run(select.async_select_option("nope"))
    assert _commands(sent) == []


# --- Number -----------------------------------------------------------------


def test_number_range_comes_from_details():
    number = build_numbers(_loxconfig(_control()))[0]
    assert number.native_min_value == 1.4
    assert number.native_max_value == 11.0
    assert number.native_unit_of_measurement == "kW"


def test_number_sends_manual_limit_clamped_to_range():
    number = build_numbers(_loxconfig(_control()))[0]
    sent = _wired(number)
    asyncio.run(number.async_set_native_value(7.4))
    asyncio.run(number.async_set_native_value(50))  # above wallbox max
    asyncio.run(number.async_set_native_value(0))  # below wallbox min
    assert _commands(sent) == [
        (UUID, "manualLimit/7.4"),
        (UUID, "manualLimit/11.0"),
        (UUID, "manualLimit/1.4"),
    ]


def test_number_follows_limit_state():
    number = build_numbers(_loxconfig(_control()))[0]
    _wired(number)
    asyncio.run(number.event_handler(_event(limit=6.5)))
    assert number.native_value == 6.5
    asyncio.run(number.event_handler(_event(limit="garbage")))
    assert number.native_value is None


# --- Binary sensors ---------------------------------------------------------


def test_binary_sensors_follow_their_own_state_only():
    sensors = {
        s._state_key: s for s in build_binary_sensors(_loxconfig(_control()))
    }
    sent_all = {k: _wired(s) for k, s in sensors.items()}
    asyncio.run(sensors["connected"].event_handler(_event(connected=1)))
    asyncio.run(sensors["active"].event_handler(_event(connected=1)))
    assert sensors["connected"].is_on is True
    assert sensors["active"].is_on is None  # not its state
    assert all(not v for v in sent_all.values())  # read-only: no commands


# --- Mode names pushed by the Miniserver -------------------------------------


def test_select_takes_mode_names_from_modes_state():
    states = dict(STATES, modes="s-modes")
    select = build_selects(_loxconfig(_control(states=states)))[0]
    _wired(select)

    names = [{"id": 1, "name": "Solar"}, {"id": 2, "name": "Fast"}]
    asyncio.run(select.event_handler(SimpleNamespace(data={"s-modes": json.dumps(names)})))
    assert select.options == ["Solar", "Fast", "Manual"]

    asyncio.run(select.event_handler(_event(mode=2)))
    assert select.current_option == "Fast"


def test_select_remaps_current_option_when_names_arrive_late():
    states = dict(STATES, modes="s-modes")
    select = build_selects(_loxconfig(_control(states=states)))[0]
    _wired(select)

    asyncio.run(select.event_handler(_event(mode=1)))
    assert select.current_option == "Mode 1"
    asyncio.run(
        select.event_handler(
            SimpleNamespace(data={"s-modes": [{"id": 1, "name": "Solar"}]})
        )
    )
    assert select.current_option == "Solar"


def test_select_keeps_defaults_on_garbage_modes_state():
    states = dict(STATES, modes="s-modes")
    select = build_selects(_loxconfig(_control(states=states)))[0]
    _wired(select)
    before = list(select.options)
    asyncio.run(select.event_handler(SimpleNamespace(data={"s-modes": "not json"})))
    assert select.options == before


def test_select_exposes_mode_map_as_attribute():
    select = build_selects(_loxconfig(_control()))[0]
    attrs = select.extra_state_attributes
    assert attrs["modes"]["3"] == "Eco"
    assert attrs["modes"]["99"] == "Manual"
    assert attrs["mode_id"] is None


def test_number_ignores_non_finite_values():
    number = build_numbers(_loxconfig(_control()))[0]
    sent = _wired(number)
    for bad in (float("nan"), float("inf"), float("-inf")):
        asyncio.run(number.async_set_native_value(bad))
    assert _commands(sent) == []


def test_number_not_created_without_valid_range():
    for details in ({}, {"min": 1.4}, {"min": 0, "max": 11}, {"min": 12, "max": 11},
                    {"min": "x", "max": 11}, {"min": None, "max": 11}):
        cfg = _loxconfig(_control(details=details))
        assert build_numbers(cfg) == [], details


def test_one_broken_wallbox_does_not_break_the_others():
    good = _control()
    bad = _control(uuidAction="00000000-0000-0000-ffff000000000002",
                   details={"min": None, "max": None})
    entities = build_numbers(_loxconfig(bad, good))
    assert [e.uuidAction for e in entities] == [UUID]


def test_unreadable_binary_state_is_unknown_not_off():
    sensors = {s._state_key: s for s in build_binary_sensors(_loxconfig(_control()))}
    _wired(sensors["connected"])
    asyncio.run(sensors["connected"].event_handler(_event(connected="garbage")))
    assert sensors["connected"].is_on is None
