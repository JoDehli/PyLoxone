"""Diagnostics support for Pyloxone."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    # The structure file of *this* entry: with several Miniservers the
    # first loaded one used to be returned for every entry.
    coordinator = hass.data.get(DOMAIN, {}).get(config_entry.entry_id)
    miniserver = getattr(coordinator, "miniserver", None)
    if miniserver is None:
        return {"error": "Config entry is not loaded"}
    return {
        "LoxAPP3.json": miniserver.lox_config.json,
    }
