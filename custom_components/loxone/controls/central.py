"""Central objects (structure file spec V17, "Central Objects", since 9.0).

CentralAlarm, CentralAudioZone, CentralGate, CentralJalousie,
CentralLightController, CentralWindow and CentralPresence have no states;
``details.controls`` lists the members (``uuid``, ``id``) and a command
sent to the central object applies to all of them:

* CentralAlarm: on, off, quit, delayedon
* CentralAudio(Zone): play, pause, volup, voldown
* CentralGate: open, close, stop
* CentralJalousie: FullUp, FullDown, shade, auto, NoAuto, stop
* CentralLightController: on, reset
* CentralWindow: fullopen, fullclose, slightlyOpen, stop, ...
* CentralPresence: no commands in the spec

Without states, covers report an assumed state.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import CoverDeviceClass, CoverEntity, CoverEntityFeature
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import Platform

from . import SetupContext, register
from .base import ControlButton, ControlEntity


def member_names(loxconfig: dict, control: dict) -> list[str]:
    """Names of the member controls (uuid when not in the structure file)."""
    controls = loxconfig.get("controls", {})
    names = []
    for member in (control.get("details") or {}).get("controls") or []:
        if not isinstance(member, dict):
            continue
        uuid = member.get("uuid")
        found = controls.get(uuid) if isinstance(uuid, str) else None
        names.append(found.get("name") if found else uuid)
    return names


class _MembersMixin:
    members: list[str]

    def _extra_attributes(self) -> dict[str, Any]:
        return {"controls": self.members}


class CentralCover(_MembersMixin, ControlEntity, CoverEntity):
    """A central cover: open / close / stop for all members."""

    _attr_assumed_state = True
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    _attr_is_closed = None

    def __init__(
        self, control: dict, members: list[str], *, device_class: CoverDeviceClass, commands: tuple[str, str, str]
    ) -> None:
        super().__init__(control)
        self.members = members
        self._attr_device_class = device_class
        self._open, self._close, self._stop = commands

    async def async_open_cover(self, **kwargs: Any) -> None:
        self.send(self._open)

    async def async_close_cover(self, **kwargs: Any) -> None:
        self.send(self._close)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        self.send(self._stop)


class CentralMembersSensor(_MembersMixin, ControlEntity, SensorEntity):
    """Number of member controls (for central objects without commands)."""

    _attr_icon = "mdi:format-list-bulleted"

    def __init__(self, control: dict, members: list[str]) -> None:
        super().__init__(control)
        self.members = members
        self._attr_native_value = len(members)


_COVERS = {
    "CentralJalousie": (CoverDeviceClass.SHUTTER, ("FullUp", "FullDown", "stop")),
    "CentralGate": (CoverDeviceClass.GATE, ("open", "close", "stop")),
    "CentralWindow": (CoverDeviceClass.WINDOW, ("fullopen", "fullclose", "stop")),
}

# Commands without a matching cover action: (command, name suffix, icon).
_BUTTONS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "CentralJalousie": (
        ("shade", "Shade", "mdi:weather-sunny"),
        ("auto", "Automatic On", "mdi:refresh-auto"),
        ("NoAuto", "Automatic Off", "mdi:sync-off"),
    ),
    "CentralWindow": (("slightlyOpen", "Slightly Open", "mdi:window-open-variant"),),
    "CentralAlarm": (
        ("on", "Arm", "mdi:shield-lock"),
        ("delayedon", "Arm Delayed", "mdi:shield-lock-outline"),
        ("off", "Disarm", "mdi:shield-off"),
        ("quit", "Acknowledge", "mdi:bell-check"),
    ),
    "CentralAudioZone": (
        ("play", "Play", "mdi:play"),
        ("pause", "Pause", "mdi:pause"),
        ("volup", "Volume Up", "mdi:volume-plus"),
        ("voldown", "Volume Down", "mdi:volume-minus"),
    ),
    "CentralLightController": (
        ("on", "On", "mdi:lightbulb-group"),
        ("reset", "Off", "mdi:lightbulb-group-off"),
    ),
}


@register(Platform.COVER, *_COVERS)
def _covers(ctx: SetupContext, control: dict) -> list:
    device_class, commands = _COVERS[control["type"]]
    return [CentralCover(control, member_names(ctx.loxconfig, control), device_class=device_class, commands=commands)]


@register(Platform.BUTTON, *_BUTTONS)
def _buttons(_ctx: SetupContext, control: dict) -> list:
    return [ControlButton(control, command, suffix, icon=icon) for command, suffix, icon in _BUTTONS[control["type"]]]


@register(Platform.SENSOR, "CentralAlarm", "CentralAudioZone", "CentralLightController", "CentralPresence")
def _members(ctx: SetupContext, control: dict) -> list:
    # Button-only central objects get their member list on a sensor; the
    # covers carry it as an attribute.
    return [CentralMembersSensor(control, member_names(ctx.loxconfig, control))]
