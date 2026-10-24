"""Pytest configuration.

Tests assume homeassistant is installed via requirements.txt.

Setup (in a virtual environment to avoid system pip restrictions). Note
that the tests get their OWN virtualenv — ``.venv`` is reserved for the
local Home Assistant runtime used for live Miniserver tests. Just use
the wrapper, it creates the venv and installs everything:

    ./scripts/test -q

This allows tests to import from custom_components.loxone normally.
"""
