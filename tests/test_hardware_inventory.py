"""Tests for physical Loxone Air hardware discovery and mapping."""

from custom_components.loxone.hardware.api import (
    _as_float,
    apply_control_mappings,
    mapping_key,
    parse_channel_names,
    parse_enum_devices,
    parse_status_xml,
)

ENUMDEV = "Miniserver (ABCDEF123456), Air Base (ABCDEF123456.0C000001), Window Handle (0C000001.B299C3)"

STATUS = """
<Status>
  <Miniserver Name="Test Home" Version="16.1.10.17" />
  <Extension Type="Air Base Extension" Serial="0C000001" Version="15.5.3.11" />
  <AirDevice Type="Fenstergriff Air" Serial="50:4F:94:FF:FE:B2:99:C3"
    Name="EG_WZ_Fenster_Rechts" Place="Wohnzimmer" Inst="Rechts"
    Online="true" Battery="70%" BattWeak="false" Version="15.5.2.19"
    HwVersion="1" Hops="1" QualityExt="2" QualityDev="2"
    LastReceived="2026-09-14 20:00:00" />
  <AirDevice Type="Nano IO Air" Serial="50:4F:94:FF:FE:B3:56:B9"
    Name="EG_WZ_Terassentuer_Bedienfeld" Place="Wohnzimmer"
    Online="true" Battery="127" Version="16.1.10.17" HwVersion="2" />
</Status>
"""

STRUCTURE = {
    "rooms": {"room-1": {"name": "Wohnzimmer"}},
    "cats": {"cat-1": {"name": "Fenster"}},
    "controls": {
        "position-control": {
            "name": "EG_WZ_Fenster_Rechts_Position",
            "type": "InfoOnlyAnalog",
            "uuidAction": "POSITION-CONTROL",
            "room": "room-1",
            "cat": "cat-1",
            "states": {"value": "POSITION-STATE"},
        },
        "alarm-control": {
            "name": "EG_WZ_Fenster_Rechts_Alarm",
            "type": "InfoOnlyDigital",
            "uuidAction": "ALARM-CONTROL",
            "states": {"active": "ALARM-STATE"},
        },
        "blind-control": {
            "name": "EG_WZ_Rolladen_Terrasse",
            "type": "Jalousie",
            "uuidAction": "BLIND-CONTROL",
            "states": {"position": "BLIND-POSITION"},
        },
    },
}


def test_temperature_parser_accepts_loxone_unit_suffix() -> None:
    """System-temperature values may include the degree symbol."""
    assert _as_float("34.0°") == 34.0
    assert _as_float("34,5 °C") == 34.5


def test_parse_inventory_only_includes_window_handles() -> None:
    """Generic Air devices remain outside the hardware inventory."""
    serial, air_base = parse_enum_devices(ENUMDEV)
    data = parse_status_xml(STATUS, serial, air_base, STRUCTURE)

    assert serial == "ABCDEF123456"
    assert air_base == "0C000001"
    assert set(data.devices) == {"B299C3"}
    assert data.devices["B299C3"].is_window_handle
    assert data.devices["B299C3"].battery == 70
    assert data.controls["position-control"].room == "Wohnzimmer"


def test_channel_designations_are_read_from_inputs_and_outputs() -> None:
    """Physical channel names are retained as the automatic join key."""
    value = (
        "EG_WZ_Fenster_Rechts_Position (0C000001.B299C3.AI2,0), "
        "Orientierungslicht (0C000001.B356B9.Q1,0), "
        "Systemtemperatur (0C000001.B356B9.ST,34.0)"
    )
    names = parse_channel_names(value)

    assert names["0C000001.B299C3.AI2"] == "EG_WZ_Fenster_Rechts_Position"
    assert names["0C000001.B356B9.Q1"] == "Orientierungslicht"
    assert names["0C000001.B356B9.ST"] == "Systemtemperatur"


def test_window_controls_are_automatically_mapped() -> None:
    """Both handle roles map to their single matching LoxAPP controls."""
    data = parse_status_xml(STATUS, "ABCDEF123456", "0C000001", STRUCTURE)
    names = {
        "0C000001.B299C3.AI2": "EG_WZ_Fenster_Rechts_Position",
        "0C000001.B299C3.I4": "EG_WZ_Fenster_Rechts_Alarm",
    }
    routing = apply_control_mappings(data, names)
    handle = data.devices["B299C3"]

    assert handle.automatic_mappings == {
        "position": "position-control",
        "vibration": "alarm-control",
    }
    assert handle.resolved_mappings == handle.automatic_mappings
    assert routing == {
        "position-state": ("B299C3", "position"),
        "alarm-state": ("B299C3", "vibration"),
    }


def test_display_name_is_not_used_for_automatic_mapping() -> None:
    """Only the physical channel designation is an automatic join key."""
    data = parse_status_xml(STATUS, "ABCDEF123456", "0C000001", STRUCTURE)

    apply_control_mappings(data, {})

    assert data.devices["B299C3"].automatic_mappings == {}
    assert data.devices["B299C3"].resolved_mappings == {}


def test_explicit_unassignment_disables_an_automatic_handle_mapping() -> None:
    """An empty manual UUID disables one automatic handle mapping."""
    data = parse_status_xml(STATUS, "ABCDEF123456", "0C000001", STRUCTURE)
    handle = data.devices["B299C3"]
    manual = {
        mapping_key(handle.serial, "position"): "",
    }
    apply_control_mappings(
        data,
        {"0C000001.B299C3.AI2": "EG_WZ_Fenster_Rechts_Position"},
        manual,
    )

    assert "position" in handle.automatic_mappings
    assert "position" not in handle.resolved_mappings
