import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr

from .helpers import get_miniserver_type

_LOGGER = logging.getLogger(__name__)
# ``dr.format_mac`` output: six lower-case hex pairs separated by colons.
_MAC_RE = re.compile(r"([0-9a-f]{2}:){5}[0-9a-f]{2}")
DOMAIN = "loxone"
NEW_GROUP = "groups"
NEW_LIGHT = "lights"
NEW_SCENE = "scenes"
NEW_SENSOR = "sensors"
NEW_COVERS = "covers"


@callback
def get_miniserver_from_hass(hass, config_entry):
    """Return the Miniserver for this specific config entry."""
    return hass.data[DOMAIN][config_entry.entry_id].miniserver


@dataclass
class ConfigDataClass:
    json: Optional[Dict[str, Any]] = None

    def get(self, key, default=None):
        if self.json is not None:
            return self.json.get(key, default)
        return default

    def __contains__(self, key):
        if self.json is not None:
            return key in self.json
        return False

    def __getitem__(self, key):
        if self.json is not None:
            return self.json[key]
        raise KeyError(key)


class MiniServer:
    def __init__(self, hass, lox_config, config_entry, configuration_url: str | None = None):
        self.hass = hass
        self.lox_config: ConfigDataClass = ConfigDataClass(lox_config)
        self.config_entry = config_entry
        # Where the Miniserver's web interface lives, e.g. ``http://192.168.1.50``.
        # Built by the caller from the connection, which has already
        # normalised scheme, default ports and Cloud DNS paths.
        self.configuration_url = configuration_url
        self.listeners = []

    @property
    def serial(self):
        return self.lox_config.get("msInfo", {}).get("serialNr", None)

    @property
    def mac_address(self) -> str | None:
        """
        Return the MAC address in the device registry's format, or ``None``.

        A Miniserver's serial number is its MAC address (``504F94AABBCC``
        -> ``50:4f:94:aa:bb:cc``). ``None`` if the serial is something else.
        """
        serial = self.serial
        if not serial:
            return None
        mac = dr.format_mac(str(serial))
        return mac if _MAC_RE.fullmatch(mac) else None

    @property
    def miniserver_type(self):
        return self.lox_config.get("msInfo", {}).get("miniserverType", None)

    @property
    def name(self):
        return self.lox_config.get("msInfo", {}).get("msName", None)

    @property
    def software_version(self):
        return ".".join([str(x) for x in self.lox_config.get("softwareVersion", "")])

    @property
    def miniserver_id(self) -> str:
        """Return the unique identifier of the Miniserver."""
        return self.config_entry.unique_id

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
    def async_update_device_registry(self) -> None:
        """
        Create the Miniserver's device or bring it up to date.

        Called on every setup, so the firmware version and the other details
        follow the Miniserver instead of staying at whatever the device was
        first created with.
        """
        identifier = self.serial or self.miniserver_id
        if not identifier:
            _LOGGER.debug("Miniserver has neither serial number nor unique id; no device registered")
            return

        # Only what is known: passing ``None`` would clear a value the
        # device already has, leaving the argument out keeps it.
        details: dict[str, Any] = {}
        if self.serial:
            details["serial_number"] = self.serial
        if self.software_version:
            details["sw_version"] = self.software_version
        if (mac := self.mac_address) is not None:
            details["connections"] = {(dr.CONNECTION_NETWORK_MAC, mac)}
        if self.configuration_url:
            details["configuration_url"] = self.configuration_url

        device_registry = dr.async_get(self.hass)
        device = device_registry.async_get_or_create(
            config_entry_id=self.config_entry.entry_id,
            identifiers={(DOMAIN, identifier)},
            name=self.name,
            manufacturer="Loxone",
            model=get_miniserver_type(self.miniserver_type),
            **details,
        )

        # Earlier versions registered the host/IP as the "MAC" connection.
        # ``async_get_or_create`` only ever adds connections, so drop those
        # leftovers explicitly - anything of type "mac" that is not a MAC.
        bogus = {
            connection
            for connection in device.connections
            if connection[0] == dr.CONNECTION_NETWORK_MAC and not _MAC_RE.fullmatch(connection[1])
        }
        if bogus:
            device_registry.async_update_device(device.id, new_connections=device.connections - bogus)
