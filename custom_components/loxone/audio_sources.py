"""Compatibility imports with an isolated HA source-operation environment."""
from __future__ import annotations

from functools import wraps
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util
from pyloxone_audio import sources

if TYPE_CHECKING:
    from datetime import datetime
    from pyloxone_audio.native import AudioZoneMetadata

# Immutable configuration, not mutation of the portable module or its default.
# Resolve HA's current UTC provider at the point of observation (also in tests).
class _HAEnvironment(sources.SourceEnvironment):
    async def async_observed_change(self, *args: Any, **kwargs: Any) -> AudioZoneMetadata | None:
        # Keep the historical host observation hook for unchanged test callers.
        # The concrete algorithm and all eligibility rules remain package-owned.
        return await _async_observed_change(*args, clock=self.clock, **kwargs)


def _ha_clock() -> datetime:
    return dt_util.utcnow()


environment = _HAEnvironment(clock=_ha_clock)
_async_observed_change = sources.async_observed_change


def _configured(method: Any) -> Any:
    @wraps(method)
    async def configured(*args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("environment", environment)
        return await method(*args, **kwargs)
    return configured


async_select_catalogue = _configured(sources.async_select_catalogue)
async_select_favourite = _configured(sources.async_select_favourite)
async_select_radio_station = _configured(sources.async_select_radio_station)
async_seek_track = _configured(sources.async_seek_track)
async_native_catalogue_noop = _configured(sources.async_native_catalogue_noop)


def __getattr__(name: str) -> Any:
    """Preserve pure compatibility imports without a second native algorithm."""
    return getattr(sources, name)
