"""stop_cover against the Loxone structure file spec.

- Gate: the spec (pages 67-68) lists an unversioned ``stop`` command
  ("stops a moving gate"). The old heuristic sent ``open``/``close``
  depending on the movement direction - that parks the gate at the
  opposite end position instead of stopping in between.
- Window: the spec (page 146 f) lists an explicit ``stop`` command
  (since Miniserver 11.3); before that only the jog-off heuristic
  ``open``/``close`` + ``off`` exists. The heuristic below keeps
  sending ``fullopen``/``fullclose`` for pre-11.3 structures, but any
  structure that carries a ``targetPosition`` state is treated as
  MS >= 11.3 and gets the real stop.
- Jalousie already sends ``stop`` (regression guard).
"""

from __future__ import annotations

from types import SimpleNamespace

from custom_components.loxone.cover import LoxoneGate, LoxoneJalousie, LoxoneWindow
from custom_components.loxone.const import SENDDOMAIN


def _entity(cls, **attrs):
    """Build a cover entity without full setup; events are captured."""
    entity = cls.__new__(cls)
    sent: list = []
    entity.hass = SimpleNamespace(
        bus=SimpleNamespace(fire=lambda domain, data: sent.append((domain, data["value"])))
    )
    entity.uuidAction = "cover-uuid"
    entity.schedule_update_ha_state = lambda: None
    for key, val in attrs.items():
        setattr(entity, key, val)
    return entity, sent


def _fired(sent) -> list:
    return [value for domain, value in sent if domain == SENDDOMAIN]


# --- Gate -----------------------------------------------------------------

def test_gate_stop_while_closing_sends_stop():
    gate, sent = _entity(
        LoxoneGate, _is_closing=True, _is_opening=False, _position=40.0
    )
    gate.stop_cover()
    assert _fired(sent) == ["stop"]


def test_gate_stop_while_opening_sends_stop():
    gate, sent = _entity(
        LoxoneGate, _is_closing=False, _is_opening=True, _position=60.0
    )
    gate.stop_cover()
    assert _fired(sent) == ["stop"]


def test_gate_stop_without_direction_sends_stop():
    """Spec 'stop' is unversioned and always available - even when the
    movement flags were not (yet) updated by an event."""
    gate, sent = _entity(LoxoneGate, _is_closing=False, _is_opening=False)
    gate.stop_cover()
    assert _fired(sent) == ["stop"]


# --- Window ---------------------------------------------------------------

def _window_states(*keys) -> dict:
    return {key: f"uuid-{key}" for key in keys}


def test_window_stop_sends_stop_when_target_position_state_exists():
    """A targetPosition state means MS >= 11.3 -> the 'stop' command is
    available and must be used instead of the fullopen/fullclose heuristic."""
    window, sent = _entity(
        LoxoneWindow,
        _direction=1,
        _target_position=None,
        states=_window_states("position", "direction", "targetPosition"),
    )
    window.stop_cover()
    assert _fired(sent) == ["stop"]


def test_window_stop_sends_stop_even_without_direction_event():
    window, sent = _entity(
        LoxoneWindow,
        _direction=0,
        _target_position=None,
        states=_window_states("position", "direction", "targetPosition"),
    )
    window.stop_cover()
    assert _fired(sent) == ["stop"]


def test_window_stop_keeps_heuristic_fallback_without_target_position():
    """Pre-11.3 structure (no targetPosition state): the direction heuristic
    stays as the last resort."""
    window, sent = _entity(
        LoxoneWindow,
        _direction=-1,
        states=_window_states("position", "direction"),
    )
    window.stop_cover()
    assert _fired(sent) == ["fullopen"]

    window, sent = _entity(
        LoxoneWindow,
        _direction=1,
        states=_window_states("position", "direction"),
    )
    window.stop_cover()
    assert _fired(sent) == ["fullclose"]


# --- Jalousie (regression guard) ------------------------------------------

def test_jalousie_stop_sends_stop():
    jalousie, sent = _entity(LoxoneJalousie)
    jalousie.stop_cover()
    assert _fired(sent) == ["stop"]


def test_jalousie_stop_tilt_sends_stop():
    jalousie, sent = _entity(LoxoneJalousie)
    jalousie.stop_cover_tilt()
    assert _fired(sent) == ["stop"]
