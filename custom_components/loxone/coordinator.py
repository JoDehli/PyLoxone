import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (CONF_HOST, CONF_PASSWORD, CONF_PORT,
                                 CONF_USERNAME)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL
from .miniserver import MiniServer
from pyloxone_api.connection import LoxoneConnection, LoxoneException

_LOGGER = logging.getLogger(__name__)


class _ConfigEntryTokenStore:
    """Persist the Loxone token in the ConfigEntry (``TokenStore`` protocol).

    ``load()`` hands the library the stored dict (it checks the binding
    itself and ignores a token that does not match). ``save()`` is called
    after every login and refresh with the new token, and with ``None``
    when the token is reset.

    Errors are logged, never raised: a persistence failure must not break
    the live websocket path.
    """

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = config_entry

    def load(self) -> dict | None:
        data = self._entry.data
        if not data.get("token"):
            return None
        return dict(data)

    def save(self, token: dict | None) -> None:
        try:
            if token is None:
                new_data = {
                    **self._entry.data,
                    "token": "",
                    "hash_alg": "",
                    "valid_until": "",
                }
                new_data.pop("binding", None)
                new_data.pop("unsecure_password", None)
            else:
                # token, valid_until, hash_alg, unsecure_password, binding
                new_data = {**self._entry.data, **token}
            # ``async_update_entry`` is the supported way to mutate a
            # ConfigEntry's data from a coordinator.
            self._hass.config_entries.async_update_entry(
                self._entry, data=new_data
            )
            _LOGGER.info(
                "Persisted Loxone token for config entry %s (valid until %s)",
                self._entry.entry_id,
                "reset" if token is None else token.get("valid_until", "unknown"),
            )
        except Exception as e:
            _LOGGER.warning(
                "Failed to persist Loxone token: %s", e, exc_info=True
            )


def _collect_control_uuids(structure_file: dict) -> frozenset[str]:
    """Collect the UUIDs of all controls and subcontrols (``uuidAction``)."""
    uuids: set[str] = set()
    for key, control in (structure_file.get("controls") or {}).items():
        uuids.add(key)
        if not isinstance(control, dict):
            continue
        if control.get("uuidAction"):
            uuids.add(control["uuidAction"])
        for sub_key, sub in (control.get("subControls") or {}).items():
            uuids.add(sub_key)
            if isinstance(sub, dict) and sub.get("uuidAction"):
                uuids.add(sub["uuidAction"])
    return frozenset(uuids)


class LoxoneCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the Loxone Miniserver."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            logger=_LOGGER,
            config_entry=config_entry,
            name="PyLoxone Coordinator",
            update_method=None,  # Not polling!
        )
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
        # Control and subcontrol UUIDs from the structure file; filled
        # by ``async_config_entry_first_refresh``. See ``owns_uuid``.
        self._control_uuids: frozenset[str] = frozenset()
        # Supervisor task running ``LoxoneConnection.run()``. Stored
        # here (instead of a local in ``start_event``) so
        # ``async_unload_entry`` can cancel it — this aborts the
        # backoff sleep between retries, which ``api.close()`` alone
        # would not interrupt.
        self._listening_task: asyncio.Task | None = None
        # False while the websocket connection is down. Entity
        # availability consults this (see ``LoxoneEntity.available``);
        # it is flipped by the ``run()`` supervisor's on_state
        # callback in ``__init__.py``.
        self.connection_available: bool = True

    async def async_config_entry_first_refresh(self) -> None:
        _LOGGER.debug("async_config_entry_first_refresh")
        if self.api and self.api.connection:
            await self.api.close()
            self.api.connection = None

        self.api = LoxoneConnection(
            host=self._host,
            port=self._port,
            username=self._username,
            password=self._password,
            verify_ssl=self._verify_ssl,
            # Off-load the (potentially multi-MB) ``LoxAPP3.json`` parse
            # to HA's default executor — keeps the event loop responsive
            # while ``open()`` is bootstrapping.
            executor=self.hass.async_add_executor_job,
            # The library loads the stored token (if it matches this
            # connection) and saves every new token through the store.
            token_store=_ConfigEntryTokenStore(self.hass, self.config_entry),
        )
        try:
            session = async_get_clientsession(self.hass)
            # Bootstrap only: the websocket is opened by ``run()`` once
            # the platforms are set up. Opened here, it would sit
            # unauthenticated during platform setup and the Miniserver
            # would close it (issue #527).
            await self.api.open(session, connect_websocket=False)
        except LoxoneException as e:
            _LOGGER.error("Could not connect to Loxone Miniserver")
            raise e
        except Exception as e:
            _LOGGER.error("Could not connect to Loxone Miniserver")
            raise e

        self.miniserver = MiniServer(
            self.hass,
            self.api.structure_file,
            self.config_entry,
            configuration_url=self._configuration_url,
        )
        self._control_uuids = _collect_control_uuids(self.api.structure_file)

        return None

    @property
    def _configuration_url(self) -> str:
        """The Miniserver's web interface, from the connection's normalised URL."""
        return f"{self.api.scheme}://{self.api.url}"

    def refresh_miniserver(self) -> bool:
        """Hand the Miniserver the structure file of the latest bootstrap.

        ``LoxoneConnection.run`` re-runs ``open()`` on every reconnect and
        reads the structure file (and firmware version) again. Returns
        ``True`` if there was a newer one than the Miniserver already has.
        """
        structure_file = self.api.structure_file
        if (
            self.miniserver is None
            or not structure_file
            or structure_file is self.miniserver.lox_config.json
        ):
            return False
        self.miniserver.lox_config.json = structure_file
        self.miniserver.configuration_url = self._configuration_url
        return True

    def owns_uuid(self, uuid: str) -> bool:
        """Return True if ``uuid`` is a control or subcontrol of this Miniserver.

        Used to route commands when more than one Miniserver is set up:
        services and the send events only carry the control UUID.
        """
        return uuid in self._control_uuids

    async def _async_update_data(self) -> None:
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        print("_async_update_data")
        return None

    async def async_cleanup(self, kill_token: bool = False) -> None:
        """Clean up resources.

        ``kill_token`` defaults to ``False``: an unload (reload, HA
        restart) must keep the token valid so the value persisted by
        the token store saved survives. Only removing the config entry
        for good invalidates it on the Miniserver (see
        ``async_remove_entry`` in ``__init__.py``).
        """
        if hasattr(self, "listeners"):
            # Clean up all event listeners. One bad unsubscribe must
            # not prevent the rest (or api.close() below) from running.
            for listener in self.listeners:
                if listener is not None:
                    try:
                        listener()
                    except Exception as err:  # noqa: BLE001
                        _LOGGER.warning(
                            "Failed to unsubscribe Loxone listener %r: %s",
                            listener,
                            err,
                            exc_info=True,
                        )
            self.listeners = []

        # Close API connection.
        if hasattr(self, "api") and self.api is not None:
            if kill_token:
                # ``kill_token`` invalidates the JWT on the Miniserver
                # so it cannot be reused. Only wanted when the entry is
                # removed for good — otherwise the just-persisted token
                # would be dead on the next start and every restart
                # would have to fall back to username/password auth.
                try:
                    await self.api.kill_token()
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug(
                        "kill_token during cleanup failed: %s", err, exc_info=True
                    )
            try:
                await self.api.close()
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "api.close during cleanup failed: %s", err, exc_info=True
                )
