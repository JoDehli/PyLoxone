"""
Loxone Sensors

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""
import logging
from re import match

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.sensor import (
    PLATFORM_SCHEMA,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_DEVICE_CLASS,
    CONF_NAME,
    CONF_UNIT_OF_MEASUREMENT,
    CONF_VALUE_TEMPLATE,
    STATE_OFF,
    STATE_ON,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import LoxoneEntity
from .const import CONF_ACTIONID, DOMAIN, SENDDOMAIN
from .helpers import get_all, get_cat_name_from_cat_uuid, get_room_name_from_room_uuid
from .miniserver import get_miniserver_from_hass

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

    loxconfig = miniserver.lox_config.json
    sensors = []
    if "softwareVersion" in loxconfig:
        sensors.append(LoxoneVersionSensor(loxconfig["softwareVersion"]))

    for sensor in get_all(loxconfig, "InfoOnlyAnalog"):
        sensor.update(
            {
                "typ": "analog",
                "room": get_room_name_from_room_uuid(loxconfig, sensor.get("room", "")),
                "cat": get_cat_name_from_cat_uuid(loxconfig, sensor.get("cat", "")),
            }
        )

        sensors.append(Loxonesensor(**sensor))

    for sensor in get_all(loxconfig, "TextInput"):
        sensor.update(
            {
                "room": get_room_name_from_room_uuid(loxconfig, sensor.get("room", "")),
                "cat": get_cat_name_from_cat_uuid(loxconfig, sensor.get("cat", "")),
            }
        )

        sensors.append(LoxoneTextSensor(**sensor))

    @callback
    def async_add_sensors(_):
        async_add_entities(_, True)

    miniserver.listeners.append(
        async_dispatcher_connect(
            hass, miniserver.async_signal_new_device(NEW_SENSOR), async_add_sensors
        )
    )

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

        self._state = STATE_UNKNOWN

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
    def __init__(self, version_list):
        try:
            self.version = ".".join([str(x) for x in version_list])
        except:
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
    """Representation of a Sensor."""

    def __init__(self, **kwargs):
        LoxoneEntity.__init__(self, **kwargs)
        """Initialize the sensor."""
        self._state = STATE_UNKNOWN
        self._unit_of_measurement = None
        self._format = self._get_format(kwargs.get("details", {}).get("format", ""))
        self._on_state = STATE_ON
        self._off_state = STATE_OFF
        self._parent_id = kwargs.get("parent_id", None)
        self._device_class = kwargs.get("device_class", None)
        self._state_class = kwargs.get("state_class", None)
        self.extract_attributes()

    async def event_handler(self, e):
        if self.uuidAction in e.data:
            if self.typ == "analog":
                self._state = e.data[self.uuidAction]
            elif self.typ == "digital":
                self._state = e.data[self.uuidAction]
                if self._state == 1.0:
                    self._state = self._on_state
                else:
                    self._state = self._off_state
            else:
                self._state = e.data[self.uuidAction]
            self.schedule_update_ha_state()

    def extract_attributes(self):
        """Extract certain Attributes. Not all."""
        # if "text" in self.details:
        #     self._on_state = self.details["text"]["on"]
        #     self._off_state = self.details["text"]["off"]
        if hasattr(self, "details") and "format" in self.details:
            self._format = self._get_format(self.details["format"])
            self._unit_of_measurement = self._clean_unit(self.details["format"])

    @property
    def should_poll(self):
        return False

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self._format is not None and self._state != STATE_UNKNOWN:
            try:
                return self._format % float(self._state)
            except ValueError:
                return self._state
        else:
            return self._state

    @native_value.setter
    def native_value(self, value):
        if self._format is not None and self._state != STATE_UNKNOWN:
            try:
                self._state = self._format % value
            except ValueError:
                self._state = value
        else:
            self._state = value

    @property
    def native_unit_of_measurement(self):
        """Return the unit of measurement."""
        return self._unit_of_measurement

    @property
    def icon(self):
        """Return the sensor icon."""
        if self._device_class:
            if self._device_class == "humidity":
                return "mdi:water-percent"
            elif self._device_class == "carbon_dioxide":
                return "mdi:molecule-co2"
            elif self._device_class == "temperature":
                return "mdi:thermometer"
            else:
                return "mdi:chart-bell-curve"
        else:
            if self.typ == "analog":
                return "mdi:chart-bell-curve"

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

    @property
    def device_info(self):
        _uuid = self.unique_id

        if self._parent_id:
            _uuid = self._parent_id

        if self.typ == "analog":
            return {
                "identifiers": {(DOMAIN, _uuid)},
                "name": self.name,
                "manufacturer": "Loxone",
                "model": "Sensor analog",
                "type": self.typ,
                "suggested_area": self.room,
            }
        else:
            return {
                "identifiers": {(DOMAIN, _uuid)},
                "name": self.name,
                "manufacturer": "Loxone",
                "model": "Sensor digital",
                "type": self.typ,
                "suggested_area": self.room,
            }

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        return self._device_class

    @device_class.setter
    def device_class(self, device_class):
        if not hasattr(self, "_device_class"):
            setattr(self, "_device_class", device_class)
        else:
            self._device_class = device_class

    @property
    def state_class(self):
        return self._state_class
