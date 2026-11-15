"""Information-only controls without states (structure file spec V17).

* Application: ``details.url`` / ``image`` / ``iconColor``
* MsShortcut (Miniserver shortcut): ``details`` with the addresses
* SystemScheme: ``details`` with the image and the referenced controls

None of them has states or commands; each becomes a sensor whose value
comes from the structure file. TextState and InfoOnlyText are sensors of
``sensor.py``; :func:`text_presentation` names their unnamed scheme cells.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import Platform

from ..helpers import get_or_create_device
from . import SetupContext, register
from .base import ControlEntity, to_text

# --- unnamed text cells of a system scheme -------------------------------------


def has_meaningful_name(name: Any) -> bool:
    """False for names without any letter or digit, like ``-``."""
    return any(char.isalnum() for char in str(name or ""))


def scheme_references(loxconfig: dict) -> dict[str, tuple[dict, int]]:
    """Control uuid -> (SystemScheme control, 1-based position in its references)."""
    result: dict[str, tuple[dict, int]] = {}
    for scheme in loxconfig.get("controls", {}).values():
        if scheme.get("type") != "SystemScheme":
            continue
        references = (scheme.get("details") or {}).get("controlReferences") or []
        for position, ref in enumerate(references, start=1):
            uuid = ref.get("uuidAction") if isinstance(ref, dict) else None
            if isinstance(uuid, str):
                result.setdefault(uuid, (scheme, position))
    return result


@dataclass(frozen=True)
class TextPresentation:
    """How a text control is shown.

    System schemes place many unnamed text cells ("-") on an image; on
    their own they mean nothing, so they get the scheme's name and their
    position, live on the scheme's device and start disabled.
    """

    name: str
    enabled_default: bool = True
    scheme: dict | None = None
    position: int | None = None
    original_name: str | None = None


def text_presentation(loxconfig: dict, control: dict) -> TextPresentation:
    name = control.get("name", "")
    if has_meaningful_name(name):
        return TextPresentation(name=name)
    ref = scheme_references(loxconfig).get(control.get("uuidAction"))
    if ref is not None:
        scheme, position = ref
        return TextPresentation(
            name=f"{scheme.get('name', '')} {position}",
            enabled_default=False,
            scheme=scheme,
            position=position,
            original_name=name,
        )
    return TextPresentation(
        name=f"{control.get('type', '')} {control.get('uuidAction', '')[:8]}",
        enabled_default=False,
        original_name=name,
    )


def _room_name(loxconfig: dict, room: Any) -> str:
    """Room name for a room uuid; a value that is no uuid is already a name."""
    rooms = loxconfig.get("rooms") or {}
    if isinstance(room, str) and room in rooms:
        return rooms[room].get("name", "")
    return room if isinstance(room, str) else ""


def apply_text_presentation(loxconfig: dict, entity: Any, presentation: TextPresentation) -> None:
    """Apply ``presentation`` to a text sensor built with its name."""
    entity._attr_entity_registry_enabled_default = presentation.enabled_default  # noqa: SLF001
    if presentation.original_name is None:
        return
    attributes: dict[str, Any] = {"original_name": presentation.original_name}
    scheme = presentation.scheme
    if scheme is not None:
        entity._attr_device_info = get_or_create_device(  # noqa: SLF001
            scheme["uuidAction"], scheme.get("name", ""), "SystemScheme", _room_name(loxconfig, scheme.get("room"))
        )
        attributes["system_scheme"] = scheme.get("name")
        attributes["scheme_position"] = presentation.position
    entity._attr_extra_state_attributes.update(attributes)  # noqa: SLF001


# --- controls without states ---------------------------------------------------


class StaticInfoSensor(ControlEntity, SensorEntity):
    """A control without states: the value comes from the structure file."""

    def __init__(self, control: dict, value: Any, attributes: dict[str, Any], icon: str) -> None:
        super().__init__(control, icon=icon)
        self._attr_native_value = to_text(value) if value not in (None, "") else None
        self._static_attributes = attributes

    def _extra_attributes(self) -> dict[str, Any]:
        return self._static_attributes


def _control_name(loxconfig: dict, uuid: Any) -> str | None:
    found = loxconfig.get("controls", {}).get(uuid) if isinstance(uuid, str) else None
    return found.get("name") if found else None


@register(Platform.SENSOR, "Application")
def _application(_ctx: SetupContext, control: dict) -> list:
    details = control.get("details") or {}
    return [
        StaticInfoSensor(
            control,
            details.get("url"),
            {"url": details.get("url"), "image": details.get("image"), "icon_color": details.get("iconColor")},
            "mdi:application-outline",
        )
    ]


@register(Platform.SENSOR, "MsShortcut")
def _ms_shortcut(_ctx: SetupContext, control: dict) -> list:
    details = control.get("details") or {}
    trust = bool(details.get("trust"))
    # Trust members have no addresses; the serial number identifies them.
    value = details.get("serialNr") if trust else details.get("localUrl") or details.get("remoteUrl")
    return [
        StaticInfoSensor(
            control,
            value,
            {
                "serial_number": details.get("serialNr"),
                "trust": trust,
                "local_url": details.get("localUrl"),
                "remote_url": details.get("remoteUrl"),
            },
            "mdi:server-network",
        )
    ]


@register(Platform.SENSOR, "SystemScheme")
def _system_scheme(ctx: SetupContext, control: dict) -> list:
    details = control.get("details") or {}
    controls = ctx.loxconfig.get("controls", {})
    referenced = []
    for ref in details.get("controlReferences") or []:
        uuid = ref.get("uuidAction") if isinstance(ref, dict) else None
        found = controls.get(uuid) if isinstance(uuid, str) else None
        # Unnamed cells are listed under the name their entity gets.
        referenced.append(text_presentation(ctx.loxconfig, found).name if found else uuid)
    main = details.get("mainControl")
    return [
        StaticInfoSensor(
            control,
            _control_name(ctx.loxconfig, main),
            {
                "main_control": main,
                "controls": referenced,
                "image_path": details.get("imagePath"),
                "image_version": details.get("imageVersion"),
            },
            "mdi:sitemap-outline",
        )
    ]
