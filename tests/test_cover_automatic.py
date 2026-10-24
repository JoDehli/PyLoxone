"""Jalousie sun automation reads the spec states autoActive / infoText."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from custom_components.loxone.cover import LoxoneJalousie

STATES = {
    "position": "uuid-position",
    "shadePosition": "uuid-shade",
    "up": "uuid-up",
    "down": "uuid-down",
    "targetPosition": "uuid-target",
    "autoActive": "uuid-auto-active",
    "infoText": "uuid-info",
}


def _jalousie(states=STATES) -> LoxoneJalousie:
    cover = LoxoneJalousie(
        hass=None,
        name="Blind",
        uuidAction="blind-uuid",
        room="",
        cat="",
        type="Jalousie",
        states=dict(states),
        details={"isAutomatic": True, "animation": 0},
    )
    cover.schedule_update_ha_state = lambda: None
    return cover


def _event(cover, data):
    asyncio.run(cover.event_handler(SimpleNamespace(data=data)))


def test_auto_active_turns_sun_automation_on():
    from custom_components.loxone.cover import STATE_ON

    cover = _jalousie()
    _event(cover, {"uuid-auto-active": 1, "uuid-info": "Sun protection"})

    assert cover.auto == STATE_ON
    assert cover._auto_text == "Sun protection"


def test_spec_states_are_not_overwritten():
    """The old code wrote "" placeholders into ``states``."""
    cover = _jalousie()
    assert "autoState" not in cover.states
    assert "autoInfoText" not in cover.states


def test_legacy_state_names_still_work():
    from custom_components.loxone.cover import STATE_ON

    legacy = {k: v for k, v in STATES.items() if k not in ("autoActive", "infoText")}
    legacy["autoState"] = "uuid-legacy-auto"
    cover = _jalousie(legacy)
    _event(cover, {"uuid-legacy-auto": 1})

    assert cover.auto == STATE_ON
