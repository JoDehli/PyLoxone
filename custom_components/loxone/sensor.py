import logging

from homeassistant.const import (
    CONF_VALUE_TEMPLATE, STATE_ON, STATE_OFF)
from homeassistant.helpers.entity import Entity

from . import LoxoneEntity
from . import get_room_name_from_room_uuid, get_cat_name_from_cat_uuid
from . import get_all_analog_info, get_all_digital_info

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = 'Loxone Sensor'
DEFAULT_FORCE_UPDATE = False

CONF_UUID = "uuid"
EVENT = "loxone_event"
DOMAIN = 'loxone'


async def async_setup_platform(hass, config, async_add_devices,
                               discovery_info: object = {}):
    """Set up Loxone Sensor."""

    value_template = config.get(CONF_VALUE_TEMPLATE)
    if value_template is not None:
        value_template.hass = hass

    config = hass.data[DOMAIN]
    loxconfig = config['loxconfig']

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

    async_add_devices(devices)
    return True


class LoxoneVersionSensor(Entity):
    def __init__(self, version_list):
        try:
            self.version = ".".join([str(x) for x in version_list])
        except:
            self.version = "-"

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


class Loxonesensor(LoxoneEntity):
    """Representation of a Sensor."""

    def __init__(self, **kwargs):
        LoxoneEntity.__init__(self, **kwargs)
        """Initialize the sensor."""
        self._state = 0.0
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
        if self._format is not None:
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
    def device_state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        return {"uuid": self.uuidAction, "device_typ": self.typ + "_sensor",
                "plattform": "loxone", "room": self.room, "category": self.cat,
                "show_last_changed": "true"}
