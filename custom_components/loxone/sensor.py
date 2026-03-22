"""
Loxone Sensors

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""

import logging
import re
from functools import cached_property
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.sensor import (CONF_STATE_CLASS, PLATFORM_SCHEMA,
                                             SensorDeviceClass, SensorEntity,
                                             SensorEntityDescription,
                                             SensorStateClass)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (CONF_DEVICE_CLASS, CONF_NAME,
                                 CONF_UNIT_OF_MEASUREMENT, CONF_VALUE_TEMPLATE,
                                 CONCENTRATION_PARTS_PER_MILLION, LIGHT_LUX,
                                 PERCENTAGE, STATE_UNKNOWN, UnitOfEnergy,
                                 UnitOfPower, UnitOfSpeed, UnitOfTemperature)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import dt as dt_util

from . import LoxoneEntity
from .const import CONF_ACTIONID, DOMAIN, SENDDOMAIN, THROTTLE_KEEP_ALIVE_TIME
from .helpers import (add_room_and_cat_to_value_values, clean_unit, get_all,
                      get_or_create_device)
from .miniserver import get_miniserver_from_hass

NEW_SENSOR = "sensors"

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "Loxone Sensor"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_ACTIONID): cv.string,
        vol.Optional(CONF_NAME): cv.string,
        vol.Optional(CONF_UNIT_OF_MEASUREMENT): cv.string,
        vol.Optional(CONF_DEVICE_CLASS): cv.string,
        vol.Optional(CONF_STATE_CLASS): cv.string,
    }
)


class LoxoneEntityDescription(SensorEntityDescription, frozen_or_thawed=True):
    """Describes a Loxone sensor entity.

    Acts as a classification object: carries matching criteria (which Loxone
    units/keywords trigger this description) and the resulting classification
    (device_class, state_class). Presentation details (actual unit, precision)
    come from the Loxone format string via _attr_* in __init__.
    """

    loxone_format_strings: tuple[str, ...]
    category_keywords: tuple[str, ...] = ()
    name_keywords: tuple[str, ...] = ()


SENSOR_TYPES: tuple[LoxoneEntityDescription, ...] = (
    LoxoneEntityDescription(
        key="temperature",
        loxone_format_strings=(UnitOfTemperature.CELSIUS, UnitOfTemperature.FAHRENHEIT),
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    LoxoneEntityDescription(
        key="wind_speed",
        loxone_format_strings=(UnitOfSpeed.KILOMETERS_PER_HOUR,),
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.WIND_SPEED,
    ),
    LoxoneEntityDescription(
        key="energy",
        loxone_format_strings=(
            UnitOfEnergy.KILO_WATT_HOUR,
            UnitOfEnergy.WATT_HOUR,
            UnitOfEnergy.MEGA_WATT_HOUR,
        ),
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.ENERGY,
    ),
    LoxoneEntityDescription(
        key="power",
        loxone_format_strings=(UnitOfPower.WATT, UnitOfPower.KILO_WATT),
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.POWER,
    ),
    LoxoneEntityDescription(
        key="illuminance",
        loxone_format_strings=(LIGHT_LUX, "Lx", "lux"),
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.ILLUMINANCE,
    ),
    LoxoneEntityDescription(
        key="carbon_dioxide",
        loxone_format_strings=(CONCENTRATION_PARTS_PER_MILLION,),
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.CO2,
    ),
    LoxoneEntityDescription(
        key="humidity",
        loxone_format_strings=(PERCENTAGE,),
        category_keywords=("vlhkost", "humidity", "feucht", "humidité"),
        name_keywords=("vlhkost", "humidity", "feucht", "humidité"),
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.HUMIDITY,
    ),
    LoxoneEntityDescription(
        key="battery",
        loxone_format_strings=(PERCENTAGE,),
        name_keywords=("batt", "akku", "battery"),
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.BATTERY,
    ),
)

UNAMBIGUOUS_UNITS: frozenset[str] = frozenset(
    u
    for desc in SENSOR_TYPES
    if not desc.category_keywords and not desc.name_keywords
    for u in desc.loxone_format_strings
)
"""Units that map to exactly one device class without needing keyword disambiguation."""


def match_sensor_description(
    unit: str, name: str = "", category: str = "",
) -> LoxoneEntityDescription | None:
    """Find the first matching sensor description for a Loxone sensor.

    Unambiguous units (°C, kWh, ppm, …) match immediately.
    Ambiguous units (%) require a keyword hit in name or category.
    Returns None if no description matches.
    """
    name_lower = name.lower()
    cat_lower = category.lower()
    for desc in SENSOR_TYPES:
        if unit not in desc.loxone_format_strings:
            continue
        if not desc.category_keywords and not desc.name_keywords:
            return desc
        cat_match = any(kw in cat_lower for kw in desc.category_keywords)
        name_match = any(kw in name_lower for kw in desc.name_keywords)
        if cat_match or name_match:
            return desc
    return None


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_devices: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up Loxone Sensor from yaml"""
    value_template = config.get(CONF_VALUE_TEMPLATE)
    if value_template is not None:
        value_template.hass = hass

    # Devices from yaml
    if config:
        # Setup all Sensors in Yaml-File
        new_sensor = LoxoneCustomSensor(**config)
        async_add_devices([new_sensor], update_before_add=True)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entry."""
    miniserver = get_miniserver_from_hass(hass)

    loxconfig = miniserver.lox_config.json
    entities: list[Any] = [LoxoneKeepAliveSensor()]

    if "softwareVersion" in loxconfig:
        entities.append(LoxoneVersionSensor(loxconfig["softwareVersion"]))

    for sensor in get_all(loxconfig, "InfoOnlyAnalog"):
        sensor = add_room_and_cat_to_value_values(loxconfig, sensor)
        sensor.update({"type": "analog"})
        entities.append(LoxoneSensor(**sensor))

    for sensor in get_all(loxconfig, "TextInput"):
        sensor = add_room_and_cat_to_value_values(loxconfig, sensor)
        entities.append(LoxoneTextSensor(**sensor))

    for sensor in get_all(loxconfig, "Meter"):
        _LOGGER.info("Found Meter: %s", sensor)
        sensor = add_room_and_cat_to_value_values(loxconfig, sensor)
        device_info = LoxoneMeterSensor.create_DeviceInfo_from_sensor(sensor)

        for state_key, name_suffix, format_key in [
            ("actual", "Actual", "actualFormat"),
            ("total", "Total", "totalFormat"),
            ("totalNeg", "Total Neg", "totalFormat"),
            ("storage", "Level", "storageFormat"),
        ]:
            if state_key in sensor["states"]:
                subsensor = {
                    "device_info": device_info,
                    "parent_id": sensor["uuidAction"],
                    "uuidAction": sensor["states"][state_key],
                    "type": "analog",
                    "room": sensor.get("room", ""),
                    "cat": sensor.get("cat", ""),
                    "name": f"{sensor['name']} {name_suffix}",
                    "details": {"format": sensor["details"][format_key]},
                    "async_add_devices": async_add_entities,
                    "config_entry": config_entry,
                }
                entities.append(LoxoneMeterSensor(**subsensor))

    @callback
    def async_add_sensors(_):
        async_add_entities(_, True)

    miniserver.listeners.append(
        async_dispatcher_connect(
            hass, miniserver.async_signal_new_device(NEW_SENSOR), async_add_sensors
        )
    )

    async_add_entities(entities, update_before_add=True)


class LoxoneCustomSensor(LoxoneEntity, SensorEntity):
    def __init__(self, **kwargs):
        self._attr_name = kwargs.pop("name", None)
        self._attr_state_class = kwargs.pop("state_class", None)
        self._attr_device_class = kwargs.pop("device_class", None)
        self._attr_native_unit_of_measurement = kwargs.pop("unit_of_measurement", None)
        self._attr_native_value = None  # Initialize state
        # Must be after the kwargs.pop functions!
        super().__init__(**kwargs)

    @cached_property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self.uuidAction + self._attr_name

    async def event_handler(self, e):
        if self.uuidAction in e.data:
            data = e.data[self.uuidAction]
            if isinstance(data, (list, dict)):
                data = str(data)
                if len(data) >= 255:
                    self._attr_native_value = data[:255]
                else:
                    self._attr_native_value = data
            else:
                self._attr_native_value = data

            self.async_schedule_update_ha_state()

    @property
    def native_unit_of_measurement(self):
        """Return the unit of measurement of this entity, if any."""
        if self._attr_native_unit_of_measurement in ["None", "none", "-"]:
            return None
        return self._attr_native_unit_of_measurement

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes."""
        return {**self._attr_extra_state_attributes}


class LoxoneKeepAliveSensor(LoxoneEntity, SensorEntity):
    _attr_name = "Loxone Last Keep Alive Message"
    _attr_icon = "mdi:information-outline"
    _attr_unique_id = "loxone_keep_alive_sensor_uuid"
    _attr_device_class = SensorDeviceClass.TIMESTAMP  # tell HA this is a timestamp

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._attr_native_value = None

    @cached_property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._attr_unique_id

    async def event_handler(self, e):
        if "keep_alive" in e.data and e.data["keep_alive"] == "received":
            now = dt_util.utcnow()
            # only update if at least 60 seconds passed since last update
            if self._attr_native_value is not None:
                time_since_last = (now - self._attr_native_value).total_seconds()
                if time_since_last < THROTTLE_KEEP_ALIVE_TIME:
                    # too soon, skip this update
                    return

            # update the timestamp
            self._attr_native_value = now
            self.async_schedule_update_ha_state()

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes."""
        return {**self._attr_extra_state_attributes}


class LoxoneVersionSensor(LoxoneEntity, SensorEntity):
    _attr_should_poll = False
    _attr_name = "Loxone Software Version"
    _attr_icon = "mdi:information-outline"
    _attr_unique_id = "loxone_software_version"

    def __init__(self, version_list, **kwargs):
        super().__init__(**kwargs)
        try:
            self._attr_native_value = ".".join([str(x) for x in version_list])
        except Exception:
            self._attr_native_value = STATE_UNKNOWN

    @cached_property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._attr_unique_id


class LoxoneTextSensor(LoxoneEntity, SensorEntity):
    """Representation of a Text Sensor."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._state = STATE_UNKNOWN

    async def event_handler(self, e):
        if self.states["text"] in e.data:
            self._state = str(e.data[self.states["text"]])
            self.async_schedule_update_ha_state()

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        return self.type

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self._state

    async def async_set_value(self, value):
        """Set new value."""
        self.hass.bus.async_fire(
            SENDDOMAIN, dict(uuid=self.uuidAction, value="{}".format(value))
        )
        self.async_schedule_update_ha_state()

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes."""
        return {
            **self._attr_extra_state_attributes,
            "device_type": self.type,
        }


class LoxoneSensor(LoxoneEntity, SensorEntity):
    """Representation of a Loxone Sensor."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._format = self._get_format(self.details["format"])
        self._attr_should_poll = False
        self._attr_native_unit_of_measurement = clean_unit(self.details["format"])
        self._parent_id = kwargs.get("parent_id", None)

        precision = self._parse_digits_after_decimal(self.details["format"])
        if precision:
            self._attr_suggested_display_precision = precision

        # Device class is detected automatically from unit/category/name.
        # To override for a specific entity, use HA's customize in configuration.yaml:
        #   homeassistant:
        #     customize:
        #       sensor.my_sensor:
        #         device_class: battery
        desc = match_sensor_description(
            unit=self._attr_native_unit_of_measurement,
            name=self.name,
            category=kwargs.get("cat", ""),
        )
        if desc:
            self.entity_description = desc
        else:
            self._attr_state_class = SensorStateClass.MEASUREMENT

        _uuid = self.unique_id
        if self._parent_id:
            _uuid = self._parent_id

        self.type = "Sensor analog"
        self._attr_device_info = get_or_create_device(
            _uuid, self.name, self.type, self.room
        )

    def _parse_digits_after_decimal(self, format_string):
        """Parse digits after the decimal point from the format string."""
        pattern = r"\.(\d+)"
        match = re.search(pattern, format_string)
        if match:
            digits = int(match.group(1))
            return digits
        return None

    @property
    def available(self) -> bool:
        """Return entity availability."""
        return self.state is not None

    def _get_lox_rounded_value(self, value):
        try:
            return float(self._format % float(value))
        except ValueError:
            return value

    async def event_handler(self, e):
        if self.uuidAction in e.data:
            self._attr_native_value = e.data[self.uuidAction]
            self.async_schedule_update_ha_state()

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes."""
        return {
            **self._attr_extra_state_attributes,
            "device_type": self.type + "_sensor",
        }


class LoxoneMeterSensor(LoxoneSensor, SensorEntity):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        device_info = kwargs.get("device_info", None)
        if device_info:
            self._attr_device_info = device_info

    @staticmethod
    def create_DeviceInfo_from_sensor(sensor) -> DeviceInfo:
        try:
            # For legacy Meter
            model = sensor["details"]["type"].capitalize() + " Meter"
        except (KeyError, TypeError):
            model = "Meter"
        return DeviceInfo(
            identifiers={(DOMAIN, sensor["uuidAction"])},
            name=sensor["name"],
            manufacturer="Loxone",
            model=model,
        )
