"""Models for the physical Loxone hardware inventory."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True, frozen=True)
class UiControl:
    """A top-level control exposed by LoxAPP3.json."""

    uuid: str
    name: str
    control_type: str
    room: str | None = None
    category: str | None = None
    states: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class HardwareDevice:
    """A physical device connected through Loxone Air."""

    device_id: str
    serial: str
    name: str
    device_type: str
    air_base: str
    room: str | None = None
    installation: str | None = None
    online: bool = False
    battery: int | None = None
    battery_low: bool | None = None
    last_received: datetime | None = None
    firmware: str | None = None
    hardware_version: str | None = None
    system_temperature: float | None = None
    hops: int | None = None
    quality_extension: int | None = None
    quality_device: int | None = None
    position: int | None = None
    vibration: bool | None = None
    automatic_mappings: dict[str, str] = field(default_factory=dict)
    resolved_mappings: dict[str, str] = field(default_factory=dict)
    push_state_uuids: dict[str, str] = field(default_factory=dict)
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def is_window_handle(self) -> bool:
        """Return whether this is a Window Handle Air."""
        return self.device_type.casefold() == "fenstergriff air"

    @property
    def address_prefix(self) -> str:
        """Return the physical I/O address prefix."""
        return f"{self.air_base}.{self.device_id}"

    @property
    def position_name(self) -> str:
        """Return the normalized handle position."""
        return {1: "closed", 2: "tilted", 3: "open"}.get(self.position, "unknown")


@dataclass(slots=True)
class HardwareData:
    """Current physical hardware snapshot."""

    miniserver_serial: str
    miniserver_name: str
    miniserver_version: str | None
    air_base: str
    air_base_version: str | None
    devices: dict[str, HardwareDevice] = field(default_factory=dict)
    controls: dict[str, UiControl] = field(default_factory=dict)
    last_poll: datetime | None = None
    last_inventory: datetime | None = None
    last_push: datetime | None = None

    def control(self, control_uuid: str | None) -> UiControl | None:
        """Return a control using a case-insensitive UUID lookup."""
        if not control_uuid:
            return None
        return self.controls.get(control_uuid.casefold())


def control_catalog(structure: dict[str, Any]) -> dict[str, UiControl]:
    """Build a stable UI-control catalog from LoxAPP3.json."""
    rooms = structure.get("rooms", {})
    categories = structure.get("cats", {})
    result: dict[str, UiControl] = {}
    for key, raw in structure.get("controls", {}).items():
        uuid = str(raw.get("uuidAction") or key).casefold()
        if not uuid:
            continue
        room = rooms.get(raw.get("room"), {}).get("name")
        category = categories.get(raw.get("cat"), {}).get("name")
        result[uuid] = UiControl(
            uuid=uuid,
            name=str(raw.get("name") or uuid),
            control_type=str(raw.get("type") or "Unknown"),
            room=room,
            category=category,
            states={str(name): str(value).casefold() for name, value in (raw.get("states") or {}).items()},
        )
    return result
