"""
Component to create an interface to the Loxone Miniserver.

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""
import asyncio
import logging
import traceback

import homeassistant.components.group as group
import voluptuous as vol
from homeassistant.const import (CONF_HOST, CONF_PASSWORD, CONF_PORT,
                                 CONF_USERNAME, EVENT_COMPONENT_LOADED,
                                 EVENT_HOMEASSISTANT_START,
                                 EVENT_HOMEASSISTANT_STOP)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.entity import Entity

from .api import LoxWs, LoxApp
from .helpers import get_miniserver_type

REQUIREMENTS = ['websockets', "pycryptodome", "numpy", "requests_async"]

from .const import (AES_KEY_SIZE, ATTR_CODE, ATTR_COMMAND, ATTR_UUID,
                    ATTR_VALUE, CMD_AUTH_WITH_TOKEN, CMD_ENABLE_UPDATES,
                    CMD_ENCRYPT_CMD, CMD_GET_KEY, CMD_GET_KEY_AND_SALT,
                    CMD_GET_PUBLIC_KEY, CMD_GET_VISUAL_PASSWD,
                    CMD_KEY_EXCHANGE, CMD_REFRESH_TOKEN,
                    CMD_REFRESH_TOKEN_JSON_WEB, CMD_REQUEST_TOKEN,
                    CMD_REQUEST_TOKEN_JSON_WEB, CONF_SCENE_GEN, DEFAULT,
                    DEFAULT_PORT, DEFAULT_TOKEN_PERSIST_NAME, DOMAIN,
                    DOMAIN_DEVICES, ERROR_VALUE, EVENT, IV_BYTES,
                    KEEP_ALIVE_PERIOD, LOXAPPPATH, LOXONE_PLATFORMS,
                    SALT_BYTES, SALT_MAX_AGE_SECONDS, SALT_MAX_USE_COUNT,
                    SECUREDSENDDOMAIN, SENDDOMAIN, TIMEOUT, TOKEN_PERMISSION,
                    TOKEN_REFRESH_DEFAULT_SECONDS, TOKEN_REFRESH_RETRY_COUNT,
                    TOKEN_REFRESH_SECONDS_BEFORE_EXPIRY)

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
        vol.Optional(CONF_SCENE_GEN, default=True): cv.boolean,
    }),
}, extra=vol.ALLOW_EXTRA)

'''@JoDehli Any specific reason you are using async_add_devices() here? 
https://github.com/JoDehli/PyLoxone/blob/dev/custom_components/loxone/light.py#L160 Also, manually adding devices to 
hass is not necessary unless you are creating a device that has no entities. For entities that belong to a device, 
use async_add_entities(). Devices will be automatically created based on the provided device info in the entity, 
and the entities will be added to it. A tip is to use base classes for devices. Take a look at the Deconz integration 
for example '''


# https://github.com/home-assistant/core/blob/48e954e038430f9f58ebf67dc80073978928dbab/homeassistant/components/broadlink/__init__.py


async def async_unload_entry(hass, config_entry):
    """ Restart of Home Assistant needed."""
    # TODO: Implement a complete restart of the loxone component without restart HomeAssistant
    # TODO: Unload device
    return False


async def async_setup(hass, config):
    """setup loxone"""
    if DOMAIN in config:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": "import"}, data=config[DOMAIN]
            )
        )
    return True


async def async_set_options(hass, config_entry):
    data = {**config_entry.data}
    options = {
        CONF_HOST: data.pop(CONF_HOST, ""),
        CONF_PORT: data.pop(CONF_PORT, DEFAULT_PORT),
        CONF_USERNAME: data.pop(CONF_USERNAME, ""),
        CONF_PASSWORD: data.pop(CONF_PASSWORD, ""),
        CONF_SCENE_GEN: data.pop(CONF_SCENE_GEN, ""),
    }
    hass.config_entries.async_update_entry(
        config_entry, data=data, options=options
    )


async def async_setup_entry(hass, config_entry):
    if not config_entry.options:
        await async_set_options(hass, config_entry)

    config = {DOMAIN: dict(config_entry.options)}

    res = False
    try:
        lox_config = LoxApp()
        lox_config.lox_user = config_entry.options[CONF_USERNAME]
        lox_config.lox_pass = config_entry.options[CONF_PASSWORD]
        lox_config.host = config_entry.options[CONF_HOST]
        lox_config.port = config_entry.options[CONF_PORT]
        request_code = await lox_config.getJson()

        if request_code == 200 or request_code == "200":
            hass.data[DOMAIN] = config[DOMAIN]
            hass.data[DOMAIN]['loxconfig'] = lox_config.json

            lox = LoxWs(user=config[DOMAIN][CONF_USERNAME],
                        password=config[DOMAIN][CONF_PASSWORD],
                        host=config[DOMAIN][CONF_HOST],
                        port=config[DOMAIN][CONF_PORT],
                        loxconfig=config[DOMAIN]['loxconfig'])

            res = await lox.async_init()
    except ConnectionError:
        _LOGGER.error("Connection Error")
        return False

    # https://github.com/home-assistant/core/blob/dev/homeassistant/components/upnp/__init__.py
    device_registry = await dr.async_get_registry(hass)
    identify = hass.data[DOMAIN]['loxconfig']['msInfo']['serialNr']
    device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        connections={},
        identifiers={(DOMAIN, identify)},
        name=hass.data[DOMAIN]['loxconfig']['msInfo']['msName'],
        manufacturer="Loxone",
        sw_version=".".join([str(x) for x in hass.data[DOMAIN]['loxconfig']['softwareVersion']]),
        model=get_miniserver_type(hass.data[DOMAIN]['loxconfig']['msInfo']['miniserverType']),
    )

    await asyncio.sleep(0.5)
    for platform in LOXONE_PLATFORMS:
        _LOGGER.debug("starting loxone {}...".format(platform))
        # https://github.com/home-assistant/core/blob/dev/homeassistant/components/upnp/__init__.py
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(config_entry, platform)
        )
        hass.async_create_task(
            async_load_platform(hass, platform, DOMAIN, {}, config_entry)
        )

    del lox_config

    async def message_callback(message):
        hass.bus.async_fire(EVENT, message)

    async def start_loxone(event):
        await lox.start()

    async def stop_loxone(event):
        _ = await lox.stop()
        _LOGGER.debug(_)

    async def loxone_discovered(event):
        if "component" in event.data:
            if event.data['component'] == DOMAIN:
                try:
                    _LOGGER.info("loxone discovered")
                    await asyncio.sleep(0.1)
                    entity_ids = hass.states.async_all()
                    sensors_analog = []
                    sensors_digital = []
                    switches = []
                    covers = []
                    lights = []
                    climates = []

                    for s in entity_ids:
                        s_dict = s.as_dict()
                        attr = s_dict['attributes']
                        if "plattform" in attr and \
                                attr['plattform'] == DOMAIN:
                            if attr['device_typ'] == "analog_sensor":
                                sensors_analog.append(s_dict['entity_id'])
                            elif attr['device_typ'] == "digital_sensor":
                                sensors_digital.append(s_dict['entity_id'])
                            elif attr['device_typ'] == "Jalousie" or \
                                    attr['device_typ'] == "Gate" or attr['device_typ'] == "Window":
                                covers.append(s_dict['entity_id'])
                            elif attr['device_typ'] == "Switch" or \
                                    attr['device_typ'] == "Pushbutton" or \
                                    attr['device_typ'] == "TimedSwitch":
                                switches.append(s_dict['entity_id'])
                            elif attr['device_typ'] == "LightControllerV2" or \
                                    attr['device_typ'] == "Dimmer":
                                lights.append(s_dict['entity_id'])
                            elif attr['device_typ'] == "IRoomControllerV2":
                                climates.append(s_dict['entity_id'])
                            elif attr['device_typ'] == "IRoomControllerV2":
                                climates.append(s_dict['entity_id'])

                    sensors_analog.sort()
                    sensors_digital.sort()
                    covers.sort()
                    switches.sort()
                    lights.sort()
                    climates.sort()

                    await group.Group.async_create_group(
                        hass, "Loxone Analog Sensors", object_id="loxone_analog", entity_ids=sensors_analog)

                    await group.Group.async_create_group(
                        hass, "Loxone Digital Sensors", object_id="loxone_digital", entity_ids=sensors_digital)

                    await group.Group.async_create_group(
                        hass, "Loxone Switches", object_id="loxone_switches", entity_ids=switches)

                    await group.Group.async_create_group(
                        hass, "Loxone Covers", object_id="loxone_covers", entity_ids=covers)

                    await group.Group.async_create_group(
                        hass, "Loxone Lights", object_id="loxone_lights", entity_ids=lights)

                    await group.Group.async_create_group(
                        hass, "Loxone Room Controllers", object_id="loxone_climates", entity_ids=climates)

                    await hass.async_block_till_done()

                    await group.Group.async_create_group(
                        hass, "Loxone Group", object_id="loxone_group", entity_ids=["group.loxone_analog",
                                                                                    "group.loxone_digital",
                                                                                    "group.loxone_switches",
                                                                                    "group.loxone_covers",
                                                                                    "group.loxone_lights",
                                                                                    ])
                except:
                    traceback.print_exc()

    if res is True:
        lox.message_call_back = message_callback
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, start_loxone)
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop_loxone)
        hass.bus.async_listen_once(EVENT_COMPONENT_LOADED, loxone_discovered)

        async def listen_loxone_send(event):
            """Listen for change Events from Loxone Components"""
            try:
                if event.event_type == SENDDOMAIN and isinstance(event.data,
                                                                 dict):
                    value = event.data.get(ATTR_VALUE, DEFAULT)
                    device_uuid = event.data.get(ATTR_UUID, DEFAULT)
                    await lox.send_websocket_command(device_uuid, value)

                elif event.event_type == SECUREDSENDDOMAIN and isinstance(event.data,
                                                                          dict):
                    value = event.data.get(ATTR_VALUE, DEFAULT)
                    device_uuid = event.data.get(ATTR_UUID, DEFAULT)
                    code = event.data.get(ATTR_CODE, DEFAULT)
                    await lox.send_secured__websocket_command(device_uuid, value, code)

            except ValueError:
                traceback.print_exc()

        hass.bus.async_listen(SENDDOMAIN, listen_loxone_send)
        hass.bus.async_listen(SECUREDSENDDOMAIN, listen_loxone_send)

        async def handle_websocket_command(call):
            """Handle websocket command services."""
            value = call.data.get(ATTR_VALUE, DEFAULT)
            device_uuid = call.data.get(ATTR_UUID, DEFAULT)
            await lox.send_websocket_command(device_uuid, value)

        hass.services.async_register(DOMAIN, 'event_websocket_command',
                                     handle_websocket_command)

    else:
        res = False
        _LOGGER.info("Error")
    return res


class LoxoneEntity(Entity):
    """
    @DynamicAttrs
    """

    def __init__(self, **kwargs):
        self._name = ""
        for key in kwargs:
            if not hasattr(self, key):
                setattr(self, key, kwargs[key])
            else:
                try:
                    setattr(self, key, kwargs[key])
                except:
                    traceback.print_exc()
                    import sys
                    sys.exit(-1)

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, n):
        self._name = n

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

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self.uuidAction