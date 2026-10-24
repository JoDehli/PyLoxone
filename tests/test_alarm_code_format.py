"""Secured Loxone alarms take the visualisation password, which may contain
letters - the HA alarm card must not show a numeric-only keypad."""

from __future__ import annotations

from homeassistant.components.alarm_control_panel.const import CodeFormat

from custom_components.loxone.alarm_control_panel import LoxoneAlarm


def _alarm(is_secured: bool) -> LoxoneAlarm:
    return LoxoneAlarm(
        name="Alarm",
        uuidAction="alarm-uuid",
        room="",
        cat="",
        type="Alarm",
        isSecured=is_secured,
        states={},
        details={},
    )


def test_secured_alarm_accepts_text_codes():
    alarm = _alarm(True)
    assert alarm._attr_code_arm_required is True
    assert alarm._attr_code_format == CodeFormat.TEXT


def test_unsecured_alarm_needs_no_code():
    alarm = _alarm(False)
    assert alarm._attr_code_arm_required is False
    assert alarm._attr_code_format is None
