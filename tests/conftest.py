"""Shared fixtures for the Loxone integration test tree.

``enable_custom_integrations`` is re-defined here (not the phcc-studio
fixture) so it also re-roots ``custom_components`` at the repo's own
``custom_components/`` directory. Phcc's stock fixture only clears the
loader integration cache, and pins ``custom_components.__path__`` at
phcc's testing_config directory, which would make
``custom_components.loxone`` un-importable in tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def enable_custom_integrations(hass):
    """Re-points ``custom_components`` at the repo's ``custom_components/`` and
    clears the loader integration cache.
    """
    import custom_components

    from homeassistant import loader

    original = list(custom_components.__path__)
    custom_components.__path__ = [str(REPO_ROOT / "custom_components")]
    hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
    yield
    custom_components.__path__ = original
