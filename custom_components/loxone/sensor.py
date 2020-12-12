"""
Loxone Sensors

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""
import logging

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import (CONF_NAME, CONF_UNIT_OF_MEASUREMENT,
                                 CONF_VALUE_TEMPLATE, STATE_OFF, STATE_ON, STATE_UNKNOWN)

from . import LoxoneEntity
from .const import CONF_ACTIONID, DOMAIN, EVENT, SENDDOMAIN
from .helpers import (get_all, get_all_analog_info, get_all_digital_info,
                      get_cat_name_from_cat_uuid, get_room_name_from_room_uuid)

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = 'Loxone Sensor'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_ACTIONID): cv.string,
        vol.Optional(CONF_NAME): cv.string,
        vol.Optional(CONF_UNIT_OF_MEASUREMENT): cv.string,
    }
)


async def async_setup_platform(hass, config, async_add_devices,
                               discovery_info: object = {}):
    """Set up Loxone Sensor from yaml"""
    value_template = config.get(CONF_VALUE_TEMPLATE)
    if value_template is not None:
        value_template.hass = hass

    # Devices from yaml
    if config != {}:
        # Here setup all Sensors in Yaml-File
        new_sensor = LoxoneCustomSensor(**config)
        hass.bus.async_listen(EVENT, new_sensor.event_handler)
        async_add_devices([new_sensor])
        return True
    return True


async def async_setup_entry(hass, config_entry, async_add_devices):
    """Set up entry."""
    loxconfig = hass.data[DOMAIN]['loxconfig']
    devices = []
    if 'softwareVersion' in loxconfig:
        version_sensor = LoxoneVersionSensor(loxconfig['softwareVersion'])
        devices.append(version_sensor)

    for sensor in get_all_analog_info(loxconfig):
        sensor.update({'typ': 'analog',
                       'room': get_room_name_from_room_uuid(loxconfig, sensor.get('room', '')),
                       'cat': get_cat_name_from_cat_uuid(loxconfig, sensor.get('cat', ''))})

        new_sensor = Loxonesensor(**sensor)
        hass.bus.async_listen(EVENT, new_sensor.event_handler)
        devices.append(new_sensor)

    for sensor in get_all_digital_info(loxconfig):
        sensor.update({'typ': 'digital',
                       'room': get_room_name_from_room_uuid(loxconfig, sensor.get('room', '')),
                       'cat': get_cat_name_from_cat_uuid(loxconfig, sensor.get('cat', ''))})

        new_sensor = Loxonesensor(**sensor)
        hass.bus.async_listen(EVENT, new_sensor.event_handler)
        devices.append(new_sensor)

    for sensor in get_all(loxconfig, "TextInput"):
        sensor.update({'room': get_room_name_from_room_uuid(loxconfig, sensor.get('room', '')),
                       'cat': get_cat_name_from_cat_uuid(loxconfig, sensor.get('cat', ''))})

        new_sensor = LoxoneTextSensor(**sensor)
        hass.bus.async_listen(EVENT, new_sensor.event_handler)
        devices.append(new_sensor)

    async_add_devices(devices, True)

    return True


class LoxoneCustomSensor(LoxoneEntity):
    def __init__(self, **kwargs):
        self._name = kwargs['name']
        if "uuidAction" in kwargs:
            self.uuidAction = kwargs['uuidAction']
        else:
            self.uuidAction = ""
        if "unit_of_measurement" in kwargs:
            self._unit_of_measurement = kwargs['unit_of_measurement']
        else:
            self._unit_of_measurement = ""

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
    def state(self):
        return self._state

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement of this entity, if any."""
        return self._unit_of_measurement


class LoxoneVersionSensor(LoxoneEntity):
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
    def state(self):
        return self.version

    @property
    def icon(self):
        """Return the sensor icon."""
        return "mdi:information-outline"

    @property
    def unique_id(self):
        """Return unique ID."""
        return "loxone_software_version"


class LoxoneTextSensor(LoxoneEntity):
    """Representation of a Text Sensor."""

    def __init__(self, **kwargs):
        LoxoneEntity.__init__(self, **kwargs)
        self._state = STATE_UNKNOWN

    async def event_handler(self, e):
        if self.states['text'] in e.data:
            self._state = str(e.data[self.states['text']])
            self.schedule_update_ha_state()

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        return self.type

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    async def async_set_value(self, value):
        """Set new value."""
        self.hass.bus.async_fire(SENDDOMAIN,
                                 dict(uuid=self.uuidAction, value="{}".format(value)))
        self.async_schedule_update_ha_state()

    @property
    def device_state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        return {"uuid": self.uuidAction, "device_typ": self.type,
                "plattform": "loxone", "room": self.room, "category": self.cat,
                "show_last_changed": "true"}


class Loxonesensor(LoxoneEntity):
    """Representation of a Sensor."""

    def __init__(self, **kwargs):
        LoxoneEntity.__init__(self, **kwargs)
        """Initialize the sensor."""
        self._state = STATE_UNKNOWN
        self._unit_of_measurement = None
        self._format = None
        self._on_state = STATE_ON
        self._off_state = STATE_OFF
        self.extract_attributes()

    async def event_handler(self, e):
        if self.uuidAction in e.data:
            if self.typ == "analog":
                self._state = round(e.data[self.uuidAction], 1)
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
        if "text" in self.details:
            self._on_state = self.details['text']['on']
            self._off_state = self.details['text']['off']
        if "format" in self.details:
            self._format = self._get_format(self.details['format'])
            self._unit_of_measurement = self._clean_unit(self.details['format'])

    @property
    def should_poll(self):
        return False

    @property
    def state(self):
        """Return the state of the sensor."""
        if self._format is not None and self._format != STATE_UNKNOWN:
            try:
                return self._format % self._state
            except ValueError:
                return self._state
        else:
            return self._state

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return self._unit_of_measurement

    @property
    def icon(self):
        """Return the sensor icon."""
        if self.typ == "analog":
            return "mdi:chart-bell-curve"

    @property
    def device_state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        return {"uuid": self.uuidAction, "device_typ": self.typ + "_sensor",
                "plattform": "loxone", "room": self.room, "category": self.cat,
                "show_last_changed": "true"}

    @property
    def device_info(self):
        if self.typ == "analog":
            return {
                "identifiers": {(DOMAIN, self.unique_id)},
                "name": self.name,
                "manufacturer": "Loxone",
                "model": "Sensor analog",
                "type": self.typ
            }
        else:
            return {
                "identifiers": {(DOMAIN, self.unique_id)},
                "name": self.name,
                "manufacturer": "Loxone",
                "model": "Sensor digital",
                "type": self.typ
            }
