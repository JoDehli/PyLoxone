"""Regression tests for fan (Ventilation), alarm panel, media player (AudioZoneV2).

A larger suite of behaviour tests for these platforms exists that runs under
``pytest-homeassistant-custom-component`` (``hass`` / ``mock_connection`` /
``mock_entry`` fixtures). The tests below are the subset that does not need
those fixtures: the pure-function tables and entity features.
"""

from __future__ import annotations

import pytest
from homeassistant.components.fan import FanEntityFeature
from homeassistant.components.media_player import MediaPlayerEntityFeature
from homeassistant.components.alarm_control_panel import AlarmControlPanelState

from custom_components.loxone.alarm_control_panel import alarm_arm_value
from custom_components.loxone.fan import (
    LoxoneVentilation,
    fan_speed_percentage,
    ventilation_profile_id,
    ventilation_set_mode_command,
    ventilation_set_timer_command,
)
from custom_components.loxone.media_player import (
    SUPPORT_LOXONE_AUDIO_ZONE,
    play_state_to_media_player_state,
)


def _fan(**overrides) -> LoxoneVentilation:
    kwargs = {
        "name": "Test Ventilation",
        "nameRu": "Test Ventilation",
        "uuidAction": "U68KEE6-VOA-0001-0000-000000000001",
        "room": "",
        "device_class": None,
        "type": "ventilation",
        "details": {"format": "", "hasIndoorHumidity": False, "hasAirQuality": False, "hasPresence": False},
        "states": {
            "active": "36333734-01ad-9336-ffff-d303161632d3000173",
            "mode": "36333734-01ae-9336-ffff-d303161632d3000174",
            "speed": "36333734-01ae-9336-ffff-d303161632d3000175",
        },
        "isSecured": False,
    }
    kwargs.update(overrides)
    return LoxoneVentilation(**kwargs)


# ===========================================================================
# fan.py
# ===========================================================================


def test_fan_supported_features_includes_turn_on_off() -> None:
    """TURN_ON/TURN_OFF must be advertised (required since HA 2024.8)."""
    e = _fan()
    features = e.supported_features
    assert features & FanEntityFeature.TURN_ON
    assert features & FanEntityFeature.TURN_OFF
    assert features & FanEntityFeature.PRESET_MODE
    assert features & FanEntityFeature.SET_SPEED


@pytest.mark.parametrize(
    ("speed", "expected"),
    [
        (None, None),
        (0.0, 0),
        (42.0, 42),
        (37.4, 37),
        (99.6, 100),
        (103.0, 100),
        (-0.4, 0),
        (-25.0, 0),
        (float("nan"), None),
        ("nope", None),
    ],
)
def test_fan_speed_percentage_clamped_table(speed, expected) -> None:
    """Hand-derived clamp table (raw float, possibly off-band)."""
    assert fan_speed_percentage(speed) == expected


def test_fan_speed_state_missing_from_structure() -> None:
    """A control without a `speed` state must not raise."""
    e = _fan(states={"mode": "36333734-01ae-9336-ffff-d303161632d3000174"})
    assert e.percentage is None
    assert e.get_state_value("speed") is None


def test_ventilation_set_mode_command_table() -> None:
    """Profile id, not name."""
    assert ventilation_set_mode_command("Low") == "setMode/2"
    assert ventilation_set_mode_command("Medium") == "setMode/3"
    assert ventilation_set_mode_command("High") == "setMode/4"
    assert ventilation_set_mode_command("Auto") == "setMode/5"
    assert ventilation_set_mode_command("Away") == "setMode/6"


def test_fan_profile_id_table() -> None:
    """Only the raw integer profile ids 2..6 are valid modes."""
    assert ventilation_profile_id(2) == 2
    assert ventilation_profile_id(6.0) == 6
    assert ventilation_profile_id(None) is None
    assert ventilation_profile_id(99) is None
    assert ventilation_profile_id("nope") is None


def test_ventilation_set_timer_command_table() -> None:
    """Raw integer mode in setTimer."""
    assert ventilation_set_timer_command(3600, 50, 2) == "setTimer/3600/50/2/-1"
    assert ventilation_set_timer_command(3600, 0, 6) == "setTimer/3600/0/6/-1"


# ===========================================================================
# alarm_control_panel.py
# ===========================================================================


def test_alarm_arm_value_table() -> None:
    """``ARMED_HOME`` ⇒ ``delayedon/0``, ``ARMED_AWAY`` ⇒ ``delayedon/1``."""
    assert alarm_arm_value(AlarmControlPanelState.ARMED_HOME) == "delayedon/0"
    assert alarm_arm_value(AlarmControlPanelState.ARMED_AWAY) == "delayedon/1"


def test_alarm_arm_value_rejects_non_arm_state() -> None:
    """Non-arm states should not silently produce a command."""
    with pytest.raises(ValueError):
        alarm_arm_value(AlarmControlPanelState.DISARMED)


# ===========================================================================
# media_player.py
# ===========================================================================


@pytest.mark.parametrize(
    ("play_state", "expected"),
    [
        (0, "IDLE"),
        (1, "PAUSED"),
        (2, "PLAYING"),
        (-1, "OFF"),
        # Unknown values fall back to a non-playing state instead of None.
        (-2, "IDLE"),
        (3, "IDLE"),
        (100, "IDLE"),
    ],
)
def test_play_state_to_media_player_state_table(play_state, expected) -> None:
    assert play_state_to_media_player_state(play_state).name == expected


def test_media_player_advertises_stop_feature() -> None:
    """STOP is advertised, so ``async_media_stop`` is reachable (not dead)."""
    assert SUPPORT_LOXONE_AUDIO_ZONE & MediaPlayerEntityFeature.STOP
    assert SUPPORT_LOXONE_AUDIO_ZONE & MediaPlayerEntityFeature.PAUSE
    assert SUPPORT_LOXONE_AUDIO_ZONE & MediaPlayerEntityFeature.PLAY
    # SELECT_SOURCE is not (and has never been) advertised:
    assert not (SUPPORT_LOXONE_AUDIO_ZONE & MediaPlayerEntityFeature.SELECT_SOURCE)