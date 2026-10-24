"""LightControllerV2 command encoding + mood state semantics.

Spec facts (Structure File, LightControllerV2, pages 95-98):
- mood playback `changeTo/{moodId}`, mood id **0 is always off**
- the ids 99 / 778 are NOT in the spec (runtime conventions of the
  analysis installation), see docs/IMPLEMENTED_CONTROL_TYPES_EN.md,
  section "LightControllerV2"
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from custom_components.loxone.lights.lightcontroller import LoxoneLightControllerV2
from homeassistant.const import STATE_UNKNOWN


def _controller(moodlist=None, active_moods=None) -> tuple:
    sent: list = []
    controller = LoxoneLightControllerV2.__new__(LoxoneLightControllerV2)
    controller.hass = SimpleNamespace(
        bus=SimpleNamespace(
            fire=lambda domain, data: sent.append(data["value"]),
            async_fire=lambda domain, data: sent.append(data["value"]),
        )
    )
    controller.uuidAction = "lc-uuid"
    controller.name = "Licht"
    controller.states = {}
    controller._moodlist = moodlist if moodlist is not None else []
    controller._additional_moodlist = []
    controller._active_moods = active_moods if active_moods is not None else []
    controller._master_position_loxone = None
    controller._attr_state = STATE_UNKNOWN
    controller._attr_is_on = STATE_UNKNOWN
    controller._attr_available = False
    controller._attr_brightness = None
    controller._master_value = None
    controller._master_value_uuid = None
    controller._master_position_uuid = None
    controller._master_min_uuid = None
    controller._master_max_uuid = None
    controller._master_min = None
    controller._master_max = None
    controller._sub_controls = {}
    controller._uuid_dict = {}
    controller.schedule_update_ha_state = lambda: None
    controller.async_schedule_update_ha_state = lambda: None
    return controller, sent


# --- is_on semantics --------------------------------------------------------


def test_event_empty_active_moods_is_off():
    controller, sent = _controller()
    controller.states = {"activeMoods": "uuid-activemoods"}

    asyncio.run(controller.event_handler(SimpleNamespace(data={"uuid-activemoods": "[]"})))

    assert controller._attr_is_on is False


def test_event_spec_off_mood_0_is_off():
    """The spec declares mood id 0 as *always off* - previously only the
    runtime id 778 switched the entity off, so [0] kept it 'on'."""
    controller, sent = _controller()
    controller.states = {"activeMoods": "uuid-activemoods"}

    asyncio.run(controller.event_handler(SimpleNamespace(data={"uuid-activemoods": "[0]"})))

    assert controller._attr_is_on is False


def test_event_778_runtime_off_id_is_off():
    """Regression: the observed runtime off id stays handled as off until
    empirically verified otherwise."""
    controller, sent = _controller()
    controller.states = {"activeMoods": "uuid-activemoods"}

    asyncio.run(controller.event_handler(SimpleNamespace(data={"uuid-activemoods": "[778]"})))

    assert controller._attr_is_on is False


def test_event_real_mood_is_on():
    controller, sent = _controller()
    controller.states = {"activeMoods": "uuid-activemoods"}

    asyncio.run(controller.event_handler(SimpleNamespace(data={"uuid-activemoods": "[3]"})))

    assert controller._attr_is_on is True


def test_event_mixed_off_and_real_mood_is_on():
    controller, sent = _controller()
    controller.states = {"activeMoods": "uuid-activemoods"}

    asyncio.run(controller.event_handler(SimpleNamespace(data={"uuid-activemoods": "[0, 3]"})))

    assert controller._attr_is_on is True


# --- turn_on/turn_off command encoding ---------------------------------------


def test_turn_on_without_kwargs_activates_the_first_mood():
    """`changeTo/99` was a runtime convention of one installation and is
    not in the spec; plain turn-on activates the first known mood."""
    controller, sent = _controller(
        moodlist=[{"id": 3, "name": "Eins"}, {"id": 5, "name": "Zwei"}]
    )
    controller._attr_is_on = False

    asyncio.run(controller.async_turn_on())

    assert sent == ["changeTo/3"]


def test_turn_on_without_kwargs_falls_back_to_plus_without_moods():
    controller, sent = _controller(moodlist=[])
    controller._attr_is_on = False

    asyncio.run(controller.async_turn_on())

    assert sent == ["plus"]


def test_turn_on_without_kwargs_while_on_is_a_noop():
    controller, sent = _controller(
        moodlist=[{"id": 3, "name": "Eins"}]
    )
    controller._attr_is_on = True

    asyncio.run(controller.async_turn_on())

    assert sent == []


def test_turn_off_sends_spec_change_to_0():
    controller, sent = _controller()

    asyncio.run(controller.async_turn_off())

    assert sent == ["changeTo/0"]


def _manual_controller(position_uuid="uuid-master"):
    controller, sent = _controller()
    controller.states = {"activeMoods": "uuid-activemoods"}
    controller._master_position_uuid = position_uuid
    return controller


def test_manual_mode_with_lit_master_is_on():
    """Moving the master directly clears activeMoods ("Stimmung Manuell"),
    the circuits stay lit - empty mood list must follow the master value."""
    controller = _manual_controller()

    asyncio.run(controller.event_handler(SimpleNamespace(data={
        "uuid-master": 57.0, "uuid-activemoods": "[]",
    })))

    assert controller._attr_is_on is True


def test_manual_mode_with_master_at_zero_is_off():
    controller = _manual_controller()

    asyncio.run(controller.event_handler(SimpleNamespace(data={
        "uuid-master": 0.0, "uuid-activemoods": "[]",
    })))

    assert controller._attr_is_on is False


def test_master_position_change_alone_switches_manual_mode_off():
    controller = _manual_controller()
    asyncio.run(controller.event_handler(SimpleNamespace(data={
        "uuid-master": 57.0, "uuid-activemoods": "[]",
    })))

    asyncio.run(controller.event_handler(SimpleNamespace(data={"uuid-master": 0.0})))

    assert controller._attr_is_on is False
