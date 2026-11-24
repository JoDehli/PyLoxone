"""Remote (media controller, structure file spec V17).

Details: ``favoritePad``, ``modeList`` (``{"1": {"name": "TV"}}``).
States: ``mode`` (0 = no mode = all off), ``timeout``, ``active``.
Commands: ``mode/{id}`` (not 0), ``on`` / ``off`` (power output),
``reset`` (devices of the current mode off, mode 0) and the buttons
(``play``, ``volplus``, ``dirup``, ``num{x}``, ``number/{x}``, ...).

The control is a remote entity: modes are activities, buttons go through
``remote.send_command``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

from homeassistant.components.remote import (
    ATTR_ACTIVITY,
    ATTR_DELAY_SECS,
    ATTR_NUM_REPEATS,
    DEFAULT_DELAY_SECS,
    RemoteEntity,
    RemoteEntityFeature,
)
from homeassistant.const import Platform

from . import SetupContext, register
from .base import ControlEntity, to_bool, to_int


def mode_list(details: dict) -> dict[int, str]:
    """Mode id -> name from ``details.modeList``."""
    modes = details.get("modeList") or {}
    result = {}
    if isinstance(modes, dict):
        for key, mode in modes.items():
            number = to_int(key)
            if number is not None and number != 0:
                name = mode.get("name") if isinstance(mode, dict) else None
                result[number] = str(name or f"Mode {number}")
    return result


class LoxoneRemote(ControlEntity, RemoteEntity):
    """Media controller with its modes as activities."""

    _attr_supported_features = RemoteEntityFeature.ACTIVITY
    _attr_icon = "mdi:remote-tv"

    def __init__(self, control: dict) -> None:
        super().__init__(control, watch=("mode", "active", "timeout"))
        self._modes = mode_list(self.details)
        self._attr_activity_list = list(self._modes.values())
        self._mode: int | None = None
        self._active: bool | None = None
        self._timeout: int | None = None

    def _handle_states(self, changes: dict[str, Any]) -> None:
        if "mode" in changes:
            self._mode = to_int(changes["mode"])
        if "active" in changes:
            self._active = to_bool(changes["active"])
        if "timeout" in changes:
            self._timeout = to_int(changes["timeout"])

    @property
    def is_on(self) -> bool | None:
        return None if self._mode is None else self._mode != 0

    @property
    def current_activity(self) -> str | None:
        return self._modes.get(self._mode) if self._mode else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        activity = kwargs.get(ATTR_ACTIVITY)
        mode = next((number for number, name in self._modes.items() if name == activity), None)
        self.send(f"mode/{mode}" if mode is not None else "on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        # reset: devices of the current mode off and back to mode 0.
        self.send("reset")

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        repeats = int(kwargs.get(ATTR_NUM_REPEATS) or 1)
        delay = float(kwargs.get(ATTR_DELAY_SECS, DEFAULT_DELAY_SECS))
        commands = [str(item) for item in command]
        for repeat in range(repeats):
            for index, item in enumerate(commands):
                self.send(item)
                if delay and (repeat < repeats - 1 or index < len(commands) - 1):
                    await asyncio.sleep(delay)

    def _extra_attributes(self) -> dict[str, Any]:
        return {
            "mode_id": self._mode,
            "switching": self._active,
            "timeout_ms": self._timeout,
            "favorite_pad": "numbers" if self.details.get("favoritePad") == 1 else "directions",
        }


@register(Platform.REMOTE, "Remote")
def _remote(_ctx: SetupContext, control: dict) -> list:
    return [LoxoneRemote(control)]
