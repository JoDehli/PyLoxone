"""Provide info to system health."""

from __future__ import annotations

from typing import Any

from homeassistant.components import system_health
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN


@callback
def async_register(
    hass: HomeAssistant, register: system_health.SystemHealthRegistration
) -> None:
    """Register system health callbacks."""
    register.async_register_info(system_health_info)


async def system_health_info(hass: HomeAssistant) -> dict[str, Any]:
    """Get info for the info page."""
    for k, v in hass.data[DOMAIN].items():
        return {
            "Loxone Miniserver Serial": v.serial,
            "Project Name": v.project_name,
            "Local Url": v.local_url,
            "Loxone Software Version": v.software_version,
        }
