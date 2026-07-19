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
        if hasattr(v, "miniserver"):
            miniserver_serial = v.miniserver.serial
            software_version = v.miniserver.software_version
            project_name = v.miniserver.lox_config.json["msInfo"]["projectName"]
            local_url = v.miniserver.lox_config.json["msInfo"]["localUrl"]
            remote_url = v.miniserver.lox_config.json["msInfo"]["remoteUrl"]
        else:
            miniserver_serial = "Unavailable"
            software_version = "Unavailable"
            project_name = "Unavailable"
            local_url = "Unavailable"
            remote_url = "Unavailable"
        return {
            "Loxone Miniserver Serial": miniserver_serial,
            "Project Name": project_name,
            "Local Url": local_url,
            "Remote Url": remote_url,
            "Loxone Software Version": software_version,
        }
