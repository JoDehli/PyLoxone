"""Meter sub-sensor setup against the Loxone structure file spec.

The setup loop in ``sensor.py`` maps each Meter state (actual/total/totalNeg/
storage) to a format key in ``details``. Per spec each value format exists
twice - once for the generally formatted value and once specifically for the
negative total: ``[totalFormatNeg]`` (docs/1700_Structure-File.txt, Meter).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from custom_components.loxone import sensor as sensor_module
from custom_components.loxone.sensor import LoxoneMeterSensor


def _meter_config() -> dict:
    """A Meter whose negative-total format differs from the usual total format."""
    return {
        "controls": {
            "meter-uuid": {
                "name": "Stromzähler",
                "type": "Meter",
                "uuidAction": "meter-uuid",
                "room": "Technik",
                "cat": "Messung",
                "details": {
                    "type": "bidirectional",
                    "actualFormat": "%.0f",
                    "totalFormat": "%.2f",
                    "totalFormatNeg": "%.2f",
                    "storageFormat": "%.1f",
                },
                "states": {
                    "actual": "uuid-actual",
                    "total": "uuid-total",
                    "totalNeg": "uuid-totalneg",
                    "storage": "uuid-storage",
                },
            }
        }
    }


def _setup_meter_entities(loxconfig: dict) -> list:
    """Run the Meter part of async_setup_entry with a faked Miniserver."""
    miniserver = SimpleNamespace(
        lox_config=SimpleNamespace(json=loxconfig),
        serial="12345678",
        listeners=[],
        async_signal_new_device=lambda new_type: "loxone-new-device",
    )
    hass = SimpleNamespace(data={})

    def fake_miniserver(hass, config_entry):
        return miniserver

    created: list = []

    original = sensor_module.get_miniserver_from_hass
    sensor_module.get_miniserver_from_hass = fake_miniserver
    try:
        asyncio.run(sensor_module.async_setup_entry(
            hass=hass, config_entry=SimpleNamespace(),
            async_add_entities=lambda es, update_before_add=False: created.extend(es),
        ))
    finally:
        sensor_module.get_miniserver_from_hass = original
    return created


def _subsensors_by_suffix(entities) -> dict:
    return {
        e._attr_name.rsplit(" ", 1)[-1]: e for e in entities
    }


def test_meter_creates_one_subsensor_per_state():
    entities = _setup_meter_entities(_meter_config())
    meters = [e for e in entities if isinstance(e, LoxoneMeterSensor)]
    names = sorted(mock._attr_name for mock in meters)
    assert names == [
        "Stromzähler Actual",
        "Stromzähler Level",
        "Stromzähler Total",
        "Stromzähler Total Neg",
    ]


def test_meter_total_neg_uses_the_total_format_neg_detail():
    """Bug: 'Total Neg' was formatted with 'totalFormat' instead of
    'totalFormatNeg' - with a distinct negative format (e.g. a decimal
    separator flipped) the sub-sensor displayed the rounded positive format."""
    loxconfig = _meter_config()
    # make the two formats distinguishable:
    loxconfig["controls"]["meter-uuid"]["details"]["totalFormat"] = "%.0f"
    loxconfig["controls"]["meter-uuid"]["details"]["totalFormatNeg"] = "%.2f"

    entities = _subsensors_by_suffix(_setup_meter_entities(loxconfig))

    assert entities["Neg"]._format == "%.2f"


def test_meter_total_uses_the_total_format_detail():
    loxconfig = _meter_config()
    loxconfig["controls"]["meter-uuid"]["details"]["totalFormat"] = "%.0f"
    loxconfig["controls"]["meter-uuid"]["details"]["totalFormatNeg"] = "%.2f"

    entities = _subsensors_by_suffix(_setup_meter_entities(loxconfig))

    assert entities["Total"]._format == "%.0f"


def test_meter_actual_and_level_keep_their_own_formats():
    entities = _subsensors_by_suffix(_setup_meter_entities(_meter_config()))

    assert entities["Actual"]._format == "%.0f"
    assert entities["Level"]._format == "%.1f"


def test_meter_without_total_neg_state_creates_no_subsensor():
    loxconfig = _meter_config()
    del loxconfig["controls"]["meter-uuid"]["states"]["totalNeg"]

    entities = _subsensors_by_suffix(_setup_meter_entities(loxconfig))

    assert "Neg" not in entities
