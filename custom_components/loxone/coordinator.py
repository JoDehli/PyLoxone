import asyncio
import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (CONF_HOST, CONF_PASSWORD, CONF_PORT,
                                 CONF_USERNAME)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL
from .miniserver import MiniServer
from .pyloxone_api.connection import LoxoneConnection, LoxoneException

if TYPE_CHECKING:
    from .audio import AudioMetadataCoordinator

_LOGGER = logging.getLogger(__name__)


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
        self.audio_commands = None
        self.audio_diagnostics = None
        self.miniserver: MiniServer | None = None
        self.listeners = []
        self.audio_metadata: AudioMetadataCoordinator | None = None
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

    def _on_token_changed(self, token: dict) -> None:
        """Persist a freshly-issued token into the ConfigEntry.

        Called by :class:`LoxoneConnection` via the
        ``token_change_callback`` whenever the Miniserver issues
        a new token (initial auth or refresh). The token dict
        is merged into ``ConfigEntry.data`` so a HA restart
        can pick it up without re-prompting for credentials.

        Errors are logged at WARNING — a persistence failure
        must not break the live websocket path; the user just
        has to re-authenticate on the next restart.
        """
        try:
            new_data = {**self.config_entry.data, **token}
            # ``async_update_entry`` is the supported way to
            # mutate a ConfigEntry's data from a coordinator.
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            _LOGGER.info(
                "Persisted updated Loxone token for config entry %s "
                "(valid until %s)",
                self.config_entry.entry_id,
                token.get("valid_until", "unknown"),
            )
        except Exception as e:
            _LOGGER.warning(
                "Failed to persist updated token: %s", e, exc_info=True
            )

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
                # Off-load the (potentially multi-MB)
                # ``LoxAPP3.json`` parse to HA's default executor —
                # keeps the event loop responsive while ``open()``
                # is bootstrapping.
                executor=self.hass.async_add_executor_job,
                # ``_on_token_changed`` is async-aware and
                # merges the new token into ConfigEntry.data
                # so a HA restart can resume without a fresh
                # username/password auth.
                token_change_callback=self._on_token_changed,
            )
        else:
            self.api = LoxoneConnection(
                host=self._host,
                port=self._port,
                username=self._username,
                password=self._password,
                verify_ssl=self._verify_ssl,
                executor=self.hass.async_add_executor_job,
                token_change_callback=self._on_token_changed,
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
            self.hass, self.api.structure_file, self.config_entry
        )
        self._control_uuids = _collect_control_uuids(self.api.structure_file)

        return None

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
        ``_on_token_changed`` survives. Only removing the config entry
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

        await _async_close_audio_commands(self)

        # Optional metadata must not outlive the entry or prevent API cleanup.
        if audio_metadata := getattr(self, "audio_metadata", None):
            try:
                await audio_metadata.async_stop()
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Audioserver metadata cleanup failed (%s)", type(err).__name__)
            finally:
                self.audio_metadata = None
        if diagnostics := getattr(self, "audio_diagnostics", None):
            await diagnostics.async_close()
            self.audio_diagnostics = None
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


async def _async_close_audio_commands(coordinator: LoxoneCoordinator) -> None:
    """Close optional playback without preventing native API cleanup."""
    # Opt-in command connections must close before their token owner.
    if audio_commands := getattr(coordinator, "audio_commands", None):
        try:
            await audio_commands.async_close()
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Audioserver playback cleanup failed (%s)", type(err).__name__)
        finally:
            coordinator.audio_commands = None
