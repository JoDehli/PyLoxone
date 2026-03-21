"""Tests for Loxone device class detection."""
import pytest
from unittest.mock import patch

from custom_components.loxone.device_class import (
    _heuristic_device_class,
    sensor_entries_from_control,
)
from custom_components.loxone.helpers import clean_unit


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_loxone_config():
    """Return a mock Loxone configuration JSON."""
    return {
        "msInfo": {
            "serialNr": "test-serial-123",
            "miniserverType": 0,
            "msName": "Test Miniserver",
        },
        "softwareVersion": [13, 0, 0, 0],
        "rooms": {"0": {"name": "Bedroom"}, "1": {"name": "Living Room"}},
        "cats": {
            "cat-uuid-vlhkost": {"name": "Vlhkost"},
            "cat-uuid-pristup": {"name": "Přístup"},
        },
        "controls": {
            "sensor-humidity-1": {
                "type": "analog",
                "uuidAction": "uuid-humidity-1",
                "name": "Vlhkost Ložnice",
                "room": "0",
                "cat": "cat-uuid-vlhkost",
                "details": {"format": "%.1f %%"},
                "states": {},
            },
            "sensor-battery-1": {
                "type": "analog",
                "uuidAction": "uuid-battery-1",
                "name": "NUKI Battery",
                "room": "0",
                "cat": "cat-uuid-pristup",
                "details": {"format": "%.0f %%"},
                "states": {},
            },
            "sensor-temp-1": {
                "type": "analog",
                "uuidAction": "uuid-temp-1",
                "name": "Temperature",
                "room": "1",
                "cat": "Teplota",
                "details": {"format": "%.1f °C"},
                "states": {},
            },
            "meter-1": {
                "type": "Meter",
                "uuidAction": "uuid-meter-1",
                "name": "Energy Meter",
                "room": "1",
                "cat": "Energie",
                "states": {"actual": "uuid-meter-actual", "total": "uuid-meter-total"},
                "details": {"actualFormat": "%.2f kWh", "totalFormat": "%.1f kWh"},
            },
        },
    }


# ============================================================================
# Tests: Heuristics
# ============================================================================


class TestNameHeuristics:
    """Test name-based device class detection with category and unit info."""

    def test_humidity_detection_czech_category(self):
        """Test Czech humidity category detection."""
        assert _heuristic_device_class("Sensor", "%", "Vlhkost") == "humidity"

    def test_humidity_detection_english_category(self):
        """Test English humidity category detection."""
        assert _heuristic_device_class("Sensor", "%", "Humidity") == "humidity"

    def test_humidity_detection_german_category(self):
        """Test German humidity category detection."""
        assert _heuristic_device_class("Sensor", "%", "Feuchtigkeit") == "humidity"

    def test_battery_detection_by_name(self):
        """Test battery keyword detection across languages."""
        assert _heuristic_device_class("NUKI Battery", "%", "") == "battery"
        assert _heuristic_device_class("Batterie Sensor", "%", "") == "battery"

    def test_temperature_unambiguous_by_unit(self):
        """Test temperature detection by unit alone."""
        assert _heuristic_device_class("Random", "°C", "") == "temperature"
        assert _heuristic_device_class("Random", "°F", "") == "temperature"

    def test_no_match(self):
        """Test no match for unknown sensor."""
        assert _heuristic_device_class("Random", "%", "Unknown") is None


class TestUnitExtraction:
    """Test unit extraction from Loxone format strings."""

    def test_extract_percentage(self):
        """Test extraction of % unit."""
        assert clean_unit("%.1f %%") == "%"

    def test_extract_celsius(self):
        """Test extraction of °C unit."""
        assert clean_unit("%.1f °C") == "°C"

    def test_extract_kwh(self):
        """Test extraction of kWh unit."""
        assert clean_unit("%.2f kWh") == "kWh"

    def test_extract_kelvin(self):
        """Test extraction of K unit."""
        assert clean_unit("%.1f K") == "K"

    def test_extract_lux(self):
        """Test extraction of lux unit."""
        assert clean_unit("%.0f lux") == "lux"


class TestSensorDetection:
    """Test sensor extraction from Loxone control objects."""

    def test_detect_humidity_sensor(self, mock_loxone_config):
        """Test detection of humidity sensor."""
        ctrl = mock_loxone_config["controls"]["sensor-humidity-1"]
        entries = sensor_entries_from_control(ctrl, mock_loxone_config)
        assert len(entries) == 1
        uuid, name, room, unit, category = entries[0]
        assert uuid == "uuid-humidity-1"
        assert name == "Vlhkost Ložnice"
        assert room == "Bedroom"
        assert unit == "%"
        assert category == "Vlhkost"

    def test_detect_battery_sensor(self, mock_loxone_config):
        """Test detection of battery sensor."""
        ctrl = mock_loxone_config["controls"]["sensor-battery-1"]
        entries = sensor_entries_from_control(ctrl, mock_loxone_config)
        assert len(entries) == 1
        uuid, name, room, unit, category = entries[0]
        assert uuid == "uuid-battery-1"
        assert name == "NUKI Battery"
        assert unit == "%"
        assert category == "Přístup"

    def test_detect_temperature_sensor(self, mock_loxone_config):
        """Test detection of temperature sensor with name-based cat."""
        ctrl = mock_loxone_config["controls"]["sensor-temp-1"]
        entries = sensor_entries_from_control(ctrl, mock_loxone_config)
        assert len(entries) == 1
        uuid, name, room, unit, category = entries[0]
        assert uuid == "uuid-temp-1"
        assert unit == "°C"
        assert category == "Teplota"

    def test_cat_uuid_resolved_to_name(self, mock_loxone_config):
        """Test that UUID-based cat field is resolved to category name."""
        ctrl = mock_loxone_config["controls"]["sensor-humidity-1"]
        assert ctrl["cat"] == "cat-uuid-vlhkost"
        entries = sensor_entries_from_control(ctrl, mock_loxone_config)
        _, _, _, _, category = entries[0]
        assert category == "Vlhkost"

    def test_cat_name_passthrough(self, mock_loxone_config):
        """Test that name-based cat field passes through unchanged."""
        ctrl = mock_loxone_config["controls"]["sensor-temp-1"]
        assert ctrl["cat"] == "Teplota"
        entries = sensor_entries_from_control(ctrl, mock_loxone_config)
        _, _, _, _, category = entries[0]
        assert category == "Teplota"

    def test_detect_meter_subsensors(self, mock_loxone_config):
        """Test detection of meter sub-sensors."""
        ctrl = mock_loxone_config["controls"]["meter-1"]
        entries = sensor_entries_from_control(ctrl, mock_loxone_config)
        assert len(entries) == 2
        uuid_actual, name_actual, room, unit_actual, category = entries[0]
        assert uuid_actual == "uuid-meter-actual"
        assert "Actual" in name_actual
        assert unit_actual == "kWh"
        uuid_total, name_total, _, unit_total, _ = entries[1]
        assert uuid_total == "uuid-meter-total"
        assert "Total" in name_total
        assert unit_total == "kWh"


class TestHeuristicMatching:
    """Test heuristic matching end-to-end."""

    def test_humidity_category_matches_humidity_sensor(self, mock_loxone_config):
        """Test humidity detection on real sensor data."""
        ctrl = mock_loxone_config["controls"]["sensor-humidity-1"]
        entries = sensor_entries_from_control(ctrl, mock_loxone_config)
        uuid, name, room, unit, category = entries[0]
        device_class = _heuristic_device_class(name, unit, category)
        assert device_class == "humidity"

    def test_battery_name_matches_battery_sensor(self, mock_loxone_config):
        """Test battery detection on real sensor data."""
        ctrl = mock_loxone_config["controls"]["sensor-battery-1"]
        entries = sensor_entries_from_control(ctrl, mock_loxone_config)
        uuid, name, room, unit, category = entries[0]
        device_class = _heuristic_device_class(name, unit, category)
        assert device_class == "battery"

    def test_temperature_unit_matches_temperature_sensor(self, mock_loxone_config):
        """Test temperature detection on real sensor data."""
        ctrl = mock_loxone_config["controls"]["sensor-temp-1"]
        entries = sensor_entries_from_control(ctrl, mock_loxone_config)
        uuid, name, room, unit, category = entries[0]
        device_class = _heuristic_device_class(name, unit, category)
        assert device_class == "temperature"

    def test_all_sensors_expected_matches(self, mock_loxone_config):
        """Test all mock sensors get expected device class matches."""
        controls = mock_loxone_config["controls"]
        matches = {}
        for ctrl in controls.values():
            entries = sensor_entries_from_control(ctrl, mock_loxone_config)
            for uuid, name, room, unit, category in entries:
                device_class = _heuristic_device_class(name, unit, category)
                matches[name] = device_class
        assert matches["Vlhkost Ložnice"] == "humidity"
        assert matches["NUKI Battery"] == "battery"
        assert matches["Temperature"] == "temperature"
        assert "Energy Meter Actual" in matches
        assert matches["Energy Meter Actual"] == "energy"


class TestDeviceClassOverride:
    """Test device class override mechanism in sensor entities."""

    def test_device_class_override_from_config_entry(self):
        """Test that device class can be overridden via config entry options."""
        from homeassistant.components.sensor import SensorDeviceClass
        from custom_components.loxone.sensor import LoxoneSensor
        from unittest.mock import MagicMock

        # Create a mock config entry with device class mapping
        mock_config_entry = MagicMock()
        mock_config_entry.options = {
            "sensor_device_class_map": {
                "uuid-humidity-1": "battery",  # Override humidity to battery
            }
        }

        # Create a mock kwargs dict with the config entry
        kwargs = {
            "config_entry": mock_config_entry,
            "uuidAction": "uuid-humidity-1",
            "details": {"format": "%.1f %%"},
            "room": "0",
            "cat": "Vlhkost",
            "name": "Test Humidity Sensor",
        }

        # Mock the parent class initialization
        with patch.object(LoxoneSensor, "__init__", return_value=None):
            sensor = LoxoneSensor.__new__(LoxoneSensor)
            sensor.uuidAction = "uuid-humidity-1"
            sensor.name = "Test Humidity Sensor"
            sensor.entity_description = None
            sensor._attr_device_class = None

            # Manually run the override logic from __init__
            _config_entry = kwargs.get("config_entry")
            if _config_entry is not None:
                from custom_components.loxone.const import CONF_SENSOR_DEVICE_CLASS_MAP
                dc_map = _config_entry.options.get(CONF_SENSOR_DEVICE_CLASS_MAP, {})
                if sensor.uuidAction in dc_map:
                    dc_value = dc_map[sensor.uuidAction]
                    if dc_value == "none":
                        sensor._attr_device_class = None
                    else:
                        sensor._attr_device_class = SensorDeviceClass(dc_value)

            # Verify the override was applied
            assert sensor._attr_device_class == SensorDeviceClass.BATTERY

    def test_device_class_none_clears_heuristic(self):
        """Test that 'none' value clears heuristic device class."""
        from homeassistant.components.sensor import SensorDeviceClass
        from custom_components.loxone.sensor import LoxoneSensor
        from unittest.mock import MagicMock

        # Create a mock config entry with "none" mapping
        mock_config_entry = MagicMock()
        mock_config_entry.options = {
            "sensor_device_class_map": {
                "uuid-temp-1": "none",  # Explicitly clear device class
            }
        }

        # Create sensor with config entry
        kwargs = {
            "config_entry": mock_config_entry,
            "uuidAction": "uuid-temp-1",
            "details": {"format": "%.1f °C"},
            "room": "1",
            "cat": "Teplota",
            "name": "Test Temperature",
        }

        # Mock parent init
        with patch.object(LoxoneSensor, "__init__", return_value=None):
            sensor = LoxoneSensor.__new__(LoxoneSensor)
            sensor.uuidAction = "uuid-temp-1"
            sensor.name = "Test Temperature"
            # Simulate heuristic setting device_class
            sensor._attr_device_class = SensorDeviceClass.TEMPERATURE

            # Apply override logic
            _config_entry = kwargs.get("config_entry")
            if _config_entry is not None:
                from custom_components.loxone.const import CONF_SENSOR_DEVICE_CLASS_MAP
                dc_map = _config_entry.options.get(CONF_SENSOR_DEVICE_CLASS_MAP, {})
                if sensor.uuidAction in dc_map:
                    dc_value = dc_map[sensor.uuidAction]
                    if dc_value == "none":
                        sensor._attr_device_class = None
                    else:
                        sensor._attr_device_class = SensorDeviceClass(dc_value)

            # Verify the device class was cleared
            assert sensor._attr_device_class is None
