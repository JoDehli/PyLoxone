import asyncio
import logging

from homeassistant.const import (
    CONF_VALUE_TEMPLATE)
from homeassistant.helpers.entity import Entity

from . import get_room_name_from_room_uuid, get_cat_name_from_cat_uuid

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = 'Loxone Sensor'
DEFAULT_FORCE_UPDATE = False

CONF_UUID = "uuid"
EVENT = "loxone_event"
DOMAIN = 'loxone'


def get_all_analog_info(json_data):
    controls = []
    for c in json_data['controls'].keys():
        if json_data['controls'][c]['type'] == "InfoOnlyAnalog":
            controls.append(json_data['controls'][c])
    return controls


def get_all_digital_info(json_data):
    controls = []
    for c in json_data['controls'].keys():
        if json_data['controls'][c]['type'] == "InfoOnlyDigital":
            controls.append(json_data['controls'][c])
    return controls


@asyncio.coroutine
def async_setup_platform(hass, config, async_add_devices,
                         discovery_info: object = {}):
    """Set up Loxone Sensor."""

    value_template = config.get(CONF_VALUE_TEMPLATE)
    if value_template is not None:
        value_template.hass = hass

    config = hass.data[DOMAIN]
    loxconfig = config['loxconfig']

    devices = []
    for sensor in get_all_analog_info(loxconfig):
        new_sensor = Loxonesensor(name=sensor['name'],
                                  uuid=sensor['uuidAction'],
                                  sensortyp="analog",
                                  room=get_room_name_from_room_uuid(loxconfig, sensor['room']),
                                  cat=get_cat_name_from_cat_uuid(loxconfig, sensor['cat']),
                                  complete_data=sensor)

        hass.bus.async_listen(EVENT, new_sensor.event_handler)
        devices.append(new_sensor)

    for sensor in get_all_digital_info(loxconfig):
        new_sensor = Loxonesensor(name=sensor['name'],
                                  uuid=sensor['uuidAction'],
                                  sensortyp="digital",
                                  room=get_room_name_from_room_uuid(loxconfig, sensor['room']),
                                  cat=get_cat_name_from_cat_uuid(loxconfig, sensor['cat']),
                                  complete_data=sensor)
        hass.bus.async_listen(EVENT, new_sensor.event_handler)
        devices.append(new_sensor)

    async_add_devices(devices)


class Loxonesensor(Entity):
    """Representation of a Sensor."""

    def __init__(self, name, uuid, sensortyp, room="", cat="",
                 complete_data=None):
        """Initialize the sensor."""
        self._state = 0.0
        self._name = name
        self._uuid = uuid
        self._sensortyp = sensortyp
        self._unit_of_measurement = None
        self._format = None
        self._on_state = "an"
        self._off_state = "aus"
        self._room = room
        self._cat = cat
        self._complete_data = complete_data
        self.extract_attributes()

    @asyncio.coroutine
    def event_handler(self, event):
        if self._uuid in event.data:
            if self._sensortyp == "analog":
                self._state = round(event.data[self._uuid], 1)
            elif self._sensortyp == "digital":
                self._state = event.data[self._uuid]
                if self._state == 1.0:
                    self._state = self._on_state
                else:
                    self._state = self._off_state
            else:
                self._state = event.data[self._uuid]
            self.schedule_update_ha_state()

    @staticmethod
    def _clean_unit(lox_format):
        cleaned_fields = []
        fields = lox_format.split(" ")
        for f in fields:
            _ = f.strip()
            if len(_) > 0:
                cleaned_fields.append(_)

        if len(cleaned_fields) > 1:
            unit = cleaned_fields[1]
            if unit == "%%":
                unit = "%"
            return unit
        return None

    @staticmethod
    def _get_format(lox_format):
        cleaned_fields = []
        fields = lox_format.split(" ")
        for f in fields:
            _ = f.strip()
            if len(_) > 0:
                cleaned_fields.append(_)

        if len(cleaned_fields) > 1:
            return cleaned_fields[0]
        return None

    def extract_attributes(self):
        """Extract certain Attributes. Not all."""
        if self._complete_data is not None:
            if "details" in self._complete_data:
                if "text" in self._complete_data['details']:
                    self._on_state = self._complete_data['details']['text'][
                        'on']
                    self._off_state = self._complete_data['details']['text'][
                        'off']
                if "format" in self._complete_data['details']:
                    self._format = self._get_format(self._complete_data['details']['format'])
                    self._unit_of_measurement = self._clean_unit(self._complete_data['details']['format'])

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

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
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._uuid

    @property
    def device_state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        return {"uuid": self._uuid, "device_typ": self._sensortyp + "_sensor",
                "plattform": "loxone", "room": self._room, "category": self._cat,
                "show_last_changed": "true"}
