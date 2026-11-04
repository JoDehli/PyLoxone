"""Real HA setup/unload boundaries for the existing minimum and native cameras."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from homeassistant.const import Platform
from homeassistant import const as ha_const

from custom_components.loxone import compat
from custom_components.loxone.const import DOMAIN


def test_matrix_target_selects_the_expected_camera_capability():
    expected = (ha_const.MAJOR_VERSION, ha_const.MINOR_VERSION) >= (2026, 11)
    assert compat.supports_intercom() is expected
    assert (Platform.CAMERA in compat.entry_platforms()) is expected


def test_old_versions_do_not_import_native_camera_dependencies(monkeypatch):
    monkeypatch.setattr(compat, "MAJOR_VERSION", 2025)
    monkeypatch.setattr(compat, "MINOR_VERSION", 2)
    imported = Mock(side_effect=AssertionError("Old HA must not import the native camera API"))
    monkeypatch.setattr(compat, "import_module", imported)
    assert not compat.supports_intercom()
    assert Platform.CAMERA not in compat.entry_platforms()
    imported.assert_not_called()


def test_missing_camera_dependency_does_not_block_existing_platforms(monkeypatch):
    monkeypatch.setattr(compat, "MAJOR_VERSION", 2026)
    monkeypatch.setattr(compat, "MINOR_VERSION", 11)
    monkeypatch.setattr(compat, "import_module", Mock(side_effect=ModuleNotFoundError("Optional camera dependency")))
    platforms = compat.entry_platforms()
    assert Platform.CAMERA not in platforms
    assert Platform.SENSOR in platforms
    assert Platform.SWITCH in platforms


@pytest.mark.parametrize("missing", ["CameraEntityCapabilities", "WebRTCAnswer", "WebRTCCandidate"])
def test_missing_required_api_disables_only_native_camera(monkeypatch, missing):
    monkeypatch.setattr(compat, "MAJOR_VERSION", 2026)
    monkeypatch.setattr(compat, "MINOR_VERSION", 11)
    exports = {
        "CameraEntityCapabilities": lambda **kwargs: SimpleNamespace(**kwargs),
        "WebRTCAnswer": object,
        "WebRTCClientConfiguration": object,
        "WebRTCCandidate": object,
        "WebRTCError": object,
    }
    exports.pop(missing)
    monkeypatch.setattr(compat, "import_module", lambda _: SimpleNamespace(**exports))
    platforms = compat.entry_platforms()
    assert Platform.CAMERA not in platforms
    assert Platform.SWITCH in platforms
    assert Platform.SENSOR in platforms


@pytest.mark.parametrize("with_intercom", [False, True])
@pytest.mark.parametrize("stored_token", [False, True])
async def test_existing_entries_setup_reload_and_unload_without_token_migration(
    hass,
    mock_connection,
    mock_entry,
    enable_custom_integrations,
    with_intercom,
    stored_token,
    caplog,
    monkeypatch,
):
    controls = mock_connection.structure_file["controls"]
    if not with_intercom:
        mock_connection.structure_file["controls"] = {
            uuid: control for uuid, control in controls.items() if control.get("type") != "IntercomV2"
        }
    mock_entry.add_to_hass(hass)
    if stored_token:
        auth = {
            "client_id": "11111111-1111-4111-8111-111111111111",
            "username": "test-user",
            "permission": 0,
            "token": "stored-intercom-token",
            "valid_until": 999999999,
        }
        hass.config_entries.async_update_entry(mock_entry, data={"intercom_auth": auth})
    original_data = deepcopy(dict(mock_entry.data))
    # Compatibility setup must never try to authenticate to actual hardware.
    mock_connection.async_intercom_token = Mock(side_effect=AssertionError("No camera has been opened"))
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_entry.data == original_data
    assert mock_entry.entry_id in hass.data[DOMAIN]
    if not compat.supports_intercom():
        assert hass.data[DOMAIN][mock_entry.entry_id].intercom_tokens is None
        assert not any(state.entity_id.startswith("camera.") for state in hass.states.async_all())
        if with_intercom:
            assert "require Home Assistant 2026.11" in caplog.text
    assert await hass.config_entries.async_reload(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_entry.data == original_data
    assert await hass.config_entries.async_unload(mock_entry.entry_id)
    await hass.async_block_till_done()
    mock_connection.async_intercom_token.assert_not_called()
