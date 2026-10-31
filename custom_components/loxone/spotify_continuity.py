"""Read-only legacy uncertainty fences, not a Spotify provider bridge.

0.1.1 never opens HA Spotify sessions or writes provider/journal state. Old
ambiguous dispatches remain fenced across upgrade; deleting the bridge must not
silently re-authorise native controls. Native source/announcement lifecycles are
owned by the library and entity, independently of these historical markers.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_ROOM_FENCES = "pyloxone_spotify_return_room_fences"
_DISPATCH_RESTORED = "pyloxone_spotify_return_dispatch_restored"
_DISPATCH_RESTORE_LOCK = "pyloxone_spotify_return_dispatch_restore_lock"
_DISPATCH_RESTORE_FAILED = "pyloxone_spotify_return_dispatch_restore_failed"
_MAX_DURABLE_FENCES = 1024
_MAX_DURABLE_FENCE_BYTES = 2048


def _literal(value: object, pattern: str) -> str:
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise ValueError("Invalid legacy dispatch identity")
    return value


def _room_fence_path(root: Path, room: str, player: int) -> Path:
    identity = json.dumps([room, player], separators=(",", ":"))
    return root / ("fence-" + hashlib.sha256(identity.encode()).hexdigest() + ".lock")


def _read_dispatch_fences(directory: str) -> list[dict]:
    """Read bounded historical identities without clearing or replaying them."""
    root = Path(directory)
    if not root.exists():
        return []
    result = []
    for path in root.glob("fence-*.lock"):
        if len(result) >= _MAX_DURABLE_FENCES or path.stat().st_size > _MAX_DURABLE_FENCE_BYTES:
            raise ValueError("Legacy dispatch journal is outside the supported bound")
        fence = json.loads(path.read_text())
        if (
            not isinstance(fence, dict)
            or set(fence) != {"version", "room", "player", "user", "device", "attempt"}
            or fence["version"] != 1
            or type(fence["player"]) is not int
            or fence["player"] <= 0
        ):
            raise ValueError("Legacy dispatch journal is invalid")
        _literal(fence["room"], r"[A-Za-z0-9_-]{1,128}")
        _literal(fence["user"], r"[A-Za-z0-9_.@+-]{1,128}")
        _literal(fence["device"], r"[A-Za-z0-9_-]{1,128}")
        _literal(fence["attempt"], r"[A-Za-z0-9_.-]{1,128}")
        if path != _room_fence_path(root, fence["room"], fence["player"]):
            raise ValueError("Legacy dispatch journal room identity changed")
        result.append(fence)
    return result


async def async_restore_dispatch_fences(hass: HomeAssistant) -> None:
    """Preserve pre-upgrade uncertainty before exposing native room controls."""
    lock = hass.data.setdefault(_DISPATCH_RESTORE_LOCK, asyncio.Lock())
    async with lock:
        if hass.data.get(_DISPATCH_RESTORED):
            return
        try:
            fences = await hass.async_add_executor_job(
                _read_dispatch_fences,
                hass.config.path(".storage", "pyloxone_spotify_return_dispatch"),
            )
        except (OSError, ValueError, UnicodeError):
            hass.data[_DISPATCH_RESTORE_FAILED] = True
        else:
            for fence in fences:
                hass.data.setdefault(_ROOM_FENCES, set()).add((fence["room"], fence["player"]))
        hass.data[_DISPATCH_RESTORED] = True


def spotify_room_uncertain(hass: HomeAssistant, room: str, player: int | None) -> bool:
    """Retain historical room fences without any provider/account dependency."""
    return bool(hass.data.get(_DISPATCH_RESTORE_FAILED)) or (room, player) in hass.data.get(_ROOM_FENCES, set())
