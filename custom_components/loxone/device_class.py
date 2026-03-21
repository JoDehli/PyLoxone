"""
Device class detection utilities for Loxone sensors.

Pure functions and constants for detecting sensor device classes from
Loxone configuration metadata (names, units, formats).
"""
from .const import SENSOR_CLASS_RULES
from .helpers import clean_unit


def _heuristic_device_class(name: str, unit: str, category: str) -> str | None:
    """
    Detect device class using rule-based matching against unit, category, and name.

    Checks rules in order. For each rule, checks matchers in order. A matcher
    matches if ALL conditions match (AND). First matching rule wins (OR between matchers).

    Condition matching:
    - unit: exact match in list
    - category: substring match (case-insensitive) in list
    - name: substring match (case-insensitive) in list

    Args:
        name: Sensor name (e.g., "Vlhkost Ložnice", "NUKI Battery")
        unit: Extracted unit (e.g., "%", "°C", "ppm")
        category: Loxone category (e.g., "Vlhkost", "Teplota")

    Returns:
        Device class string (e.g., "humidity", "temperature") or None if no match.

    """
    name_lower = name.lower()
    category_lower = category.lower()

    for rule in SENSOR_CLASS_RULES:
        for matcher in rule["matchers"]:
            # Check unit condition
            if "unit" in matcher and unit not in matcher["unit"]:
                continue

            # Check category condition
            if (
                "category" in matcher
                and not any(kw in category_lower for kw in matcher["category"])
            ):
                continue

            # Check name condition
            if (
                "name" in matcher
                and not any(kw in name_lower for kw in matcher["name"])
            ):
                continue

            # All conditions in this matcher matched
            return rule["device_class"]

    return None


def sensor_entries_from_control(
    ctrl: dict, lox_config: dict
) -> list[tuple[str, str, str, str, str]]:
    """
    Extract sensor entries from a Loxone control.

    Parses analog and Meter controls to extract sensor metadata.

    Args:
        ctrl: Control object from Loxone config
        lox_config: Full Loxone config (for room/category lookup)

    Returns:
        List of (uuid, name, room, unit, category) tuples for each sensor.

    """
    results = []
    ctrl_type = ctrl.get("type", "")

    room_uuid = ctrl.get("room", "")
    room_name = ""
    if room_uuid and "rooms" in lox_config and room_uuid in lox_config["rooms"]:
        room_name = lox_config["rooms"][room_uuid].get("name", "")

    cat_raw = ctrl.get("cat", "")
    category = lox_config.get("cats", {}).get(cat_raw, {}).get("name", cat_raw)

    if ctrl_type in ("InfoOnlyAnalog", "analog"):
        fmt = ctrl.get("details", {}).get("format", "")
        unit = clean_unit(fmt)
        results.append((ctrl["uuidAction"], ctrl.get("name", ""), room_name, unit, category))

    elif ctrl_type == "Meter":
        for state_key, _suffix, format_key in [
            ("actual", "Actual", "actualFormat"),
            ("total", "Total", "totalFormat"),
            ("totalNeg", "Total Neg", "totalFormat"),
            ("storage", "Level", "storageFormat"),
        ]:
            states = ctrl.get("states", {})
            details = ctrl.get("details", {})
            if state_key in states and format_key in details:
                fmt = details[format_key]
                unit = clean_unit(fmt)
                uuid = states[state_key]
                name = f"{ctrl.get('name', '')} {_suffix}"
                results.append((uuid, name, room_name, unit, category))

    return results
