"""The Miniserver is registered as a device that carries its real details.

Regression tests for a device card that showed the host/IP address as the
"MAC", a firmware version that was never refreshed and no serial number:
``MiniServer.async_update_device_registry`` was no longer called during setup.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.loxone.miniserver import MiniServer

SERIAL = "504F94AABBCC"
MAC = "50:4f:94:aa:bb:cc"


@pytest.fixture
def gen1_miniserver(monkeypatch, loxapp3):
    """A Gen 1 Miniserver named "Test Miniserver" on firmware 17.3.11.10.

    ``softwareVersion`` is what ``LoxoneConnection.open`` fills in from the
    ``apiKey`` response.
    """
    monkeypatch.setitem(loxapp3, "softwareVersion", [17, 3, 11, 10])
    monkeypatch.setitem(
        loxapp3,
        "msInfo",
        {**loxapp3["msInfo"], "msName": "Test Miniserver", "serialNr": SERIAL, "miniserverType": 0},
    )


def _miniserver_device(hass, entry, serial=SERIAL):
    """The Miniserver's device among the entry's devices (``async_get_device`` is deprecated)."""
    for device in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id):
        if ("loxone", serial) in device.identifiers:
            return device
    return None


async def _setup(hass, entry):
    """Set up an entry that is already known to ``hass``."""
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_device_carries_the_miniserver_details(
    hass, mock_connection, mock_entry, setup_loxone_entry, gen1_miniserver
):
    await setup_loxone_entry(mock_entry)

    device = _miniserver_device(hass, mock_entry)
    assert device is not None
    assert device.name == "Test Miniserver"
    assert device.manufacturer == "Loxone"
    assert device.model == "Miniserver (Gen 1)"
    assert device.sw_version == "17.3.11.10"
    assert device.serial_number == SERIAL
    assert device.connections == {(dr.CONNECTION_NETWORK_MAC, MAC)}
    assert device.configuration_url == "http://miniserver.test:8080"


async def test_device_of_an_earlier_version_is_corrected(hass, mock_connection, mock_entry, gen1_miniserver):
    """What older versions left behind: firmware from back then and the IP as "MAC"."""
    mock_entry.add_to_hass(hass)
    stale = dr.async_get(hass).async_get_or_create(
        config_entry_id=mock_entry.entry_id,
        identifiers={("loxone", SERIAL)},
        connections={(dr.CONNECTION_NETWORK_MAC, "192.168.1.50")},
        name="Test Miniserver",
        manufacturer="Loxone",
        model="Miniserver (Gen 1)",
        sw_version="16.1.11.6",
    )

    await _setup(hass, mock_entry)

    device = _miniserver_device(hass, mock_entry)
    assert device.id == stale.id
    assert device.sw_version == "17.3.11.10"
    assert device.connections == {(dr.CONNECTION_NETWORK_MAC, MAC)}


async def test_serial_that_is_not_a_mac_gives_no_connection(hass, mock_connection, mock_entry, setup_loxone_entry):
    """The fixture's serial is ``TEST-SERIAL-0001``: shown as serial, not as MAC."""
    await setup_loxone_entry(mock_entry)

    device = _miniserver_device(hass, mock_entry, "TEST-SERIAL-0001")
    assert device is not None
    assert device.serial_number == "TEST-SERIAL-0001"
    assert device.connections == set()


async def test_unknown_firmware_keeps_the_known_version(hass, mock_connection, mock_entry, monkeypatch, loxapp3):
    monkeypatch.setitem(loxapp3, "softwareVersion", [])
    mock_entry.add_to_hass(hass)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=mock_entry.entry_id,
        identifiers={("loxone", "TEST-SERIAL-0001")},
        sw_version="17.3.11.10",
    )

    await _setup(hass, mock_entry)

    assert _miniserver_device(hass, mock_entry, "TEST-SERIAL-0001").sw_version == "17.3.11.10"


async def test_cloud_dns_host_gives_a_valid_configuration_url(
    hass, mock_connection, mock_entry, setup_loxone_entry, gen1_miniserver
):
    """The host may carry a scheme and a path (Cloud DNS); the URL was built as
    ``http://{host}:{port}``, which Home Assistant rejects for such a host."""
    entry = MockConfigEntry(
        domain="loxone",
        version=4,
        data={},
        options={**mock_entry.options, "host": f"https://dns.loxonecloud.com/{SERIAL}", "port": 443},
        unique_id=SERIAL,
    )

    await setup_loxone_entry(entry)

    assert entry.state is ConfigEntryState.LOADED
    assert _miniserver_device(hass, entry).configuration_url == f"https://dns.loxonecloud.com/{SERIAL}"


async def test_device_registry_problem_does_not_fail_the_setup(
    hass, mock_connection, mock_entry, setup_loxone_entry, monkeypatch
):
    def _reject(self):
        msg = "invalid configuration_url"
        raise ValueError(msg)

    monkeypatch.setattr(MiniServer, "async_update_device_registry", _reject)

    entry = await setup_loxone_entry(mock_entry)

    assert entry.state is ConfigEntryState.LOADED


@pytest.mark.parametrize(
    ("serial", "expected"),
    [
        ("504F94AABBCC", MAC),
        ("50:4F:94:AA:BB:CC", MAC),
        ("TEST-SERIAL-0001", None),
        ("GHIJKLMNOPQR", None),  # twelve characters, but not hex
        ("", None),
        (None, None),
    ],
)
def test_mac_address_from_serial(serial, expected):
    miniserver = MiniServer(None, {"msInfo": {"serialNr": serial}}, SimpleNamespace())
    assert miniserver.mac_address == expected


def test_mac_address_without_ms_info():
    assert MiniServer(None, {}, SimpleNamespace()).mac_address is None
