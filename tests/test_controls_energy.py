"""EnergyManager, EnergyManager2, EnergyFlowMonitor (structure file spec V17)."""

from __future__ import annotations

import json

import pytest
from homeassistant.helpers import entity_registry as er

from _controls import control, entity_id, state, structure_with

EM = control(
    "EnergyManager",
    "Energy Manager",
    states=("currentPower", "currentBat", "loads"),
    details={
        "loads": [
            {"id": 0, "name": "Boiler", "minOnTime": 600},
            {"id": 1, "name": "Pool Pump", "minOnTime": 0},
        ]
    },
)
EM2 = control(
    "EnergyManager2",
    "Energy Manager 2",
    states=("Gpwr", "Spwr", "Ppwr", "Ssoc", "MinSoc", "MaxSpwr", "loads"),
    details={"MinSocLocked": False, "MaxSpwrLocked": True, "HasSsoc": True, "HasSpwr": False},
)
EFM = control(
    "EnergyFlowMonitor",
    "Energy Flow",
    states=("Ppwr", "Gpwr", "Spwr", "Pre", "Pri", "CO2", "actual0", "actual1"),
    details={
        "actualFormat": "%.3f kW",
        "totalFormat": "%.3f kWh",
        "nodes": [
            {"uuid": "n1", "nodeType": "Load", "title": "House", "actualEfmState": "actual0"},
            {"uuid": "n2", "nodeType": "Wallbox", "title": "Car", "actualEfmState": "actual1"},
            {"uuid": "n3", "nodeType": "Group", "title": "Child without live state"},
        ],
    },
)

EM2_LOADS = [
    {
        "prio": 0,
        "id": 0,
        "name": "Heat Pump",
        "uuid": "load-hp",
        "pwr": 2.5,
        "active": True,
        "activatedManually": False,
        "deactivatedManually": False,
        "minimumActiveUntil": 0,
    },
    {
        "prio": 1,
        "id": 1,
        "name": "Wallbox",
        "uuid": "load-wb",
        "pwr": 0,
        "active": False,
        "activatedManually": False,
        "deactivatedManually": True,
    },
]


@pytest.fixture
def loxapp3(loxapp3):
    return structure_with(loxapp3, EM, EM2, EFM)


@pytest.fixture
async def setup(hass, mock_connection, mock_entry, setup_loxone_entry):
    await setup_loxone_entry(mock_entry)
    return mock_connection


def _commands(setup) -> list:
    return [(c["uuid"], c["value"]) for c in setup.sent]


# --- EnergyManager --------------------------------------------------------


async def test_em_sensors(hass, setup):
    power = entity_id(hass, "sensor", f"{EM['uuidAction']}-currentPower")
    setup.feed(state(EM, "currentPower"), 3.2)
    await hass.async_block_till_done()
    assert hass.states.get(power).state == "3.2"


async def test_em_load_switches(hass, setup):
    boiler = entity_id(hass, "switch", f"{EM['uuidAction']}-load-0")
    pump = entity_id(hass, "switch", f"{EM['uuidAction']}-load-1")
    setup.feed(
        state(EM, "loads"),
        json.dumps(
            [
                {"id": 0, "isActive": True, "isPreparing": False, "activeUntil": 0, "isPermanentOn": True},
                {"id": 1, "isActive": False, "isPreparing": False, "activeUntil": 0, "isPermanentOn": False},
            ]
        ),
    )
    await hass.async_block_till_done()
    assert hass.states.get(boiler).state == "on"
    assert hass.states.get(boiler).attributes["permanent_on"] is True
    assert hass.states.get(pump).state == "off"

    await hass.services.async_call("switch", "turn_off", {"entity_id": boiler}, blocking=True)
    await hass.services.async_call("switch", "turn_on", {"entity_id": pump}, blocking=True)
    await hass.async_block_till_done()
    assert _commands(setup) == [(EM["uuidAction"], "turnOff/0"), (EM["uuidAction"], "turnOn/1")]


async def test_em_trigger_button_only_with_min_on_time(hass, setup):
    trigger = entity_id(hass, "button", f"{EM['uuidAction']}-trigger-0")
    await hass.services.async_call("button", "press", {"entity_id": trigger}, blocking=True)
    await hass.async_block_till_done()
    assert _commands(setup) == [(EM["uuidAction"], "trigger/0")]
    assert er.async_get(hass).async_get_entity_id("button", "loxone", f"{EM['uuidAction']}-trigger-1") is None


# --- EnergyManager2 -------------------------------------------------------


async def test_em2_sensors_follow_the_has_flags(hass, setup):
    registry = er.async_get(hass)
    grid = entity_id(hass, "sensor", f"{EM2['uuidAction']}-Gpwr")
    soc = entity_id(hass, "sensor", f"{EM2['uuidAction']}-Ssoc")
    # HasSpwr is false -> no storage power sensor.
    assert registry.async_get_entity_id("sensor", "loxone", f"{EM2['uuidAction']}-Spwr") is None
    # MaxSpwr is locked -> read-only sensor instead of a number.
    entity_id(hass, "sensor", f"{EM2['uuidAction']}-MaxSpwr")
    assert registry.async_get_entity_id("number", "loxone", f"{EM2['uuidAction']}-MaxSpwr") is None

    setup.feed(state(EM2, "Gpwr"), -1.5)
    setup.feed(state(EM2, "Ssoc"), 80.0)
    await hass.async_block_till_done()
    assert hass.states.get(grid).state == "-1.5"
    assert hass.states.get(grid).attributes["unit_of_measurement"] == "kW"
    assert hass.states.get(grid).attributes["device_class"] == "power"
    assert hass.states.get(soc).attributes["device_class"] == "battery"


async def test_em2_min_soc_number(hass, setup):
    number = entity_id(hass, "number", f"{EM2['uuidAction']}-MinSoc")
    setup.feed(state(EM2, "MinSoc"), 20.0)
    await hass.async_block_till_done()
    assert hass.states.get(number).state == "20.0"
    await hass.services.async_call("number", "set_value", {"entity_id": number, "value": 35}, blocking=True)
    await hass.async_block_till_done()
    assert _commands(setup) == [(EM2["uuidAction"], "setMinSoc/35")]


async def test_em2_loads_are_discovered_from_the_state(hass, setup):
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("select", "loxone", f"{EM2['uuidAction']}-load-load-hp") is None

    setup.feed(state(EM2, "loads"), json.dumps(EM2_LOADS))
    await hass.async_block_till_done()
    heat_pump = entity_id(hass, "select", f"{EM2['uuidAction']}-load-load-hp")
    wallbox = entity_id(hass, "select", f"{EM2['uuidAction']}-load-load-wb")
    assert hass.states.get(heat_pump).state == "automatic"
    assert hass.states.get(heat_pump).attributes["power"] == 2.5
    assert hass.states.get(wallbox).state == "off"

    active = entity_id(hass, "sensor", f"{EM2['uuidAction']}-loads")
    assert hass.states.get(active).state == "1"

    # A second update neither duplicates nor loses the loads.
    changed = [dict(EM2_LOADS[0], activatedManually=True), EM2_LOADS[1]]
    setup.feed(state(EM2, "loads"), json.dumps(changed))
    await hass.async_block_till_done()
    assert hass.states.get(heat_pump).state == "on"

    await hass.services.async_call(
        "select", "select_option", {"entity_id": wallbox, "option": "automatic"}, blocking=True
    )
    await hass.services.async_call("select", "select_option", {"entity_id": heat_pump, "option": "off"}, blocking=True)
    await hass.async_block_till_done()
    assert _commands(setup) == [
        (EM2["uuidAction"], "load-wb/automatic"),
        (EM2["uuidAction"], "load-hp/deactivate"),
    ]


async def test_em2_manage_button(hass, setup):
    button = entity_id(hass, "button", f"{EM2['uuidAction']}-cmd-manage")
    await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    await hass.async_block_till_done()
    assert _commands(setup) == [(EM2["uuidAction"], "manage")]


# --- EnergyFlowMonitor ----------------------------------------------------


async def test_efm_sensors(hass, setup):
    production = entity_id(hass, "sensor", f"{EFM['uuidAction']}-Ppwr")
    house = entity_id(hass, "sensor", f"{EFM['uuidAction']}-actual0")
    car = entity_id(hass, "sensor", f"{EFM['uuidAction']}-actual1")
    co2 = entity_id(hass, "sensor", f"{EFM['uuidAction']}-CO2")

    setup.feed(state(EFM, "Ppwr"), 4.2)
    setup.feed(state(EFM, "actual0"), 1.1)
    setup.feed(state(EFM, "CO2"), 0.4)
    await hass.async_block_till_done()
    assert hass.states.get(production).state == "4.2"
    assert hass.states.get(production).attributes["unit_of_measurement"] == "kW"
    assert hass.states.get(house).state == "1.1"
    assert hass.states.get(house).attributes["friendly_name"] == "Energy Flow House"
    assert hass.states.get(car).attributes["friendly_name"] == "Energy Flow Car"
    assert hass.states.get(co2).attributes["unit_of_measurement"] == "kg/kWh"
