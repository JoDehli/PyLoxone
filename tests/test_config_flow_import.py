"""YAML import (``loxone:`` in configuration.yaml) creates the entry once."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from custom_components.loxone import config_flow
from custom_components.loxone.config_flow import LoxoneFlowHandler


@pytest.fixture(autouse=True)
def _real_conf_keys(monkeypatch):
    """Use HA's real ``CONF_*`` values when ``homeassistant`` is stubbed."""
    for name, value in (
        ("CONF_HOST", "host"),
        ("CONF_PORT", "port"),
        ("CONF_USERNAME", "username"),
        ("CONF_PASSWORD", "password"),
    ):
        if not isinstance(getattr(config_flow, name), str):
            monkeypatch.setattr(config_flow, name, value)

YAML = {
    "username": "admin",
    "password": "secret",
    "host": "10.0.0.2",
    "port": 80,
    "verify_ssl": True,
    "generate_scenes": True,
    "generate_scenes_delay": 3,
    "generate_lightcontroller_subcontrols": False,
}


def _flow(existing_options):
    flow = LoxoneFlowHandler.__new__(LoxoneFlowHandler)
    flow._async_current_entries = lambda: [
        SimpleNamespace(options=opts) for opts in existing_options
    ]
    flow.async_abort = lambda reason: {"type": "abort", "reason": reason}
    flow.async_create_entry = lambda data: {"type": "create_entry", "options": data}
    return flow


def test_import_creates_entry():
    result = asyncio.run(_flow([]).async_step_import(dict(YAML)))
    assert result["type"] == "create_entry"
    assert result["options"]["host"] == "10.0.0.2"


def test_import_runs_only_once_per_miniserver():
    result = asyncio.run(
        _flow([{"host": "10.0.0.2", "port": 80}]).async_step_import(dict(YAML))
    )
    assert result == {"type": "abort", "reason": "already_configured"}


def test_import_of_another_miniserver_is_created():
    result = asyncio.run(
        _flow([{"host": "10.0.0.9", "port": 80}]).async_step_import(dict(YAML))
    )
    assert result["type"] == "create_entry"


def test_import_with_non_latin1_password_aborts():
    result = asyncio.run(
        _flow([]).async_step_import({**YAML, "password": "pässwört€"})
    )
    assert result == {"type": "abort", "reason": "invalid_import"}
