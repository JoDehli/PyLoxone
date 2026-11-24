"""Application, MsShortcut, SystemScheme (spec V17)."""

from __future__ import annotations

import pytest

from _controls import control, entity_id, structure_with

NAMED_TEXT = control("InfoOnlyText", "Weather Text", states=("text",), details={"format": "%s"})
APPLICATION = control(
    "Application", "Camera App", details={"url": "https://camera.local", "image": "img.png", "iconColor": "#FF0000"}
)
SHORTCUT = control(
    "MsShortcut",
    "Garage Miniserver",
    details={"trust": False, "serialNr": "504F11223344", "localUrl": "192.168.1.20", "remoteUrl": "dns.example"},
)
TRUST_SHORTCUT = control("MsShortcut", "Trust Miniserver", details={"trust": True, "serialNr": "504F99887766"})
SCHEME = control(
    "SystemScheme",
    "Heating Scheme",
    details={
        "imagePath": "scheme.png",
        "imageVersion": 3,
        "mainControl": NAMED_TEXT["uuidAction"],
        "controlReferences": [
            {"uuidAction": NAMED_TEXT["uuidAction"], "pos": {"x": 1, "y": 2}},
            {"uuidAction": "not-visible-uuid", "pos": {"x": 3, "y": 4}},
        ],
    },
)


@pytest.fixture
def loxapp3(loxapp3):
    return structure_with(loxapp3, NAMED_TEXT, APPLICATION, SHORTCUT, TRUST_SHORTCUT, SCHEME)


@pytest.fixture
async def setup(hass, mock_connection, mock_entry, setup_loxone_entry):
    await setup_loxone_entry(mock_entry)
    return mock_connection


async def test_application(hass, setup):
    current = hass.states.get(entity_id(hass, "sensor", APPLICATION["uuidAction"]))
    assert current.state == "https://camera.local"
    assert current.attributes["icon_color"] == "#FF0000"


async def test_ms_shortcut(hass, setup):
    current = hass.states.get(entity_id(hass, "sensor", SHORTCUT["uuidAction"]))
    assert current.state == "192.168.1.20"
    assert current.attributes["remote_url"] == "dns.example"
    assert current.attributes["trust"] is False

    trust = hass.states.get(entity_id(hass, "sensor", TRUST_SHORTCUT["uuidAction"]))
    assert trust.state == "504F99887766"
    assert trust.attributes["trust"] is True


async def test_system_scheme(hass, setup):
    current = hass.states.get(entity_id(hass, "sensor", SCHEME["uuidAction"]))
    assert current.state == "Weather Text"
    assert current.attributes["controls"] == ["Weather Text", "not-visible-uuid"]
    assert current.attributes["image_version"] == 3
