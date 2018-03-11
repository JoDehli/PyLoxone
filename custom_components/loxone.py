"""
Component to create an interface to the Loxone Miniserver.

For more details about this component, please refer to the documentation at
https://home-assistant.io/components/loxone/
"""

import asyncio
import json
import logging
import traceback

import homeassistant.components.mqtt as mqtt
import homeassistant.helpers.config_validation as cv
import requests
import voluptuous as vol
from homeassistant.components.mqtt import (
    CONF_STATE_TOPIC)

from homeassistant.const import CONF_HOST, CONF_PORT, CONF_USERNAME, \
    CONF_PASSWORD, EVENT_PLATFORM_DISCOVERED
from homeassistant.helpers import discovery
from requests.auth import HTTPBasicAuth

DEPENDENCIES = ['mqtt']

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 8080

DOMAIN = 'loxone'
SENDDOMAIN = "loxone_send"
DEFAULT = ""
ATTR_UUID = 'uuid'
ATTR_VALUE = 'value'
ATTR_COMMAND = "command"

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_STATE_TOPIC): cv.string,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
    }),
}, extra=vol.ALLOW_EXTRA)


class loxApp(object):
    def __init__(self):
        self.host = None
        self.port = None
        self.loxapppath = "/data/LoxAPP3.json"

        self.lox_user = None
        self.lox_pass = None
        self.json = None
        self.responsecode = None

    def getJson(self):
        url = "http://" + str(self.host) + ":" + str(
            self.port) + self.loxapppath
        my_response = requests.get(url, auth=HTTPBasicAuth(self.lox_user,
                                                           self.lox_pass),
                                   verify=False)
        if my_response.status_code == 200:
            self.json = my_response.json()
        else:
            self.json = None
        self.responsecode = my_response.status_code
        return self.responsecode

    def getAllAnalogInfo(self):
        controls = []
        for c in self.json['controls'].keys():
            if self.json['controls'][c]['type'] == "InfoOnlyAnalog":
                controls.append(self.json['controls'][c])
        return controls


@asyncio.coroutine
def async_setup(hass, config):
    """setup loxone"""

    @asyncio.coroutine
    def update_all_data_once(event):
        """Run when Home Assistant starts."""
        yield from hass.services.async_call(DOMAIN, 'command',
                                            {'command': 'getAllUiids'})

    hass.bus.async_listen_once(
        EVENT_PLATFORM_DISCOVERED, update_all_data_once)

    try:
        lox_config = loxApp()
        lox_config.lox_user = config[DOMAIN][CONF_USERNAME]
        lox_config.lox_pass = config[DOMAIN][CONF_PASSWORD]
        lox_config.host = config[DOMAIN][CONF_HOST]
        lox_config.port = config[DOMAIN][CONF_PORT]
        request_code = lox_config.getJson()
        if request_code == 200 or request_code == "200":
            hass.data[DOMAIN] = config[DOMAIN]
            hass.data[DOMAIN]['loxconfig'] = lox_config.json
            discovery.load_platform(hass, "cover", "loxone")
            del lox_config
        else:
            _LOGGER.error("Unable to connect to Loxone")
    except:
        _LOGGER.error("Unable to connect to Loxone")
        return False

    @asyncio.coroutine
    def handle_loxone_service_call(call):
        """Handle event bus services."""
        value = call.data.get(ATTR_VALUE, DEFAULT)
        device_uuid = call.data.get(ATTR_UUID, DEFAULT)
        command_value = call.data.get(ATTR_COMMAND, DEFAULT)
        print("-----handle_loxone_service_call-----")
        if command_value is not "":
            msg = '{{"command":"{}"}}'.format(command_value)
            mqtt.async_publish(hass, config[DOMAIN][CONF_STATE_TOPIC], msg)
        elif device_uuid is not "" and value is not "":
            msg = '{{"uuid":"{}", "value":"{}"}}'.format(device_uuid, value)
            mqtt.async_publish(hass, config[DOMAIN][CONF_STATE_TOPIC], msg)

    hass.services.async_register(DOMAIN, 'command', handle_loxone_service_call)

    @asyncio.coroutine
    def _event_receiver(topic, payload, qos):
        """Receive events published by and fire them on this hass instance."""
        if not topic == config[DOMAIN][CONF_STATE_TOPIC]:
            return
        if isinstance(payload, str):
            payload = json.loads(payload)
        if "topic" in payload and payload['topic'] == "fromLoxone":
            hass.bus.fire(DOMAIN, payload)

    yield from mqtt.async_subscribe(hass, config[DOMAIN][CONF_STATE_TOPIC],
                                    _event_receiver)

    @asyncio.coroutine
    def listen_loxone_send(event):
        """Listen for change Events from Loxone Components"""
        try:
            if event.event_type == SENDDOMAIN and isinstance(event.data, dict):
                if event.data['topic'] == "toLoxone" and 'command' in event.data:
                    msg = '{{"topic":"{}", "command":"{}", "value":{}}}'.format(
                        event.data['topic'], event.data['command'],
                        event.data['value'])
                    mqtt.async_publish(hass, config[DOMAIN][CONF_STATE_TOPIC],
                                       msg)
        except:
            traceback.print_exc()

    hass.bus.async_listen(SENDDOMAIN, listen_loxone_send)

    return True