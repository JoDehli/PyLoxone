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


_UNAVAILABLE = "Unavailable"


def _miniserver_info(miniserver) -> dict[str, Any]:
    ms_info = miniserver.lox_config.json["msInfo"]
    return {
        "Loxone Miniserver Serial": miniserver.serial,
        "Project Name": ms_info["projectName"],
        "Local Url": ms_info["localUrl"],
        "Remote Url": ms_info["remoteUrl"],
        "Loxone Software Version": miniserver.software_version,
    }


async def system_health_info(hass: HomeAssistant) -> dict[str, Any]:
    """Get info for the info page.

    One Miniserver: the rows as before. Several: every row once per
    Miniserver, labelled with the entry title (only the first one was
    shown before).
    """
    loaded = [
        coordinator
        for coordinator in hass.data.get(DOMAIN, {}).values()
        if getattr(coordinator, "miniserver", None) is not None
    ]
    if not loaded:
        return {
            "Loxone Miniserver Serial": _UNAVAILABLE,
            "Project Name": _UNAVAILABLE,
            "Local Url": _UNAVAILABLE,
            "Remote Url": _UNAVAILABLE,
            "Loxone Software Version": _UNAVAILABLE,
        }
    if len(loaded) == 1:
        return _miniserver_info(loaded[0].miniserver)

    info: dict[str, Any] = {}
    for coordinator in loaded:
        title = coordinator.config_entry.title
        for key, value in _miniserver_info(coordinator.miniserver).items():
            info[f"{key} ({title})"] = value
    return info
