"""
Loxone control types handled outside the classic platform modules.

Each module in this package covers one group of control types from the
Loxone structure file spec and registers a builder per Home Assistant
platform::

    @register(Platform.SENSOR, "Hourcounter")
    def _sensors(ctx: SetupContext, control: dict) -> list[Entity]:
        ...

The platform modules call :func:`async_setup_controls` once from their
``async_setup_entry``; the modules of this package are discovered
automatically, so adding a control type never touches the platforms.
"""

from __future__ import annotations

import copy
import importlib
import logging
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ..helpers import add_room_and_cat_to_value_values

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SetupContext:
    """What a builder may need besides the control itself."""

    hass: HomeAssistant
    config_entry: ConfigEntry
    loxconfig: dict
    async_add_entities: AddEntitiesCallback


Builder = Callable[[SetupContext, dict], list[Entity]]


@dataclass(frozen=True)
class EntityService:
    """An entity service of one platform, limited by a feature flag."""

    name: str
    schema: dict
    method: str
    feature: int


_BUILDERS: dict[str, list[tuple[frozenset[str], Builder]]] = {}
_SERVICES: dict[str, list[EntityService]] = {}
_modules_loaded = False


def register(platform: str, *control_types: str) -> Callable[[Builder], Builder]:
    """Register ``builder`` for ``control_types`` on ``platform``."""

    def decorator(builder: Builder) -> Builder:
        _BUILDERS.setdefault(str(platform), []).append((frozenset(control_types), builder))
        return builder

    return decorator


def register_service(platform: str, name: str, method: str, feature: int, schema: dict | None = None) -> None:
    """Register an entity service; only entities advertising ``feature`` get it."""
    services = _SERVICES.setdefault(str(platform), [])
    if all(service.name != name for service in services):
        services.append(EntityService(name, schema or {}, method, feature))


def _load_modules() -> None:
    global _modules_loaded  # noqa: PLW0603 - one-time import of the package
    if _modules_loaded:
        return
    for module in pkgutil.iter_modules(__path__):
        if not module.name.startswith("_") and module.name != "base":
            importlib.import_module(f"{__name__}.{module.name}")
    _modules_loaded = True


def handled_types(platform: str | None = None) -> set[str]:
    """Control types this package builds entities for."""
    _load_modules()
    platforms = [str(platform)] if platform else list(_BUILDERS)
    return {control_type for name in platforms for types, _ in _BUILDERS.get(name, []) for control_type in types}


def build_entities(platform: str, ctx: SetupContext) -> list[Entity]:
    """All entities of ``platform`` for the controls in ``ctx.loxconfig``."""
    _load_modules()
    builders = _BUILDERS.get(str(platform), [])
    entities: list[Entity] = []
    for control in ctx.loxconfig.get("controls", {}).values():
        control_type = control.get("type")
        for types, builder in builders:
            if control_type not in types:
                continue
            # A copy: builders may enrich it, the structure stays pristine.
            prepared = add_room_and_cat_to_value_values(ctx.loxconfig, copy.deepcopy(control))
            try:
                entities.extend(builder(ctx, prepared))
            except Exception:
                # One odd control must not take down the whole platform.
                _LOGGER.exception("Skipping %s control %s", control_type, control.get("name"))
    return entities


def async_setup_controls(
    platform: str,
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    loxconfig: dict,
    async_add_entities: AddEntitiesCallback,
) -> list[Entity]:
    """
    Build the entities of ``platform`` and register its entity services.

    Must run inside the platform's ``async_setup_entry``.
    """
    ctx = SetupContext(hass, config_entry, loxconfig, async_add_entities)
    entities = build_entities(platform, ctx)
    services = _SERVICES.get(str(platform), [])
    if services:
        try:
            current = entity_platform.async_get_current_platform()
        except RuntimeError:
            # Called outside a platform setup (direct calls in tests).
            _LOGGER.debug("No current %s platform; entity services not registered", platform)
            return entities
        for service in services:
            current.async_register_entity_service(service.name, service.schema, service.method, [service.feature])
    return entities


__all__ = [
    "SetupContext",
    "async_setup_controls",
    "build_entities",
    "handled_types",
    "register",
    "register_service",
]


# Import the control modules now, while Home Assistant imports the platform
# modules in its import executor: ``pkgutil.iter_modules`` lists the
# directory and ``import_module`` reads files, both blocking calls that HA
# reports when they run inside the event loop (first platform setup).
_load_modules()
