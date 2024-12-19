"""Diagnostics support for AccuWeather."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .const import DOMAIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: AccuWeatherConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    for k, v in hass.data[DOMAIN].items():
        return {
            "LoxAPP3.json": v.lox_config.json,
        }
