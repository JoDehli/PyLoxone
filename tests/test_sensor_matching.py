"""Tests for Loxone sensor matching and device class detection."""
import pytest

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    CONCENTRATION_PARTS_PER_MILLION,
    LIGHT_LUX,
    PERCENTAGE,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfVolume,
    UnitOfVolumeFlowRate,
)

from custom_components.loxone.sensor import (
    SENSOR_TYPES,
    UNAMBIGUOUS_UNITS,
    match_sensor_description,
)
from custom_components.loxone.helpers import clean_unit


# ============================================================================
# Tests: match_sensor_description
# ============================================================================


class TestSensorMatching:
    """Test match_sensor_description — the single matching function."""

    def test_temperature_celsius(self):
        desc = match_sensor_description(unit=UnitOfTemperature.CELSIUS)
        assert desc is not None
        assert desc.device_class == SensorDeviceClass.TEMPERATURE

    def test_temperature_fahrenheit(self):
        desc = match_sensor_description(unit=UnitOfTemperature.FAHRENHEIT)
        assert desc is not None
        assert desc.device_class == SensorDeviceClass.TEMPERATURE

    def test_temperature_same_description(self):
        """Both °C and °F resolve to the same description instance."""
        desc_c = match_sensor_description(unit=UnitOfTemperature.CELSIUS)
        desc_f = match_sensor_description(unit=UnitOfTemperature.FAHRENHEIT)
        assert desc_c is desc_f

    def test_illuminance_lx(self):
        desc = match_sensor_description(unit=LIGHT_LUX)
        assert desc is not None
        assert desc.device_class == SensorDeviceClass.ILLUMINANCE

    def test_illuminance_capital_lx(self):
        """Loxone sometimes sends Lx instead of lx."""
        desc = match_sensor_description(unit="Lx")
        assert desc is not None
        assert desc.device_class == SensorDeviceClass.ILLUMINANCE

    def test_illuminance_lux(self):
        desc = match_sensor_description(unit="lux")
        assert desc is not None
        assert desc.device_class == SensorDeviceClass.ILLUMINANCE

    def test_carbon_dioxide_ppm(self):
        desc = match_sensor_description(unit=CONCENTRATION_PARTS_PER_MILLION)
        assert desc is not None
        assert desc.device_class == SensorDeviceClass.CO2

    def test_energy_kwh(self):
        desc = match_sensor_description(unit=UnitOfEnergy.KILO_WATT_HOUR)
        assert desc is not None
        assert desc.device_class == SensorDeviceClass.ENERGY
        assert desc.state_class == SensorStateClass.TOTAL_INCREASING

    def test_energy_wh(self):
        desc = match_sensor_description(unit=UnitOfEnergy.WATT_HOUR)
        assert desc is not None
        assert desc.device_class == SensorDeviceClass.ENERGY

    def test_energy_mwh(self):
        desc = match_sensor_description(unit=UnitOfEnergy.MEGA_WATT_HOUR)
        assert desc is not None
        assert desc.device_class == SensorDeviceClass.ENERGY

    def test_energy_same_description(self):
        """All energy units resolve to the same description."""
        descs = [
            match_sensor_description(unit=u)
            for u in (UnitOfEnergy.KILO_WATT_HOUR, UnitOfEnergy.WATT_HOUR, UnitOfEnergy.MEGA_WATT_HOUR)
        ]
        assert descs[0] is descs[1] is descs[2]

    def test_power_watt(self):
        desc = match_sensor_description(unit=UnitOfPower.WATT)
        assert desc is not None
        assert desc.device_class == SensorDeviceClass.POWER

    def test_power_kilowatt(self):
        desc = match_sensor_description(unit=UnitOfPower.KILO_WATT)
        assert desc is not None
        assert desc.device_class == SensorDeviceClass.POWER

    def test_power_same_description(self):
        """W and kW resolve to the same description."""
        assert match_sensor_description(unit=UnitOfPower.WATT) is match_sensor_description(unit=UnitOfPower.KILO_WATT)

    def test_volume_flow_rate_liters_per_hour(self):
        desc = match_sensor_description(unit=UnitOfVolumeFlowRate.LITERS_PER_HOUR)
        assert desc is not None
        assert desc.device_class == SensorDeviceClass.VOLUME_FLOW_RATE
        assert desc.state_class == SensorStateClass.MEASUREMENT

    def test_volume_flow_rate_same_description(self):
        """All flow rate units resolve to the same description."""
        assert (
            match_sensor_description(unit=UnitOfVolumeFlowRate.LITERS_PER_HOUR)
            is match_sensor_description(unit=UnitOfVolumeFlowRate.LITERS_PER_MINUTE)
        )

    def test_water_liters(self):
        desc = match_sensor_description(unit=UnitOfVolume.LITERS)
        assert desc is not None
        assert desc.device_class == SensorDeviceClass.WATER
        assert desc.state_class == SensorStateClass.TOTAL_INCREASING

    def test_cubic_meters_no_match(self):
        """m³ is ambiguous (water, gas, air) — not auto-classified."""
        desc = match_sensor_description(unit=UnitOfVolume.CUBIC_METERS)
        assert desc is None

    def test_wind_speed(self):
        desc = match_sensor_description(unit=UnitOfSpeed.KILOMETERS_PER_HOUR)
        assert desc is not None
        assert desc.device_class == SensorDeviceClass.WIND_SPEED

    def test_humidity_by_czech_category(self):
        desc = match_sensor_description(unit=PERCENTAGE, name="Sensor", category="Vlhkost")
        assert desc is not None
        assert desc.device_class == SensorDeviceClass.HUMIDITY

    def test_humidity_by_english_category(self):
        desc = match_sensor_description(unit=PERCENTAGE, name="Sensor", category="Humidity")
        assert desc is not None
        assert desc.device_class == SensorDeviceClass.HUMIDITY

    def test_humidity_by_german_category(self):
        desc = match_sensor_description(unit=PERCENTAGE, name="Sensor", category="Feuchtigkeit")
        assert desc is not None
        assert desc.device_class == SensorDeviceClass.HUMIDITY

    def test_humidity_by_name(self):
        desc = match_sensor_description(unit=PERCENTAGE, name="Vlhkost Ložnice", category="")
        assert desc is not None
        assert desc.device_class == SensorDeviceClass.HUMIDITY

    def test_battery_by_name(self):
        desc = match_sensor_description(unit=PERCENTAGE, name="NUKI Battery", category="")
        assert desc is not None
        assert desc.device_class == SensorDeviceClass.BATTERY

    def test_battery_by_akku_name(self):
        desc = match_sensor_description(unit=PERCENTAGE, name="Akku Level", category="")
        assert desc is not None
        assert desc.device_class == SensorDeviceClass.BATTERY

    def test_no_match_unknown_unit(self):
        desc = match_sensor_description(unit="foo")
        assert desc is None

    def test_no_match_percentage_unknown_context(self):
        """% without matching name/category keywords returns None."""
        desc = match_sensor_description(unit=PERCENTAGE, name="Random", category="Unknown")
        assert desc is None


# ============================================================================
# Tests: UNAMBIGUOUS_UNITS
# ============================================================================


class TestUnambiguousUnits:
    """Test that UNAMBIGUOUS_UNITS is correctly derived from SENSOR_TYPES."""

    def test_celsius_is_unambiguous(self):
        assert UnitOfTemperature.CELSIUS in UNAMBIGUOUS_UNITS

    def test_ppm_is_unambiguous(self):
        assert CONCENTRATION_PARTS_PER_MILLION in UNAMBIGUOUS_UNITS

    def test_percentage_is_not_unambiguous(self):
        """% is ambiguous (could be humidity or battery)."""
        assert PERCENTAGE not in UNAMBIGUOUS_UNITS

    def test_lx_variants_are_unambiguous(self):
        assert LIGHT_LUX in UNAMBIGUOUS_UNITS
        assert "Lx" in UNAMBIGUOUS_UNITS
        assert "lux" in UNAMBIGUOUS_UNITS

    def test_energy_units_are_unambiguous(self):
        for u in (UnitOfEnergy.KILO_WATT_HOUR, UnitOfEnergy.WATT_HOUR, UnitOfEnergy.MEGA_WATT_HOUR):
            assert u in UNAMBIGUOUS_UNITS

    def test_power_units_are_unambiguous(self):
        for u in (UnitOfPower.WATT, UnitOfPower.KILO_WATT):
            assert u in UNAMBIGUOUS_UNITS

    def test_volume_flow_rate_units_are_unambiguous(self):
        for u in (UnitOfVolumeFlowRate.LITERS_PER_HOUR, UnitOfVolumeFlowRate.LITERS_PER_MINUTE):
            assert u in UNAMBIGUOUS_UNITS

    def test_water_units_are_unambiguous(self):
        assert UnitOfVolume.LITERS in UNAMBIGUOUS_UNITS


# ============================================================================
# Tests: Unit extraction
# ============================================================================


class TestUnitExtraction:
    """Test unit extraction from Loxone format strings."""

    def test_extract_percentage(self):
        assert clean_unit("%.1f %%") == PERCENTAGE

    def test_extract_celsius(self):
        assert clean_unit("%.1f °C") == UnitOfTemperature.CELSIUS

    def test_extract_kwh(self):
        assert clean_unit("%.2f kWh") == UnitOfEnergy.KILO_WATT_HOUR

    def test_extract_kelvin(self):
        assert clean_unit("%.1f K") == "K"

    def test_extract_lux(self):
        assert clean_unit("%.0f lux") == "lux"

    def test_extract_lx(self):
        assert clean_unit("%.0f Lx") == "Lx"

    def test_extract_ppm(self):
        assert clean_unit("%.0f ppm") == CONCENTRATION_PARTS_PER_MILLION

    def test_extract_bare_format(self):
        """Format string without a unit returns the cleaned string."""
        assert clean_unit("%.1f") == ""

    def test_extract_liters_per_hour(self):
        assert clean_unit("%.3f L/h") == UnitOfVolumeFlowRate.LITERS_PER_HOUR

    def test_extract_liters_no_space(self):
        """Loxone totalFormat often omits the space: '%.1fL'."""
        assert clean_unit("%.1fL") == UnitOfVolume.LITERS


# ============================================================================
# Tests: SENSOR_TYPES structure
# ============================================================================


class TestSensorTypesStructure:
    """Test that SENSOR_TYPES are well-formed classification objects."""

    def test_every_description_has_device_class(self):
        """No description should be missing a device_class (unlike the old humidity_or_battery)."""
        for desc in SENSOR_TYPES:
            assert desc.device_class is not None, f"{desc.key} has no device_class"

    def test_every_description_has_state_class(self):
        for desc in SENSOR_TYPES:
            assert desc.state_class is not None, f"{desc.key} has no state_class"

    def test_no_native_unit_in_descriptions(self):
        """Descriptions are classification-only; unit comes from _attr_* in __init__."""
        for desc in SENSOR_TYPES:
            assert desc.native_unit_of_measurement is None, (
                f"{desc.key} should not set native_unit_of_measurement"
            )

    def test_ten_descriptions(self):
        """One per concept: temp, wind, energy, power, volume_flow_rate, water, illuminance, co2, humidity, battery."""
        assert len(SENSOR_TYPES) == 10

    def test_unique_keys(self):
        keys = [desc.key for desc in SENSOR_TYPES]
        assert len(keys) == len(set(keys))
