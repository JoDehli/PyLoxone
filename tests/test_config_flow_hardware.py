"""Tests for conditional physical hardware configuration."""

from __future__ import annotations

import asyncio

from homeassistant.const import CONF_PORT

from custom_components.loxone.config_flow import CONFIG_FLOW, OPTIONS_FLOW
from custom_components.loxone.const import (
    CONF_HARDWARE_BATTERY_INTERVAL,
    CONF_HARDWARE_ENABLED,
    CONF_HARDWARE_FAST_POLL_INTERVAL,
    CONF_HARDWARE_INVENTORY_INTERVAL,
    DEFAULT_PORT,
)


def _schema_keys(step) -> set[str]:
    return {key.schema for key in step.schema.schema}


def test_hardware_intervals_are_not_on_initial_forms() -> None:
    interval_keys = {
        CONF_HARDWARE_FAST_POLL_INTERVAL,
        CONF_HARDWARE_INVENTORY_INTERVAL,
        CONF_HARDWARE_BATTERY_INTERVAL,
    }

    for flow, initial_step in ((CONFIG_FLOW, "user"), (OPTIONS_FLOW, "init")):
        initial_keys = _schema_keys(flow[initial_step])
        hardware_keys = _schema_keys(flow["hardware"])

        assert CONF_HARDWARE_ENABLED in initial_keys
        assert initial_keys.isdisjoint(interval_keys)
        assert hardware_keys == interval_keys


def test_hardware_step_is_skipped_when_discovery_is_disabled() -> None:
    for flow, initial_step in ((CONFIG_FLOW, "user"), (OPTIONS_FLOW, "init")):
        next_step = flow[initial_step].next_step
        assert asyncio.run(next_step({CONF_HARDWARE_ENABLED: False})) is None


def test_hardware_step_is_shown_when_discovery_is_enabled() -> None:
    for flow, initial_step in ((CONFIG_FLOW, "user"), (OPTIONS_FLOW, "init")):
        next_step = flow[initial_step].next_step
        assert asyncio.run(next_step({CONF_HARDWARE_ENABLED: True})) == "hardware"


def test_local_http_port_is_the_setup_default() -> None:
    """Use the Miniserver's local HTTP port for new config entries."""
    port_key = next(key for key in CONFIG_FLOW["user"].schema.schema if key.schema == CONF_PORT)

    assert DEFAULT_PORT == 80
    assert port_key.default() == 80
