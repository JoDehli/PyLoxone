import logging
import traceback

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.config import get_default_config_dir


from pyloxone_api import LoxAPI

from .const import (
    ATTR_CODE,
    ATTR_UUID,
    ATTR_VALUE,
    DEFAULT,
    EVENT,
    SECUREDSENDDOMAIN,
    SENDDOMAIN,
    DOMAIN
)

from .helpers import get_miniserver_type

_LOGGER = logging.getLogger(__name__)
CONNECTION_NETWORK_MAC = "mac"

NEW_GROUP = "groups"
NEW_LIGHT = "lights"
NEW_SCENE = "scenes"
NEW_SENSOR = "sensors"
NEW_COVERS = "covers"


@callback
def get_miniserver_from_config_entry(hass, config_entry):
    """Return Miniserver with a matching bridge id."""
    return hass.data[DOMAIN][config_entry.unique_id]


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
        self.api = None
        self.callback = None
        self.entities = {}
        self.listeners = []

    @callback
    def async_signal_new_device(self, device_type) -> str:
        """Gateway specific event to signal new device."""
        new_device = {
            NEW_GROUP: f"loxone_new_group_{self.miniserverid}",
            NEW_LIGHT: f"loxone_new_light_{self.miniserverid}",
            NEW_SCENE: f"loxone_new_scene_{self.miniserverid}",
            NEW_SENSOR: f"loxone_new_sensor_{self.miniserverid}",
            NEW_COVERS: f"loxone_new_cover_{self.miniserverid}",
        }
        return new_device[device_type]

    @callback
    async def async_loxone_callback(self, message) -> None:
        """Handle event of new device creation in deCONZ."""
        self.hass.async_fire(EVENT, message)

    @property
    def serial(self):
        try:
            return self.api.json["msInfo"]["serialNr"]
        except:
            return None

    @property
    def name(self):
        try:
            return self.api.json["msInfo"]["msName"]
        except:
            return None

    @property
    def software_version(self):
        try:
            return ".".join([str(x) for x in self.api.json["softwareVersion"]])
        except:
            return None

    @property
    def miniserver_type(self):
        try:
            return self.api.json["msInfo"]["miniserverType"]
        except:
            return None

    @callback
    async def shutdown(self, event) -> None:
        await self.api.stop()

    async def async_setup(self) -> bool:
        try:
            self.api = LoxAPI(
                host=self.config_entry.options[CONF_HOST],
                port=self.config_entry.options[CONF_PORT],
                user=self.config_entry.options[CONF_USERNAME],
                password=self.config_entry.options[CONF_PASSWORD],
            )
            request_code = await self.api.getJson()

            if request_code == 200 or request_code == "200":

                self.api.config_dir=get_default_config_dir()

                res = await self.api.async_init()
                if not res or res == -1:
                    _LOGGER.error("Error connecting to loxone miniserver #1")
                    return False

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
        return True

    async def async_set_callback(self, message_callback):
        self.api.message_call_back = message_callback

    async def start_loxone(self, event):
        await self.api.start()

    async def stop_loxone(self, event):
        _ = await self.api.stop()
        _LOGGER.debug(_)

    async def listen_loxone_send(self, event):
        """Listen for change Events from Loxone Components"""
        try:
            if event.event_type == SENDDOMAIN and isinstance(event.data, dict):
                value = event.data.get(ATTR_VALUE, DEFAULT)
                device_uuid = event.data.get(ATTR_UUID, DEFAULT)
                await self.api.send_websocket_command(device_uuid, value)

            elif event.event_type == SECUREDSENDDOMAIN and isinstance(event.data, dict):
                value = event.data.get(ATTR_VALUE, DEFAULT)
                device_uuid = event.data.get(ATTR_UUID, DEFAULT)
                code = event.data.get(ATTR_CODE, DEFAULT)
                await self.api.send_secured__websocket_command(device_uuid, value, code)

        except ValueError:
            traceback.print_exc()

    async def handle_websocket_command(self, call):
        """Handle websocket command services."""
        value = call.data.get(ATTR_VALUE, DEFAULT)
        device_uuid = call.data.get(ATTR_UUID, DEFAULT)
        await self.api.send_websocket_command(device_uuid, value)

    async def async_update_device_registry(self) -> None:
        device_registry = await self.hass.helpers.device_registry.async_get_registry()

        # Host device
        device_registry.async_get_or_create(
            config_entry_id=self.config_entry.entry_id,
            connections={
                (CONNECTION_NETWORK_MAC, self.config_entry.options[CONF_HOST])
            },
        )

        # Miniserver service
        device_registry.async_get_or_create(
            config_entry_id=self.config_entry.entry_id,
            connections={},
            identifiers={(DOMAIN, self.serial)},
            name=self.name,
            manufacturer="Loxone",
            sw_version=self.software_version,
            model=get_miniserver_type(self.miniserver_type),
        )

    @property
    def host(self) -> str:
        """Return the host of the miniserver."""
        return self.config_entry.data[CONF_HOST]

    @property
    def miniserverid(self) -> str:
        """Return the unique identifier of the Miniserver."""
        return self.config_entry.unique_id
