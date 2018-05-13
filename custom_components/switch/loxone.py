"""
"""
import asyncio
import json
import logging

from homeassistant.components.switch import SwitchDevice
from homeassistant.const import DEVICE_DEFAULT_NAME
from homeassistant.const import (
    CONF_VALUE_TEMPLATE)

_LOGGER = logging.getLogger(__name__)

DOMAIN = 'loxone'
EVENT = "loxone_event"
SENDDOMAIN = "loxone_send"


def get_all_push_buttons(json_data):
    controls = []
    for c in json_data['controls'].keys():
        if json_data['controls'][c]['type'] in ["Pushbutton", "Switch"]:
            controls.append(json_data['controls'][c])
    return controls


@asyncio.coroutine
def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    value_template = config.get(CONF_VALUE_TEMPLATE)
    if value_template is not None:
        value_template.hass = hass

    if discovery_info is not None:
        config = discovery_info['config']
        loxconfig = discovery_info['loxconfig']
    else:
        config = hass.data[DOMAIN]
        loxconfig = config['loxconfig']

    devices = []

    for push_button in get_all_push_buttons(loxconfig):
        new_push_button = LoxoneSwitch(push_button['name'],
                                       push_button['uuidAction'],
                                       push_button['states']['active'])

        hass.bus.async_listen(EVENT, new_push_button.event_handler)
        devices.append(new_push_button)

    async_add_devices(devices)


class LoxoneSwitch(SwitchDevice):
    """Representation of a loxone switch or pushbutton"""

    def __init__(self, name, uuid, uuid_state):
        """Initialize the Demo switch."""
        self._name = name or DEVICE_DEFAULT_NAME
        self._state = False
        self._icon = None
        self._assumed = False
        self._uuid = uuid
        self._uuid_state = uuid_state

    @property
    def should_poll(self):
        """No polling needed for a demo switch."""
        return False

    @property
    def name(self):
        """Return the name of the device if any."""
        return self._name

    @property
    def icon(self):
        """Return the icon to use for device if any."""
        return self._icon

    @property
    def assumed_state(self):
        """Return if the state is based on assumptions."""
        return self._assumed

    @property
    def is_on(self):
        """Return true if switch is on."""
        return self._state

    def turn_on(self, **kwargs):
        """Turn the switch on."""
        self.hass.bus.async_fire(SENDDOMAIN,
                                 dict(uuid=self._uuid, value="pulse"))
        self._state = True
        self.schedule_update_ha_state()

    def turn_off(self, **kwargs):
        """Turn the device off."""
        self.hass.bus.async_fire(SENDDOMAIN,
                                 dict(uuid=self._uuid, value="pulse"))
        self._state = False
        self.schedule_update_ha_state()

    @asyncio.coroutine
    def event_handler(self, event):
        if self._uuid in event.data or self._uuid_state in event.data:
            if self._uuid_state in event.data:
                self._state = event.data[self._uuid_state]
            self.update()
            self.schedule_update_ha_state()

    @property
    def device_state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        return {"uuid":self._uuid, "state_uuid":self._uuid_state}