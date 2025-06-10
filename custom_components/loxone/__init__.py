"""
Component to create an interface to the Loxone Miniserver.

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""

import asyncio
import logging
import re
import sys
import traceback
from functools import cached_property

<import homeassistant
import homeassistant.components.group as group
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (CONF_HOST, CONF_PASSWORD, CONF_PORT,
                                 CONF_USERNAME, EVENT_COMPONENT_LOADED,
                                 EVENT_HOMEASSISTANT_START,
                                 EVENT_HOMEASSISTANT_STOP)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.entity import Entity

from .const import (ATTR_AREA_CREATE, ATTR_CODE, ATTR_COMMAND, ATTR_DEVICE,
                    ATTR_UUID, ATTR_VALUE,
                    CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN, CONF_SCENE_GEN,
                    CONF_SCENE_GEN_DELAY, DEFAULT, DEFAULT_DELAY_SCENE,
                    DEFAULT_PORT, DOMAIN, DOMAIN_DEVICES, ERROR_VALUE, EVENT,
                    LOXONE_PLATFORMS, SECUREDSENDDOMAIN, SENDDOMAIN, cfmt)
from .helpers import get_miniserver_type
from .miniserver import MiniServer, get_miniserver_from_hass
from .pyloxone_api.connection import LoxoneConnection
from .pyloxone_api.exceptions import LoxoneException, LoxoneTokenError

# from .miniserver import (MiniServer, get_miniserver_from_config,
#                          get_miniserver_from_hass)

# from .api import LoxApp, LoxWs

REQUIREMENTS = ["websockets", "pycryptodome", "numpy"]

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_USERNAME): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
                vol.Required(CONF_HOST): cv.string,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
                vol.Optional(CONF_SCENE_GEN, default=True): cv.boolean,
                vol.Optional(
                    CONF_SCENE_GEN_DELAY, default=DEFAULT_DELAY_SCENE
                ): cv.positive_int,
                vol.Required(CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN, default=False): bool,
            }
        ),
    },
    extra=vol.ALLOW_EXTRA,
)

_UNDEF: dict = {}


# TODO: Implement a complete restart of the loxone component without restart HomeAssistant
# TODO: Unload device
# TODO: get version and check for updates https://update.loxone.com/updatecheck.xml?serial=xxxxxxxxx


async def async_unload_entry(hass, config_entry):
    """Restart of Home Assistant needed."""
    return False


async def async_setup(hass, config):
    """setup loxone"""
    if DOMAIN in config:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": "import"}, data=config[DOMAIN]
            )
        )

    # async def handle_reload(call):
    #     """Handle the service call to reload the integration."""
    #     _LOGGER.info("Reloading custom integration")
    #     await async_setup(hass, config)
    #
    # hass.services.async_register(DOMAIN, "reload", handle_reload)
    return True


async def async_migrate_entry(hass, config_entry):
    # _LOGGER.debug("Migrating from version %s", config_entry.version)
    if config_entry.version == 1:
        new = {**config_entry.options, CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN: True}
        config_entry.options = {**new}
        config_entry.version = 2
        _LOGGER.info("Migration to version %s successful", 2)

    if config_entry.version == 2:
        new = {**config_entry.options, CONF_SCENE_GEN_DELAY: DEFAULT_DELAY_SCENE}
        config_entry.options = {**new}
        config_entry.version = 3
        _LOGGER.info("Migration to version %s successful", 3)
    return True


async def async_set_options(hass, config_entry):
    options_in = {**config_entry.options}
    options = {
        CONF_HOST: options_in.pop(CONF_HOST, ""),
        CONF_PORT: options_in.pop(CONF_PORT, DEFAULT_PORT),
        CONF_USERNAME: options_in.pop(CONF_USERNAME, ""),
        CONF_PASSWORD: options_in.pop(CONF_PASSWORD, ""),
        CONF_SCENE_GEN: options_in.pop(CONF_SCENE_GEN, ""),
        CONF_SCENE_GEN_DELAY: options_in.pop(CONF_SCENE_GEN_DELAY, DEFAULT_DELAY_SCENE),
        CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN: options_in.pop(
            CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN, ""
        ),
    }
    hass.config_entries.async_update_entry(
        config_entry, data=config_entry.data, options=options
    )


async def async_config_entry_updated(hass, entry) -> None:
    """Handle signals of config entry being updated.

    This is a static method because a class method (bound method), can not be used with weak references.
    Causes for this is either discovery updating host address or config entry options changing.
    """
    pass


async def create_group_for_loxone_entities(hass, entities, name, object_id):
    try:
        await group.Group.async_create_group(
            hass,
            name,
            created_by_service=False,
            entity_ids=entities,
            icon=None,
            mode=None,
            object_id=object_id,
            order=None,
        )
    except HomeAssistantError as err:
        await group.Group.async_create_group(
            hass,
            name,
            created_by_service=True,
            entity_ids=entities,
            icon=None,
            mode=None,
            object_id=object_id,
            order=None,
        )
        _LOGGER.error("Can't create group '%s' with error: %s", name, err)
    except Exception as e:
        _LOGGER.error(
            "Can't create group '%s'. Try to make at least one group manually. ("
            "https://www.home-assistant.io/integrations/group/)",
            e,
        )


async def async_setup_entry(hass, config_entry):
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    if not config_entry.options:
        await async_set_options(hass, config_entry)

    username = config_entry.options[CONF_USERNAME]
    password = config_entry.options[CONF_PASSWORD]
    host = config_entry.options[CONF_HOST]
    port = config_entry.options[CONF_PORT]

    if "token" in config_entry.data:
        api = LoxoneConnection(
            host=host,
            port=port,
            username=username,
            password=password,
            token=config_entry.data,
        )
    else:
        api = LoxoneConnection(
            host=host, port=port, username=username, password=password
        )

    try:
        from homeassistant.helpers.aiohttp_client import \
            async_get_clientsession

        session = async_get_clientsession(hass)
        open_connection = await api.open(session)
    except LoxoneException:
        _LOGGER.error("Could not connect to Loxone Miniserver")
        return False

    miniserver = MiniServer(hass, api.structure_file, config_entry)
    hass.data[DOMAIN][api.miniserver_serial] = miniserver

    setup_tasks = []
    await hass.config_entries.async_forward_entry_setups(config_entry, LOXONE_PLATFORMS)
    for platform in LOXONE_PLATFORMS:
        setup_tasks.append(
            hass.async_create_task(
                async_load_platform(hass, platform, DOMAIN, {}, config_entry)
            )
        )

    if setup_tasks:
        await asyncio.wait(setup_tasks)

    def handle_task_result(task: asyncio.Task) -> None:
        try:
            task.result()
        except LoxoneTokenError as e:
            _LOGGER.debug(
                "Token is not valid anymore. Please restart Homeassistant to aquire new token."
            )
        except asyncio.exceptions.CancelledError as e:
            _LOGGER.error(e)
        except Exception as e:
            raise e

    async def message_callback(message):
        """Fire message on HomeAssistant Bus."""
        _LOGGER.debug(f"{message}")
        hass.bus.async_fire(EVENT, message)

    async def handle_websocket_command(call):
        """Handle websocket command services."""
        value = call.data.get(ATTR_VALUE, DEFAULT)
        if call.data.get(ATTR_DEVICE) is None:
            entity_uuid = call.data.get(ATTR_UUID, DEFAULT)
        else:
            entity_registry = er.async_get(hass)
            entity_id = call.data.get(ATTR_DEVICE)
            entity = entity_registry.async_get(entity_id)
            entity_uuid = entity.unique_id
        await api.send_websocket_command(entity_uuid, value)

    async def handle_secured_websocket_command(call):
        """Handle websocket command services."""
        value = call.data.get(ATTR_VALUE, DEFAULT)
        code = call.data.get(ATTR_CODE, DEFAULT)
        if call.data.get(ATTR_DEVICE) is None:
            entity_uuid = call.data.get(ATTR_UUID, DEFAULT)
        else:
            entity_registry = er.async_get(hass)
            entity_id = call.data.get(ATTR_DEVICE)
            entity = entity_registry.async_get(entity_id)
            entity_uuid = entity.unique_id
        await api.send_secured__websocket_command(entity_uuid, value, code)

    async def loxone_discovered(event):
        miniserver = get_miniserver_from_hass(hass)

    async def start_event(_):
        try:
            # noinspection PyTypeChecker
            listening_task = asyncio.create_task(
                api.start_listening(callback=message_callback)
            )
            listening_task.add_done_callback(handle_task_result)

        except Exception as e:
            raise e

    async def stop_event(_):
        token = api.get_token_dict()
        hass.config_entries.async_update_entry(
            config_entry,
            data={
                "token": token["token"],
                "hash_alg": token["hash_alg"],
                "valid_until": token["valid_until"],
            },
        )
        await api.close()

    async def loxone_send(event):
        """Listen for change Events from Loxone Components"""
        try:
            if event.event_type == SENDDOMAIN and isinstance(event.data, dict):
                value = event.data.get(ATTR_VALUE, DEFAULT)
                device_uuid = event.data.get(ATTR_UUID, DEFAULT)
                if value is None:
                    value = DEFAULT
                if device_uuid is None:
                    device_uuid = DEFAULT
                await api.send_websocket_command(device_uuid, value)

            elif event.event_type == SECUREDSENDDOMAIN and isinstance(event.data, dict):
                value = event.data.get(ATTR_VALUE, DEFAULT)
                device_uuid = event.data.get(ATTR_UUID, DEFAULT)
                code = event.data.get(ATTR_CODE, DEFAULT)
                if code is None:
                    code = DEFAULT
                if value is None:
                    value = DEFAULT
                if device_uuid is None:
                    device_uuid = DEFAULT
                await api.send_secured__websocket_command(device_uuid, value, code)

        except Exception as e:
            _LOGGER.error(e)

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, start_event)
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop_event)
    hass.bus.async_listen_once(EVENT_COMPONENT_LOADED, loxone_discovered)

    hass.bus.async_listen(SENDDOMAIN, loxone_send)
    hass.bus.async_listen(SECUREDSENDDOMAIN, loxone_send)

    hass.services.async_register(
        DOMAIN, "event_websocket_command", handle_websocket_command
    )

    hass.services.async_register(
        DOMAIN, "event_secured_websocket_command", handle_secured_websocket_command
    )

    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Remove a config entry from a device."""
    return True


class LoxoneEntity(Entity):
    """
    @DynamicAttrs
    """

    def __init__(self, **kwargs):
        for key in kwargs:
            if not hasattr(self, key):
                if key == "name":
                    self._attr_name = kwargs[key]
                else:
                    setattr(self, key, kwargs[key])
            else:
                try:
                    setattr(self, key, kwargs[key])
                except AttributeError:
                    _LOGGER.error(f"Could set {key} for {self.name}")
                except (Exception,):
                    traceback.print_exc()
                    sys.exit(-1)

        self.listener = None

    async def async_added_to_hass(self):
        """Subscribe to device events."""
        self.listener = self.hass.bus.async_listen(EVENT, self.event_handler)

    async def async_will_remove_from_hass(self):
        """Disconnect callbacks."""
        self.listener = None

    async def event_handler(self, e):
        pass

    @cached_property
    def name(self):
        return self._attr_name

    # @name.setter
    # def name(self, n):
    #     self._attr_name = n

    @staticmethod
    def _clean_unit(lox_format):
        search = re.search(cfmt, lox_format, flags=re.X)
        if search:
            unit = lox_format.replace(search.group(0).strip(), "").strip()
            if unit == "%%":
                unit = unit.replace("%%", "%")
            return unit
        else:
            return lox_format

    @staticmethod
    def _get_format(lox_format):
        search = re.search(cfmt, lox_format, flags=re.X)
        if search:
            return search.group(0).strip()
        return None

    @cached_property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self.uuidAction
