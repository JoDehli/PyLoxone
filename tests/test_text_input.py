"""TextInput as a writable HA text entity."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from custom_components.loxone.const import LOXONE_PLATFORMS, Platform
from custom_components.loxone.text import MAX_TEXT_LENGTH, LoxoneText


def _text() -> LoxoneText:
    entity = LoxoneText(
        name="Message",
        uuidAction="text-uuid",
        room="",
        cat="",
        type="TextInput",
        states={"text": "text-state-uuid"},
        details={},
    )
    entity.async_write_ha_state = lambda: None
    return entity


def _event(entity, data):
    asyncio.run(entity.event_handler(SimpleNamespace(data=data)))


def test_text_platform_is_forwarded():
    assert Platform.TEXT in LOXONE_PLATFORMS


def test_value_comes_from_the_text_state():
    entity = _text()
    assert entity._attr_native_value is None  # unknown until the first value

    _event(entity, {"text-state-uuid": "Hello"})
    assert entity._attr_native_value == "Hello"

    # The control uuid itself does not carry the value.
    _event(entity, {"text-uuid": "ignored"})
    assert entity._attr_native_value == "Hello"


def test_long_values_are_truncated():
    entity = _text()
    _event(entity, {"text-state-uuid": "x" * 300})
    assert len(entity._attr_native_value) == MAX_TEXT_LENGTH
