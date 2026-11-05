"""Import shared test helpers from the single installed HA test plugin."""

from importlib.util import find_spec

if find_spec("pytest_homeassistant") is not None:
    from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed
else:
    from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

__all__ = ["MockConfigEntry", "async_fire_time_changed"]
