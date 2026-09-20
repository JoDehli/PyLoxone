import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (CONF_HOST, CONF_PASSWORD, CONF_PORT,
                                 CONF_USERNAME)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_HARDWARE_BATTERY_INTERVAL,
    CONF_HARDWARE_ENABLED,
    CONF_HARDWARE_FAST_POLL_INTERVAL,
    CONF_HARDWARE_INVENTORY_INTERVAL,
    CONF_HARDWARE_MAPPINGS,
    CONF_VERIFY_SSL,
    DEFAULT_HARDWARE_BATTERY_INTERVAL,
    DEFAULT_HARDWARE_ENABLED,
    DEFAULT_HARDWARE_FAST_POLL_INTERVAL,
    DEFAULT_HARDWARE_INVENTORY_INTERVAL,
    DEFAULT_VERIFY_SSL,
)
from .hardware import LoxoneHardwareApi, LoxoneHardwareCoordinator
from .hardware.entity import control_device_mapping
from .helpers import configure_hardware_control_registry
from .miniserver import MiniServer
from .pyloxone_api.connection import LoxoneConnection, LoxoneException

_LOGGER = logging.getLogger(__name__)


class LoxoneCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the Loxone Miniserver."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            logger=_LOGGER,
            name="PyLoxone Coordinator",
            update_method=None,  # Not polling!
        )
        self.config_entry = config_entry
        self._username = config_entry.options[CONF_USERNAME]
        self._password = config_entry.options[CONF_PASSWORD]
        self._host = config_entry.options[CONF_HOST]
        self._port = config_entry.options[CONF_PORT]
        self._verify_ssl = config_entry.options.get(
            CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL
        )

        self.api: LoxoneConnection | None = None
        self.miniserver: MiniServer | None = None
        self.listeners = []
        self.hardware: LoxoneHardwareCoordinator | None = None

    async def async_config_entry_first_refresh(self) -> None:
        _LOGGER.debug("async_config_entry_first_refresh")
        if self.api and self.api.connection:
            await self.api.close()
            self.api.connection = None

        if "token" in self.config_entry.data:
            self.api = LoxoneConnection(
                host=self._host,
                port=self._port,
                username=self._username,
                password=self._password,
                token=self.config_entry.data,
                verify_ssl=self._verify_ssl,
            )
        else:
            self.api = LoxoneConnection(
                host=self._host,
                port=self._port,
                username=self._username,
                password=self._password,
                verify_ssl=self._verify_ssl,
            )
        try:
            session = async_get_clientsession(self.hass)
            await self.api.open(session)
        except LoxoneException as e:
            _LOGGER.error("Could not connect to Loxone Miniserver")
            raise e
        except Exception as e:
            _LOGGER.error("Could not connect to Loxone Miniserver")
            raise e

        self.miniserver = MiniServer(
            self.hass, self.api.structure_file, self.config_entry
        )

        configure_hardware_control_registry({})
        if self.config_entry.options.get(
            CONF_HARDWARE_ENABLED, DEFAULT_HARDWARE_ENABLED
        ):
            try:
                hardware_api = LoxoneHardwareApi(
                    session=session,
                    host=self._host,
                    port=self._port,
                    username=self._username,
                    password=self._password,
                    verify_ssl=self._verify_ssl,
                    structure=self.api.structure_file,
                    manual_mappings=self.config_entry.data.get(
                        CONF_HARDWARE_MAPPINGS, {}
                    ),
                )
                hardware_data = await hardware_api.async_discover()
                self.hardware = LoxoneHardwareCoordinator(
                    self.hass,
                    self.config_entry,
                    hardware_api,
                    hardware_data,
                    fast_interval=int(
                        self.config_entry.options.get(
                            CONF_HARDWARE_FAST_POLL_INTERVAL,
                            DEFAULT_HARDWARE_FAST_POLL_INTERVAL,
                        )
                    ),
                    inventory_interval=int(
                        self.config_entry.options.get(
                            CONF_HARDWARE_INVENTORY_INTERVAL,
                            DEFAULT_HARDWARE_INVENTORY_INTERVAL,
                        )
                    ),
                    battery_interval=int(
                        self.config_entry.options.get(
                            CONF_HARDWARE_BATTERY_INTERVAL,
                            DEFAULT_HARDWARE_BATTERY_INTERVAL,
                        )
                    )
                    * 60,
                )
                self.hardware.push_connected = lambda: bool(
                    self.api and self.api.is_connected
                )
                await self.hardware.async_config_entry_first_refresh()
                configure_hardware_control_registry(
                    control_device_mapping(self.hardware.data)
                )
            except Exception as err:
                # Hardware inventory is additive. A firmware or permission that
                # does not expose these endpoints must not break normal PyLoxone.
                _LOGGER.warning("Physical hardware inventory unavailable: %s", err)
                self.hardware = None

        return None

    async def _async_update_data(self) -> None:
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        print("_async_update_data")
        return None

    async def async_cleanup(self):
        """Clean up resources."""
        if hasattr(self, "listeners"):
            # Clean up all event listeners
            for listener in self.listeners:
                if listener is not None:
                    listener()
            self.listeners = []

        if self.hardware is not None:
            await self.hardware.async_shutdown()

        # Close API connection
        if hasattr(self, "api"):
            await self.api.close()
