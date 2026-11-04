"""Entry-owned, persistent permission-0 tokens for native Intercom sessions."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import logging
import math
from uuid import UUID, uuid4

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from ..pyloxone_api.exceptions import IntercomTokenError
from ..const import CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL

_LOGGER = logging.getLogger(__name__)
AUTH_DATA = "intercom_auth"
LOXONE_EPOCH_TIMESTAMP = datetime(2009, 1, 1, tzinfo=UTC).timestamp()
RENEW_BEFORE = 60
RETRY_DELAY = 60
MAX_REFRESH_DELAY = 86400


def _valid_expiry(value) -> bool:
    """Reject corrupt metadata before arithmetic or event-loop scheduling."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value) and 0 < value <= 253402300799 - LOXONE_EPOCH_TIMESTAMP
    except OverflowError:
        return False


async def async_remove_intercom_token(hass, entry) -> None:
    """Best-effort revocation after HA has already unloaded the config entry."""
    stored = entry.data.get(AUTH_DATA)
    if not isinstance(stored, dict) or not stored.get("token") or stored.get("permission") != 0:
        return
    if stored.get("username") != entry.options.get(CONF_USERNAME):
        return
    # A removal callback runs after unload, so the original websocket is gone.
    # Reuse the persisted app authentication on a short-lived connection.
    from ..pyloxone_api.connection import LoxoneConnection

    api = LoxoneConnection(
        host=entry.options[CONF_HOST],
        port=entry.options[CONF_PORT],
        username=entry.options[CONF_USERNAME],
        password=entry.options[CONF_PASSWORD],
        token=entry.data,
        verify_ssl=entry.options.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
        executor=hass.async_add_executor_job,
    )
    tasks = []
    try:
        async with asyncio.timeout(20):
            await api.open(async_get_clientsession(hass), connect_websocket=False)
            listening = asyncio.create_task(api.run(), name="loxone_intercom_revoke_connection")
            ready = asyncio.create_task(api._authenticated_event.wait())
            tasks.extend((listening, ready))
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if listening.done():
                await listening
            await api.async_intercom_token(stored["client_id"], stored["token"], revoke=True)
    except Exception as error:
        _LOGGER.debug("Dedicated Intercom token revocation failed (%s); it will expire", type(error).__name__)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            async with asyncio.timeout(5):
                await api.close()
        except Exception as error:
            _LOGGER.debug("Intercom revocation connection cleanup failed (%s)", type(error).__name__)


class IntercomTokenManager:
    """Share one dedicated token per Miniserver account, never its app token."""

    def __init__(self, hass, entry, api) -> None:
        self.hass = hass
        self.entry = entry
        self.api = api
        self.username = entry.options[CONF_USERNAME]
        self._lock = asyncio.Lock()
        self._closed = False
        self._cancel_refresh = None
        self._refresh_task = None
        self._credential_task = None
        stored = entry.data.get(AUTH_DATA, {})
        if not isinstance(stored, dict) or stored.get("username") != self.username:
            stored = {}
        try:
            client_id = stored.get("client_id")
            if not isinstance(client_id, str):
                raise ValueError("Missing client UUID")
            self.client_id = str(UUID(client_id))
        except ValueError:
            self.client_id = str(uuid4())
            stored = {}
        self._token = stored.get("token", "")
        self._valid_until = stored.get("valid_until", 0)
        if (
            stored.get("permission") != 0
            or not isinstance(self._token, str)
            or self._token == entry.data.get("token")
            or not _valid_expiry(self._valid_until)
        ):
            self._token, self._valid_until = "", 0
        if self._token:
            self._schedule()

    def _remaining(self) -> float:
        return self._valid_until + LOXONE_EPOCH_TIMESTAMP - dt_util.utcnow().timestamp()

    def _persist(self) -> None:
        self.hass.config_entries.async_update_entry(
            self.entry,
            data={
                **self.entry.data,
                AUTH_DATA: {
                    "client_id": self.client_id,
                    "username": self.username,
                    "permission": 0,
                    "token": self._token,
                    "valid_until": self._valid_until,
                },
            },
        )

    @callback
    def _schedule(self, delay: float | None = None) -> None:
        if self._cancel_refresh:
            self._cancel_refresh()
        if self._closed:
            self._cancel_refresh = None
            return
        if delay is None:
            remaining = self._remaining()
            delay = max(1, min(MAX_REFRESH_DELAY, remaining - min(RENEW_BEFORE, remaining / 2)))
        self._cancel_refresh = async_call_later(self.hass, delay, self._refresh_due)

    @callback
    def _refresh_due(self, _now) -> None:
        self._cancel_refresh = None
        if not self._closed:
            self._refresh_task = self.hass.async_create_background_task(
                self._async_renew(), "loxone_intercom_token_refresh"
            )

    async def _async_renew(self) -> None:
        try:
            await self.async_credentials(renew=True)
            if self._cancel_refresh is None:
                # A timer can join a viewer's already-running cached lookup.
                # In that case the shared task did not schedule a renewal.
                self._schedule()
        except IntercomTokenError as error:
            if error.code in {401, 403, 4003}:
                _LOGGER.warning(
                    "Dedicated Intercom token was rejected; check the PyLoxone account credentials and permissions"
                )
            else:
                _LOGGER.warning("Could not renew the dedicated Intercom token; retrying in %s seconds", RETRY_DELAY)
        finally:
            self._refresh_task = None

    async def async_credentials(self, *, renew: bool = False) -> tuple[str, str]:
        """Share issuance independently of the lifetime of a camera dialog."""
        if self._closed:
            raise IntercomTokenError("Intercom token manager is closed")
        if self._credential_task is None or self._credential_task.done():
            self._credential_task = self.hass.async_create_background_task(
                self._async_credentials(renew=renew), "loxone_intercom_credentials"
            )
            # If the last viewer leaves, consume a later exception as well.
            # The manager already schedules retries for temporary failures.
            self._credential_task.add_done_callback(lambda task: None if task.cancelled() else task.exception())
        return await asyncio.shield(self._credential_task)

    async def _async_credentials(self, *, renew: bool = False) -> tuple[str, str]:
        """Issue on first use, renew before expiry, and reuse across restarts."""
        async with self._lock:
            if self._closed:
                raise IntercomTokenError("Intercom token manager is closed")
            if not renew and self._token and self._remaining() > RENEW_BEFORE:
                return self.username, self._token
            self._persist()  # Preserve the client UUID even if the first request fails.
            try:
                value = None
                if self._token and self._remaining() > 0:
                    try:
                        value = await self.api.async_intercom_token(self.client_id, self._token)
                    except IntercomTokenError as error:
                        if error.code != 401:
                            raise
                        _LOGGER.debug("Dedicated Intercom token renewal rejected (401); requesting a replacement")
                        # Revoked tokens cannot be renewed. Issue a fresh one
                        # using the existing account, without touching app auth.
                        self._token, self._valid_until = "", 0
                        self._persist()
                if value is None:
                    value = await self.api.async_intercom_token(self.client_id)
                if not isinstance(value, dict):
                    raise IntercomTokenError("Miniserver returned invalid Intercom token metadata")
                token, expiry = value.get("token"), value.get("validUntil")
                if (
                    not isinstance(token, str)
                    or token == self.entry.data.get("token")
                    or not token
                    or not _valid_expiry(expiry)
                    or expiry + LOXONE_EPOCH_TIMESTAMP <= dt_util.utcnow().timestamp()
                ):
                    raise IntercomTokenError("Miniserver returned invalid Intercom token metadata")
                if self._closed:
                    raise IntercomTokenError("Intercom token manager is closed")
                self._token, self._valid_until = token, expiry
                self._persist()
                self._schedule()
                return self.username, token
            except (IntercomTokenError, TimeoutError) as error:
                code = getattr(error, "code", None)
                if code in {401, 403, 4003}:
                    # Do not repeatedly retry a rejected password/permission
                    # in the background: that can lock the Loxone account.
                    if self._cancel_refresh:
                        self._cancel_refresh()
                        self._cancel_refresh = None
                else:
                    self._schedule(RETRY_DELAY)
                # A temporary renewal failure does not invalidate a token
                # which the device may still accept until its actual expiry.
                if not renew and self._token and self._remaining() > 0:
                    return self.username, self._token
                raise IntercomTokenError("Could not obtain a dedicated Intercom token", code) from None

    async def async_invalidate(self, rejected_token: str) -> None:
        """Discard exactly the token rejected by the device, preserving newer ones."""
        async with self._lock:
            if self._token != rejected_token or self._closed:
                return
            self._token, self._valid_until = "", 0
            if self._cancel_refresh:
                self._cancel_refresh()
                self._cancel_refresh = None
            self._persist()

    async def async_close(self) -> None:
        """Cancel renewal work on unload; retain the token for the next setup."""
        self._closed = True
        if self._cancel_refresh:
            self._cancel_refresh()
            self._cancel_refresh = None
        tasks = {
            task
            for task in (self._refresh_task, self._credential_task)
            if task is not None and task is not asyncio.current_task()
        }
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
