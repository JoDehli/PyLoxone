"""Pytest configuration.

Tests assume homeassistant is installed via requirements.txt.

Setup (in a virtual environment to avoid system pip restrictions):
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    pytest tests/

This allows tests to import from custom_components.loxone normally.
"""
