import asyncio
import logging
import traceback

from homeassistant.const import (CONF_HOST, CONF_PASSWORD, CONF_PORT,
                                 CONF_USERNAME)
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr

from .api import LoxApp, LoxWs
from .const import (ATTR_CODE, ATTR_UUID, ATTR_VALUE, DEFAULT, DOMAIN, EVENT,
                    SECUREDSENDDOMAIN, SENDDOMAIN)
from .helpers import get_miniserver_type

_LOGGER = logging.getLogger(__name__)
CONNECTION_NETWORK_MAC = "mac"

NEW_GROUP = "groups"
NEW_LIGHT = "lights"
NEW_SCENE = "scenes"
NEW_SENSOR = "sensors"
NEW_COVERS = "covers"


@callback
def get_miniserver_from_hass(hass):
    """Return Miniserver with a matching bridge id."""
    return hass.data[DOMAIN][list(hass.data[DOMAIN].keys())[0]]


@callback
def get_miniserver_from_config(hass, config):
    """Return first Miniserver. Only one Miniserver is allowed"""
    if len(config) == 0:
        return None
    return config[next(iter(config))]


class MiniServer:
    def __init__(self, hass, config_entry) -> None:
        self.hass = hass
        self.config_entry = config_entry
        self.lox_config = None
        self.api: LoxWs | None = None
        self.callback = None
        self.entities = {}
        self.listeners = []

    @callback
    def async_signal_new_device(self, device_type) -> str:
        """Gateway specific event to signal new device."""
        new_device = {
            NEW_GROUP: f"loxone_new_group_{self.miniserver_id}",
            NEW_LIGHT: f"loxone_new_light_{self.miniserver_id}",
            NEW_SCENE: f"loxone_new_scene_{self.miniserver_id}",
            NEW_SENSOR: f"loxone_new_sensor_{self.miniserver_id}",
            NEW_COVERS: f"loxone_new_cover_{self.miniserver_id}",
        }
        return new_device[device_type]

    @callback
    async def async_loxone_callback(self, message) -> None:
        """Handle event of new device creation in deCONZ."""
        self.hass.async_fire(EVENT, message)

    @property
    def serial(self):
        try:
            return self.lox_config.json["msInfo"]["serialNr"]
        except KeyError:
            return None

    @property
    def name(self):
        try:
            return self.lox_config.json["msInfo"]["msName"]
        except KeyError:
            return None

    @property
    def software_version(self):
        try:
            return ".".join([str(x) for x in self.lox_config.json["softwareVersion"]])
        except KeyError:
            return None

    @property
    def miniserver_type(self):
        try:
            return self.lox_config.json["msInfo"]["miniserverType"]
        except KeyError:
            return None

    @property
    def local_url(self):
        try:
            return self.lox_config.json["msInfo"]["localUrl"]
        except KeyError:
            return None

    @property
    def remote_url(self):
        try:
            return self.lox_config.json["msInfo"]["remoteUrl"]
        except KeyError:
            return None

    @property
    def project_name(self):
        try:
            return self.lox_config.json["msInfo"]["projectName"]
        except KeyError:
            return None

    @callback
    async def shutdown(self, event) -> None:
        await self.api.stop()

    async def start_ws(self):
        if "token" in self.config_entry.data:
            self.api.set_token_from_dict(self.config_entry.data)
        res = await self.api.async_init()
        if res == -500:
            return -500
        if not res or res == -1:
            _LOGGER.error("Error connecting to loxone miniserver #1")
            return False
        return True

    async def async_setup(self) -> bool:
        try:
            self.lox_config = LoxApp()
            self.lox_config.lox_user = self.config_entry.options[CONF_USERNAME]
            self.lox_config.lox_pass = self.config_entry.options[CONF_PASSWORD]
            self.lox_config.host = self.config_entry.options[CONF_HOST]
            self.lox_config.port = self.config_entry.options[CONF_PORT]

            request_code = await self.lox_config.get_json()

            if request_code == 200 or request_code == "200":
                self.api = LoxWs(
                    user=self.config_entry.options[CONF_USERNAME],
                    password=self.config_entry.options[CONF_PASSWORD],
                    host=self.config_entry.options[CONF_HOST],
                    port=self.config_entry.options[CONF_PORT],
                    loxconfig=self.lox_config.json,
                    loxone_url=self.lox_config.url,
                )
                return True
            else:
                if request_code in [401, "401"]:
                    _LOGGER.error(
                        "401 - Unauthorized: the requesting user was not authorized (invalid "
                        "username/password)- Processing an encrypted request failed"
                    )

                else:
                    _LOGGER.error(
                        f"Error connecting to loxone miniserver #2 Code ({request_code})"
                    )
                return False

        except ConnectionError:
            _LOGGER.error("Error connecting to loxone miniserver  #3")
            return False

    async def async_set_callback(self, message_callback):
        self.api.message_call_back = message_callback

    async def start_loxone(self):
        _LOGGER.debug("Calling API start")
        await self.api.start()

    async def stop_loxone(self):
        _LOGGER.debug("Calling API stop")
        _ = await self.api.stop()
        self.api = None
        _LOGGER.debug(f"Stopped api: {_}")

    async def listen_loxone_send(self, event):
        """Listen for change Events from Loxone Components"""
        try:
            if event.event_type == SENDDOMAIN and isinstance(event.data, dict):
                value = event.data.get(ATTR_VALUE, DEFAULT)
                device_uuid = event.data.get(ATTR_UUID, DEFAULT)
                if value is None:
                    value = DEFAULT
                if device_uuid is None:
                    device_uuid = DEFAULT
                await self.api.send_websocket_command(device_uuid, value)

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
                await self.api.send_secured__websocket_command(device_uuid, value, code)

        except ValueError:
            traceback.print_exc()

    async def handle_websocket_command(self, call):
        """Handle websocket command services."""
        value = call.data.get(ATTR_VALUE, DEFAULT)
        device_uuid = call.data.get(ATTR_UUID, DEFAULT)
        await self.api.send_websocket_command(device_uuid, value)

    async def async_update_device_registry(self) -> None:
        device_registry = dr.async_get(self.hass)
        # Host device
        # device_registry.async_get_or_create(
        #     config_entry_id=self.config_entry.entry_id,
        #     connections={
        #         (CONNECTION_NETWORK_MAC, self.config_entry.options[CONF_HOST])
        #     },
        # )

        # Miniserver service
        device_registry.async_get_or_create(
            config_entry_id=self.config_entry.entry_id,
            connections={
                (CONNECTION_NETWORK_MAC, self.config_entry.options[CONF_HOST])
            },
            name=self.name,
            model=get_miniserver_type(self.miniserver_type),
            identifiers={(DOMAIN, self.serial)},
            manufacturer="Loxone",
            sw_version=self.software_version,
            configuration_url="http://{host}:{port}".format(
                host=self.lox_config.host, port=self.lox_config.port
            ),
        )

    @property
    def host(self) -> str:
        """Return the host of the miniserver."""
        return self.config_entry.data[CONF_HOST]

    @property
    def miniserver_id(self) -> str:
        """Return the unique identifier of the Miniserver."""
        return self.config_entry.unique_id
