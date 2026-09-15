"""Tests for conditional physical hardware configuration."""

from __future__ import annotations

from homeassistant.const import CONF_PORT

from custom_components.loxone.config_flow import CONFIG_FLOW, OPTIONS_FLOW
from custom_components.loxone.const import (
    CONF_HARDWARE_BATTERY_INTERVAL,
    CONF_HARDWARE_ENABLED,
    CONF_HARDWARE_FAST_POLL_INTERVAL,
    CONF_HARDWARE_INVENTORY_INTERVAL,
    DEFAULT_PORT,
)


def _schema_fields(step) -> dict[str, object]:
    return {key.schema: selector for key, selector in step.schema.schema.items()}


def test_hardware_intervals_follow_discovery_switch_visibility() -> None:
    """Keep interval fields on the same form and bind visibility to the switch."""
    interval_keys = {
        CONF_HARDWARE_FAST_POLL_INTERVAL,
        CONF_HARDWARE_INVENTORY_INTERVAL,
        CONF_HARDWARE_BATTERY_INTERVAL,
    }

    for flow, initial_step in ((CONFIG_FLOW, "user"), (OPTIONS_FLOW, "init")):
        fields = _schema_fields(flow[initial_step])

        assert CONF_HARDWARE_ENABLED in fields
        assert interval_keys <= fields.keys()
        for key in interval_keys:
            assert fields[key].serialize()["visible"] == {
                "field": CONF_HARDWARE_ENABLED,
                "operator": "eq",
                "value": True,
            }


def test_local_http_port_is_the_setup_default() -> None:
    """Use the Miniserver's local HTTP port for new config entries."""
    port_key = next(key for key in CONFIG_FLOW["user"].schema.schema if key.schema == CONF_PORT)

    assert DEFAULT_PORT == 80
    assert port_key.default() == 80
