"""
Loxone Sensors

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""
import logging
from dataclasses import dataclass

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.sensor import (PLATFORM_SCHEMA,
                                             SensorDeviceClass, SensorEntity,
                                             SensorEntityDescription,
                                             SensorStateClass)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (CONF_DEVICE_CLASS, CONF_NAME,
                                 CONF_UNIT_OF_MEASUREMENT, CONF_VALUE_TEMPLATE,
                                 ENERGY_KILO_WATT_HOUR, ENERGY_WATT_HOUR,
                                 LIGHT_LUX, POWER_WATT,
                                 SPEED_KILOMETERS_PER_HOUR, STATE_UNKNOWN,
                                 TEMP_CELSIUS, TEMP_FAHRENHEIT, UnitOfEnergy,
                                 UnitOfPower, UnitOfSpeed, UnitOfTemperature)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import LoxoneEntity, get_miniserver_from_hass
from .const import CONF_ACTIONID, DOMAIN, SENDDOMAIN
from .helpers import (get_all, get_cat_name_from_cat_uuid,
                      get_room_name_from_room_uuid)

NEW_SENSOR = "sensors"

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "Loxone Sensor"
CONF_STATE_CLASS = "state_class"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_ACTIONID): cv.string,
        vol.Optional(CONF_NAME): cv.string,
        vol.Optional(CONF_UNIT_OF_MEASUREMENT): cv.string,
        vol.Optional(CONF_DEVICE_CLASS): cv.string,
        vol.Optional(CONF_STATE_CLASS): cv.string,
    }
)


@dataclass
class LoxoneRequiredKeysMixin:
    """Mixin for required keys."""

    loxone_format_string: str


@dataclass
class LoxoneEntityDescription(SensorEntityDescription, LoxoneRequiredKeysMixin):
    """Describes Loxone sensor entity."""


# https://github.com/jbouwh/core/blob/bf2d40efd436556908c885e3e103168719ae1471/homeassistant/components/mysensors/sensor.py
# https://github.com/jbouwh/core/blob/a5cf8210ae0080a388425bcdc7d21325d3b032c6/homeassistant/components/netatmo/sensor.py


SENSOR_TYPES: tuple[LoxoneEntityDescription, ...] = (
    LoxoneEntityDescription(
        key="temperature",
        name="Temperature",
        loxone_format_string=TEMP_CELSIUS,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    LoxoneEntityDescription(
        key="temperature_fahrenheit",
        name="Temperature",
        loxone_format_string=TEMP_FAHRENHEIT,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    LoxoneEntityDescription(
        key="windstrength",
        name="Wind Strength",
        loxone_format_string=SPEED_KILOMETERS_PER_HOUR,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.WIND_SPEED,
    ),
    LoxoneEntityDescription(
        key="kwh",
        name="Kilowatt per hour",
        loxone_format_string=ENERGY_KILO_WATT_HOUR,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.ENERGY,
    ),
    LoxoneEntityDescription(
        key="wh",
        name="Watt per hour",
        loxone_format_string=ENERGY_WATT_HOUR,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.ENERGY,
    ),
    LoxoneEntityDescription(
        key="power",
        name="Watt",
        loxone_format_string=POWER_WATT,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.POWER,
    ),
    LoxoneEntityDescription(
        key="light_level",
        name="Light Level",
        loxone_format_string=LIGHT_LUX,
        native_unit_of_measurement=LIGHT_LUX,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.ILLUMINANCE,
    ),
)


SENSOR_FORMATS = [desc.loxone_format_string for desc in SENSOR_TYPES]


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
    if config != {}:
        # Here setup all Sensors in Yaml-File
        new_sensor = LoxoneCustomSensor(**config)
        async_add_devices([new_sensor])
        return True
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entry."""
    miniserver = get_miniserver_from_hass(hass)

    loxconfig = miniserver.structure
    sensors = []
    if hasattr(miniserver, "version"):
        sensors.append(LoxoneVersionSensor(miniserver.version))

    for sensor in get_all(loxconfig, "InfoOnlyAnalog"):
        sensor.update(
            {
                "typ": "analog",
                "room": get_room_name_from_room_uuid(loxconfig, sensor.get("room", "")),
                "cat": get_cat_name_from_cat_uuid(loxconfig, sensor.get("cat", "")),
                "config_entry": config_entry,
            }
        )

        sensors.append(Loxonesensor(**sensor))

    for sensor in get_all(loxconfig, "TextInput"):
        sensor.update(
            {
                "room": get_room_name_from_room_uuid(loxconfig, sensor.get("room", "")),
                "cat": get_cat_name_from_cat_uuid(loxconfig, sensor.get("cat", "")),
                "config_entry": config_entry,
            }
        )

        sensors.append(LoxoneTextSensor(**sensor))

    @callback
    def async_add_sensors(_):
        async_add_entities(_, True)

    # miniserver.listeners.append(
    #     async_dispatcher_connect(
    #         hass, miniserver.async_signal_new_device(NEW_SENSOR), async_add_sensors
    #     )
    # )

    async_add_entities(sensors)


class LoxoneCustomSensor(LoxoneEntity, SensorEntity):
    def __init__(self, **kwargs):
        self._name = kwargs["name"]
        if "uuidAction" in kwargs:
            self.uuidAction = kwargs["uuidAction"]
        else:
            self.uuidAction = ""
        if "unit_of_measurement" in kwargs:
            self._unit_of_measurement = kwargs["unit_of_measurement"]
        else:
            self._unit_of_measurement = ""

        if "device_class" in kwargs:
            self._device_class = kwargs["device_class"]
        else:
            self._device_class = None

        if "state_class" in kwargs:
            self._state_class = kwargs["state_class"]
        else:
            self._state_class = None

        self._state = None

    async def event_handler(self, e):
        if self.uuidAction in e.data:
            data = e.data[self.uuidAction]
            if isinstance(data, (list, dict)):
                data = str(data)
                if len(data) >= 255:
                    self._state = data[:255]
                else:
                    self._state = data
            else:
                self._state = data

            self.schedule_update_ha_state()

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def native_value(self):
        return self._state

    @property
    def native_unit_of_measurement(self):
        """Return the unit of measurement of this entity, if any."""
        if self._unit_of_measurement in ["None", "none", "-"]:
            return None
        return self._unit_of_measurement

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        return {
            "uuid": self.uuidAction,
            "platform": "loxone",
        }

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        return self._device_class

    @property
    def state_class(self):
        return self._state_class


class LoxoneVersionSensor(LoxoneEntity, SensorEntity):
    def __init__(self, version_list, **kwargs):
        super().__init__(**kwargs)
        try:
            self.version = ".".join([str(x) for x in version_list])
        except Exception:
            self.version = STATE_UNKNOWN

    @property
    def name(self):
        """Return the name of the sensor."""
        return "Loxone Software Version"

    @property
    def should_poll(self):
        return False

    @property
    def native_value(self):
        return self.version

    @property
    def icon(self):
        """Return the sensor icon."""
        return "mdi:information-outline"

    @property
    def unique_id(self):
        """Return unique ID."""
        return "loxone_software_version"


class LoxoneTextSensor(LoxoneEntity, SensorEntity):
    """Representation of a Text Sensor."""

    def __init__(self, **kwargs):
        LoxoneEntity.__init__(self, **kwargs)
        self._state = STATE_UNKNOWN

    async def event_handler(self, e):
        if self.states["text"] in e.data:
            self._state = str(e.data[self.states["text"]])
            self.schedule_update_ha_state()

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
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        return {
            "uuid": self.uuidAction,
            "device_typ": self.type,
            "platform": "loxone",
            "category": self.cat,
        }


class Loxonesensor(LoxoneEntity, SensorEntity):
    """Representation of a Loxone Sensor."""

    def __init__(self, **kwargs):
        LoxoneEntity.__init__(self, **kwargs)
        """Initialize the sensor."""
        self._format = self._get_format(self.details["format"])
        self._attr_should_poll = False
        self._attr_native_unit_of_measurement = self._clean_unit(self.details["format"])
        self._parent_id = kwargs.get("parent_id", None)

        if entity_description := self._get_entity_description():
            self.entity_description = entity_description

        _uuid = self.unique_id
        if self._parent_id:
            _uuid = self._parent_id

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, _uuid)},
            name=f"{DOMAIN} {self.name}",
            manufacturer="Loxone",
            suggested_area=self.room,
            model="Sensor analog"
        )

    def _get_entity_description(self) -> SensorEntityDescription | None:
        """Return the sensor entity description."""
        if self._attr_native_unit_of_measurement in SENSOR_FORMATS:
            return SENSOR_TYPES[
                SENSOR_FORMATS.index(self._attr_native_unit_of_measurement)
            ]
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
            self.schedule_update_ha_state()

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        return {
            "uuid": self.uuidAction,
            "device_typ": self.typ + "_sensor",
            "platform": "loxone",
            "category": self.cat,
        }

