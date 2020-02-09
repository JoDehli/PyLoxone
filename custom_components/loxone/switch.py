"""
"""
import asyncio
import logging

from homeassistant.components.switch import SwitchDevice
from homeassistant.components.script import ScriptEntity
from homeassistant.const import (
    CONF_VALUE_TEMPLATE)
from homeassistant.const import DEVICE_DEFAULT_NAME
from . import get_room_name_from_room_uuid, get_cat_name_from_cat_uuid, get_all_push_buttons

_LOGGER = logging.getLogger(__name__)

DOMAIN = 'loxone'
EVENT = "loxone_event"
SENDDOMAIN = "loxone_send"


async def async_setup_platform(hass, config, async_add_devices, discovery_info={}):
    value_template = config.get(CONF_VALUE_TEMPLATE)
    if value_template is not None:
        value_template.hass = hass

    config = hass.data[DOMAIN]
    loxconfig = config['loxconfig']

    devices = []

    for push_button in get_all_push_buttons(loxconfig):
        if push_button['type'] in ["Pushbutton", "Switch"]:
            new_push_button = LoxoneSwitch(push_button['name'],
                                           push_button['uuidAction'],
                                           push_button['states']['active'],
                                           room=get_room_name_from_room_uuid(loxconfig, push_button.get('room', '')),
                                           cat=get_cat_name_from_cat_uuid(loxconfig, push_button.get('cat', '')))
            hass.bus.async_listen(EVENT, new_push_button.event_handler)
            devices.append(new_push_button)

        elif push_button['type'] == "TimedSwitch":
            new_push_button = LoxoneTimedSwitch(push_button['name'],
                                                push_button['uuidAction'],
                                                push_button['states'],
                                                room=get_room_name_from_room_uuid(loxconfig,
                                                                                  push_button.get('room', '')),
                                                cat=get_cat_name_from_cat_uuid(loxconfig, push_button.get('cat', '')))
            hass.bus.async_listen(EVENT, new_push_button.event_handler)
            devices.append(new_push_button)

        elif push_button['type'] == "Intercom":
            if "subControls" in push_button:

                for sub_name in push_button['subControls']:
                    subcontol = push_button['subControls'][sub_name]
                    if "states" in subcontol and "active" in subcontol['states']:
                        acitive = subcontol['states']['active']

                    new_push_button = LoxoneSwitch("{} - {}".format(push_button['name'], subcontol['name']),
                                                   subcontol['uuidAction'],
                                                   acitive,
                                                   room=get_room_name_from_room_uuid(loxconfig,
                                                                                     push_button.get('room', '')),
                                                   cat=get_cat_name_from_cat_uuid(loxconfig,
                                                                                  push_button.get('cat', '')))

                    hass.bus.async_listen(EVENT, new_push_button.event_handler)
                    devices.append(new_push_button)

    async_add_devices(devices)
    return True


class LoxoneTimedSwitch(SwitchDevice):
    """Representation of a loxone switch or pushbutton"""

    def __init__(self, name, uuid, states, room="", cat=""):
        self._name = name or DEVICE_DEFAULT_NAME
        self._icon = None
        self._assumed = False
        self._uuid = uuid
        self._room = room
        self._cat = cat
        self._state = False
        self._delay_remain = 0.0
        self._delay_time_total = 0.0

        if 'deactivationDelay' in states:
            self._deactivation_delay = states['deactivationDelay']
        else:
            self._deactivation_delay = ""

        if 'deactivationDelayTotal' in states:
            self._deactivation_delay_total = states['deactivationDelayTotal']
        else:
            self._deactivation_delay_total = ""

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

    async def event_handler(self, event):
        should_update = False
        if self._deactivation_delay in event.data:
            if event.data[self._deactivation_delay] == 0.0:
                self._state = False
            else:
                self._state = True

            self._delay_remain = int(event.data[self._deactivation_delay])
            should_update = True

        if self._deactivation_delay_total in event.data:
            self._delay_time_total = int(event.data[self._deactivation_delay_total])
            should_update = True

        if should_update:
            self.async_schedule_update_ha_state()

    @property
    def device_state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        if self._state == 0.0:
            return {"uuid": self._uuid,
                    "delay_time_total": str(self._delay_time_total),
                    "room": self._room,
                    "category": self._cat,
                    "device_typ": "timedswitch",
                    "plattform": "loxone"}
        else:
            return {"uuid": self._uuid,
                    "delay": str(self._delay_remain),
                    "delay_time_total": str(self._delay_time_total),
                    "room": self._room,
                    "category": self._cat,
                    "device_typ": "timedswitch",
                    "plattform": "loxone"}


class LoxoneSwitch(SwitchDevice):
    """Representation of a loxone switch or pushbutton"""

    def __init__(self, name, uuid, uuid_state, room="", cat=""):
        """Initialize the Demo switch."""
        self._name = name or DEVICE_DEFAULT_NAME
        self._state = False
        self._icon = None
        self._assumed = False
        self._uuid = uuid
        self._room = room
        self._cat = cat
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

    async def event_handler(self, event):
        if self._uuid in event.data or self._uuid_state in event.data:
            if self._uuid_state in event.data:
                self._state = event.data[self._uuid_state]
            self.async_schedule_update_ha_state()

    @property
    def device_state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        return {"uuid": self._uuid, "state_uuid": self._uuid_state, "room": self._room, "category": self._cat,
                "device_typ": "switch", "plattform": "loxone"}
