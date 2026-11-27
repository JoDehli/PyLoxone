"""LoadManager support against the Loxone structure file spec.

Spec: structure file 16.0, section "LoadManager" (pp. 110-111).

- Details: ``loads`` (``id``, ``name``, ``power`` in kW, ``hasStatus``),
  ``mode`` (0 Overload, 1 Peak, 2 Peak Overload).
- States: ``currentPower``, ``peakOverloadPower``, ``maxTp``, ``maxPower``,
  ``availablePower`` (kW), ``maxPowerExceeded``, ``lockedLoads`` and
  ``statusLoads`` (bitmasks, "First Bit -> First Load").
- Not in the spec, sent by firmware 17.3: ``availablePowerPeak``,
  ``reducedLoads``, load detail ``isAnalog``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.loxone.load_manager import (
    LoxoneLoadManagerBinarySensor,
    LoxoneLoadManagerLockedCountSensor,
    LoxoneLoadManagerPowerSensor,
    build_binary_sensors,
    build_sensors,
    get_loads,
    power_label,
)

UUID = "00000000-0000-0000-ffff000000000002"

STATES = {
    "currentPower": "s-current",
    "availablePower": "s-available",
    "availablePowerPeak": "s-available-peak",
    "peakOverloadPower": "s-peak-overload",
    "maxPower": "s-max",
    "maxTp": "s-max-tp",
    "maxPowerExceeded": "s-exceeded",
    "lockedLoads": "s-locked",
    "statusLoads": "s-status",
    "reducedLoads": "s-reduced",
    "jLocked": "s-jlocked",
}

LOADS = [
    {"id": 0, "name": "Car", "power": 5.7, "isAnalog": True, "hasStatus": True},
    {"id": 1, "name": "Water heater", "power": 3, "isAnalog": False, "hasStatus": True},
    {"id": 2, "name": "Floor heating", "power": 1.37, "isAnalog": False, "hasStatus": False},
]


def _control(**over):
    control = {
        "name": "Load Manager",
        "type": "LoadManager",
        "uuidAction": UUID,
        "room": "room-uuid",
        "cat": "cat-uuid",
        "details": {"mode": 2, "loads": [dict(load) for load in LOADS]},
        "states": dict(STATES),
    }
    control.update(over)
    return control


def _loxconfig(*controls):
    return {
        "controls": {c["uuidAction"] + str(i): c for i, c in enumerate(controls)},
        "rooms": {"room-uuid": {"name": "Technical room"}},
        "cats": {"cat-uuid": {"name": "Energy"}},
    }


def _wired(entity):
    entity.async_write_ha_state = lambda: None
    return entity


def _event(**values):
    return SimpleNamespace(data={STATES[k]: v for k, v in values.items()})


def _by_suffix(entities):
    return {e.unique_id.removeprefix(f"{UUID}-"): _wired(e) for e in entities}


# --- Setup ------------------------------------------------------------------


def test_builders_create_expected_entities():
    cfg = _loxconfig(_control())
    sensors = _by_suffix(build_sensors(cfg))
    assert set(sensors) == {
        "current-power",
        "available-power",
        "available-power-peak",
        "peak-overload-power",
        "max-power",
        "max-technical-power",
        "locked-loads",
    }
    binary = _by_suffix(build_binary_sensors(cfg))
    assert set(binary) == {
        "max-power-exceeded",
        "load-0-locked",
        "load-0-active",
        "load-0-reduced",
        "load-1-locked",
        "load-1-active",
        "load-2-locked",
    }


def test_other_controls_are_ignored():
    cfg = _loxconfig(_control(type="Meter"))
    assert build_sensors(cfg) == []
    assert build_binary_sensors(cfg) == []


def test_missing_states_create_no_entities():
    cfg = _loxconfig(_control(states={"currentPower": "s-current"}))
    assert [e.unique_id for e in build_sensors(cfg)] == [f"{UUID}-current-power"]
    assert build_binary_sensors(cfg) == []


def test_unique_ids_are_distinct():
    cfg = _loxconfig(_control())
    ids = [e.unique_id for e in build_sensors(cfg) + build_binary_sensors(cfg)]
    assert len(ids) == len(set(ids))
    assert UUID not in ids


def test_entities_share_one_device_and_follow_the_room():
    cfg = _loxconfig(_control())
    entities = build_sensors(cfg) + build_binary_sensors(cfg)
    devices = {
        frozenset(e.device_info["identifiers"]) for e in entities
    }
    assert len(devices) == 1
    assert entities[0].device_info["suggested_area"] == "Technical room"
    assert entities[0].device_info["model"] == "LoadManager"


def test_names():
    cfg = _loxconfig(_control())
    names = {e.unique_id.removeprefix(f"{UUID}-"): e.name for e in
             build_sensors(cfg) + build_binary_sensors(cfg)}
    # mode 2 ("Peak Overload"): currentPower is the average power
    assert names["current-power"] == "Load Manager Average power"
    assert names["peak-overload-power"] == "Load Manager Current power"
    assert names["load-1-locked"] == "Load Manager Water heater locked"
    assert names["load-0-reduced"] == "Load Manager Car reduced"


@pytest.mark.parametrize(
    ("mode", "current", "peak_overload"),
    [
        (0, "Current power", "Peak overload power"),
        (1, "Average power", "Peak overload power"),
        (2, "Average power", "Current power"),
        ("2", "Average power", "Current power"),
        (None, "Current power", "Peak overload power"),
    ],
)
def test_power_names_follow_the_mode(mode, current, peak_overload):
    details = {"loads": []}
    if mode is not None:
        details["mode"] = mode
    sensors = _by_suffix(build_sensors(_loxconfig(_control(details=details))))
    assert sensors["current-power"].name == f"Load Manager {current}"
    assert sensors["peak-overload-power"].name == f"Load Manager {peak_overload}"


def test_power_label_keeps_other_names():
    assert power_label("availablePower", "Available power", 2) == "Available power"


def test_load_without_name_gets_a_default():
    loads = [{"id": 4, "power": 1}]
    cfg = _loxconfig(_control(details={"loads": loads}))
    names = [e.name for e in build_binary_sensors(cfg)]
    assert "Load Manager Load 5 locked" in names


def test_get_loads_skips_invalid_and_duplicate_ids():
    control = _control(details={"loads": [
        {"id": 0, "name": "a"},
        {"id": "1", "name": "b"},
        {"id": 0, "name": "duplicate"},
        {"id": None, "name": "none"},
        {"id": -1, "name": "negative"},
        {"id": 64, "name": "too large"},
        "garbage",
    ]})
    assert [(load["id"], load["name"]) for load in get_loads(control)] == [
        (0, "a"), (1, "b"),
    ]


def test_broken_control_does_not_break_the_others():
    broken = _control(uuidAction="broken", details={"loads": "nonsense"})
    del broken["room"]
    cfg = _loxconfig(broken, _control())
    assert len(build_sensors(cfg)) >= 7


# --- Values -----------------------------------------------------------------


async def test_power_sensor_values():
    sensors = _by_suffix(build_sensors(_loxconfig(_control())))
    current = sensors["current-power"]
    assert isinstance(current, LoxoneLoadManagerPowerSensor)
    assert current.native_unit_of_measurement == "kW"
    await current.event_handler(_event(currentPower=5.71))
    assert current.native_value == 5.71
    await current.event_handler(_event(currentPower="nan"))
    assert current.native_value is None
    await current.event_handler(_event(availablePower=3))  # other state
    assert current.native_value is None


def test_diagnostic_power_sensors():
    sensors = _by_suffix(build_sensors(_loxconfig(_control())))
    assert sensors["current-power"].entity_category is None
    assert sensors["max-power"].entity_category == "diagnostic"
    assert sensors["max-technical-power"].entity_category == "diagnostic"


def test_undocumented_states_are_disabled_by_default():
    cfg = _loxconfig(_control())
    sensors = _by_suffix(build_sensors(cfg))
    binary = _by_suffix(build_binary_sensors(cfg))
    assert sensors["available-power-peak"].entity_registry_enabled_default is False
    assert binary["load-0-reduced"].entity_registry_enabled_default is False
    assert sensors["current-power"].entity_registry_enabled_default is True
    assert binary["load-0-locked"].entity_registry_enabled_default is True
    assert binary["load-0-active"].entity_registry_enabled_default is True


async def test_locked_count_and_names():
    sensors = _by_suffix(build_sensors(_loxconfig(_control())))
    locked = sensors["locked-loads"]
    assert isinstance(locked, LoxoneLoadManagerLockedCountSensor)
    await locked.event_handler(_event(lockedLoads=0b101))
    assert locked.native_value == 2
    assert locked.extra_state_attributes["locked_loads"] == ["Car", "Floor heating"]
    await locked.event_handler(_event(lockedLoads=0))
    assert locked.native_value == 0
    assert locked.extra_state_attributes["locked_loads"] == []
    await locked.event_handler(_event(lockedLoads="bad"))
    assert locked.native_value is None


@pytest.mark.parametrize(
    ("suffix", "state_key", "mask", "expected"),
    [
        ("load-0-locked", "lockedLoads", 0b001, True),
        ("load-1-locked", "lockedLoads", 0b001, False),
        ("load-2-locked", "lockedLoads", 0b100, True),
        ("load-1-active", "statusLoads", 0b110, True),
        ("load-0-active", "statusLoads", 0b110, False),
        ("load-0-reduced", "reducedLoads", 1, True),
        ("load-0-reduced", "reducedLoads", "1", True),
        ("load-0-locked", "lockedLoads", None, None),
        ("load-0-locked", "lockedLoads", -1, None),
    ],
)
async def test_per_load_bits(suffix, state_key, mask, expected):
    binary = _by_suffix(build_binary_sensors(_loxconfig(_control())))
    entity = binary[suffix]
    assert isinstance(entity, LoxoneLoadManagerBinarySensor)
    await entity.event_handler(_event(**{state_key: mask}))
    assert entity.is_on is expected


async def test_real_status_mask():
    """statusLoads 2566 = bits 1, 2, 9 and 11, as seen on a Miniserver."""
    loads = [{"id": i, "name": f"L{i}", "hasStatus": True} for i in range(12)]
    cfg = _loxconfig(_control(details={"loads": loads}))
    active = [e for e in build_binary_sensors(cfg) if e.unique_id.endswith("-active")]
    on = []
    for entity in active:
        _wired(entity)
        await entity.event_handler(_event(statusLoads=2566))
        if entity.is_on:
            on.append(entity.extra_state_attributes["load_id"])
    assert on == [1, 2, 9, 11]


async def test_max_power_exceeded():
    binary = _by_suffix(build_binary_sensors(_loxconfig(_control())))
    exceeded = binary["max-power-exceeded"]
    assert exceeded.device_class == "problem"
    await exceeded.event_handler(_event(maxPowerExceeded=1))
    assert exceeded.is_on is True
    await exceeded.event_handler(_event(maxPowerExceeded=0))
    assert exceeded.is_on is False


def test_load_attributes():
    binary = _by_suffix(build_binary_sensors(_loxconfig(_control())))
    attributes = binary["load-0-locked"].extra_state_attributes
    assert attributes["load_id"] == 0
    assert attributes["load_name"] == "Car"
    assert attributes["load_power"] == 5.7
    assert attributes["load_analog"] is True
    assert attributes["state_uuid"] == "s-locked"
    assert attributes["state_key"] == "lockedLoads"
    assert attributes["device_type"] == "LoadManager"


def test_power_sensors_expose_their_state_key():
    """Names follow the mode, so dashboards find a value by ``state_key``."""
    sensors = _by_suffix(build_sensors(_loxconfig(_control())))
    assert sensors["current-power"].extra_state_attributes["state_key"] == "currentPower"
    assert sensors["locked-loads"].extra_state_attributes["state_key"] == "lockedLoads"
