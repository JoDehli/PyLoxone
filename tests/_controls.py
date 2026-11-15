"""Helpers for the tests of the ``controls`` package.

``control(...)`` builds a structure-file control with deterministic UUIDs;
``structure_with(base, *controls)`` returns a copy of a structure file with
the controls added. A test module overrides the ``loxapp3`` fixture with it,
so the real integration runs on exactly these controls.
"""

from __future__ import annotations

import copy
import hashlib

ROOM = "726f6f6d-0103-9697-ffff-368656e726f6000003"  # "Kitchen" in the harness
CAT = "6361743a-010c-9657-ffff-7796361743a4000012"  # "Energy" in the harness


def uuid_for(*parts: str) -> str:
    digest = hashlib.sha1("/".join(parts).encode(), usedforsecurity=False).hexdigest()
    return f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-ffff{digest[16:28]}"


def control(
    control_type: str,
    name: str,
    *,
    states: tuple[str, ...] = (),
    details: dict | None = None,
    sub_controls: dict | None = None,
    **extra,
) -> dict:
    uuid = extra.pop("uuidAction", None) or uuid_for(control_type, name)
    result = {
        "name": name,
        "type": control_type,
        "uuidAction": uuid,
        "room": ROOM,
        "cat": CAT,
        "defaultRating": 0,
        "isFavorite": False,
        "isSecured": False,
        "details": details or {},
        "states": {state: uuid_for(uuid, state) for state in states},
        **extra,
    }
    if sub_controls is not None:
        result["subControls"] = sub_controls
    return result


def structure_with(base: dict, *controls: dict) -> dict:
    structure = copy.deepcopy(base)
    for item in controls:
        structure["controls"][item["uuidAction"]] = item
    return structure


def state(item: dict, name: str) -> str:
    return item["states"][name]


def entity_id(hass, domain: str, unique_id: str) -> str:
    from homeassistant.helpers import entity_registry as er

    result = er.async_get(hass).async_get_entity_id(domain, "loxone", unique_id)
    assert result is not None, f"no {domain} entity with unique id {unique_id}"
    return result
