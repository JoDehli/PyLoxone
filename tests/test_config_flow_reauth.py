"""Rejected credentials start a reauth flow instead of a dead entry."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from custom_components.loxone import config_flow
from custom_components.loxone.config_flow import LoxoneFlowHandler


@pytest.fixture(autouse=True)
def _real_conf_keys(monkeypatch):
    """Use HA's real ``CONF_*`` values when ``homeassistant`` is stubbed."""
    for name, value in (
        ("CONF_HOST", "host"),
        ("CONF_PORT", "port"),
        ("CONF_USERNAME", "username"),
        ("CONF_PASSWORD", "password"),
    ):
        if not isinstance(getattr(config_flow, name), str):
            monkeypatch.setattr(config_flow, name, value)


def _flow():
    entry = SimpleNamespace(
        options={"host": "10.0.0.2", "port": 80, "username": "old", "password": "x"},
        data={"token": "old-token", "hash_alg": "SHA256", "valid_until": 1},
    )
    flow = LoxoneFlowHandler.__new__(LoxoneFlowHandler)
    flow._get_reauth_entry = lambda: entry
    flow.add_suggested_values_to_schema = lambda schema, values: (schema, values)
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}
    flow.async_update_reload_and_abort = lambda entry, **kwargs: {
        "type": "abort",
        "reason": "reauth_successful",
        **kwargs,
    }
    return flow


def test_reauth_shows_form_with_current_username():
    result = asyncio.run(_flow().async_step_reauth({}))
    assert result["type"] == "form"
    assert result["step_id"] == "reauth_confirm"
    assert result["data_schema"][1] == {"username": "old"}


def test_reauth_updates_credentials_and_clears_token():
    result = asyncio.run(
        _flow().async_step_reauth_confirm({"username": "new", "password": "pw"})
    )
    assert result["reason"] == "reauth_successful"
    assert result["options"] == {
        "host": "10.0.0.2",
        "port": 80,
        "username": "new",
        "password": "pw",
    }
    assert result["data_updates"] == {"token": "", "hash_alg": "", "valid_until": ""}


def test_reauth_rejects_non_latin1_password():
    result = asyncio.run(
        _flow().async_step_reauth_confirm({"username": "new", "password": "€"})
    )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_credentials_encoding"}
