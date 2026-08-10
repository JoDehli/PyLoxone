"""Tests for Loxone config entry migrations."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from custom_components.loxone import async_migrate_entry
from custom_components.loxone.const import (
    CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN,
    CONF_SCENE_GEN_DELAY,
    CONF_VERIFY_SSL,
    DEFAULT_DELAY_SCENE,
    DEFAULT_VERIFY_SSL,
)


class _ConfigEntries:
    def __init__(self) -> None:
        self.calls = []

    def async_update_entry(self, entry, **changes) -> None:
        self.calls.append(changes)
        for key, value in changes.items():
            setattr(entry, key, value)


def test_version_three_migration_uses_home_assistant_update_api() -> None:
    config_entries = _ConfigEntries()
    hass = SimpleNamespace(config_entries=config_entries)
    entry = SimpleNamespace(version=3, options={"host": "192.0.2.1"})

    assert asyncio.run(async_migrate_entry(hass, entry)) is True

    assert entry.version == 4
    assert entry.options[CONF_VERIFY_SSL] is DEFAULT_VERIFY_SSL
    assert len(config_entries.calls) == 1


def test_version_one_migrates_through_all_versions_in_one_update() -> None:
    config_entries = _ConfigEntries()
    hass = SimpleNamespace(config_entries=config_entries)
    entry = SimpleNamespace(version=1, options={})

    assert asyncio.run(async_migrate_entry(hass, entry)) is True

    assert entry.version == 4
    assert entry.options[CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN] is True
    assert entry.options[CONF_SCENE_GEN_DELAY] == DEFAULT_DELAY_SCENE
    assert entry.options[CONF_VERIFY_SSL] is DEFAULT_VERIFY_SSL
    assert len(config_entries.calls) == 1


def test_current_version_does_not_update_entry() -> None:
    config_entries = _ConfigEntries()
    hass = SimpleNamespace(config_entries=config_entries)
    entry = SimpleNamespace(version=4, options={})

    assert asyncio.run(async_migrate_entry(hass, entry)) is True

    assert config_entries.calls == []
