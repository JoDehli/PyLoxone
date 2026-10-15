"""Climate commands and states against the Loxone structure file spec."""

from __future__ import annotations

from types import SimpleNamespace

from custom_components.loxone.climate import (ActiveMode, ActiveState,
                                              LoxoneRoomControllerV2,
                                              OperatingMode)


def _room_controller_v2(sent: list, operating_mode, active_mode, **state_values):
    rc = LoxoneRoomControllerV2.__new__(LoxoneRoomControllerV2)
    rc.hass = SimpleNamespace(
        bus=SimpleNamespace(fire=lambda domain, data: sent.append(data["value"]))
    )
    rc.uuidAction = "rc-uuid"
    rc.operating_mode = operating_mode
    rc.active_state = ActiveState(mode=active_mode, value=0)
    rc._range_possible = False
    rc._states = {name: f"uuid-{name}" for name in state_values}
    rc._state_attr_values = {f"uuid-{name}": v for name, v in state_values.items()}
    rc.schedule_update_ha_state = lambda: None
    return rc


def test_comfort_mode_temp_is_the_absolute_temperature():
    """Spec: setComfortModeTemp/{temp} with temp = comfortTemperature +
    comfortTemperatureOffset ± 0.5 - an absolute temperature, not an
    offset from comfortTemperature."""
    sent: list = []
    rc = _room_controller_v2(
        sent,
        OperatingMode.AUTO_HEAT,
        ActiveMode.COMFORT,
        comfortTemperature=21.0,
    )
    rc.set_temperature(temperature=22.0)
    assert sent == ["setComfortModeTemp/22.0"]
