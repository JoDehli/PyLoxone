"""Repair issues of the Loxone integration.

* ``public_key_changed``: the Miniserver presented another public key than
  the one pinned on the first connection (pyloxone-api raises
  ``LoxonePublicKeyMismatchError``). Fixable: after the user confirmed the
  change, the pin is dropped and the next connection pins the new key.
* ``https_available``: the Miniserver supports HTTPS/WSS (``httpsStatus`` 1
  in its apiKey reply), but the entry connects over plain HTTP.
* ``certificate_expired``: the Miniserver's TLS certificate has expired
  (``httpsStatus`` 2).
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN

ISSUE_PUBLIC_KEY_CHANGED = "public_key_changed"
ISSUE_HTTPS_AVAILABLE = "https_available"
ISSUE_CERTIFICATE_EXPIRED = "certificate_expired"

HTTPS_STATUS_AVAILABLE = 1
HTTPS_STATUS_EXPIRED = 2


def issue_id(kind: str, entry: ConfigEntry) -> str:
    return f"{kind}_{entry.entry_id}"


def _placeholders(entry: ConfigEntry, **extra: str) -> dict[str, str]:
    return {"title": entry.title, **extra}


def create_public_key_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id(ISSUE_PUBLIC_KEY_CHANGED, entry),
        is_fixable=True,
        is_persistent=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key=ISSUE_PUBLIC_KEY_CHANGED,
        translation_placeholders=_placeholders(entry),
        data={"entry_id": entry.entry_id},
    )


def delete_public_key_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
    ir.async_delete_issue(hass, DOMAIN, issue_id(ISSUE_PUBLIC_KEY_CHANGED, entry))


def update_https_issues(hass: HomeAssistant, entry: ConfigEntry, api: Any) -> None:
    """Raise or clear the HTTPS hints from the connection's ``httpsStatus``."""
    status = getattr(api, "https_status", None)
    scheme = getattr(api, "scheme", None)
    hostname = getattr(api, "tls_hostname", None)

    available_id = issue_id(ISSUE_HTTPS_AVAILABLE, entry)
    if status == HTTPS_STATUS_AVAILABLE and scheme == "http":
        ir.async_create_issue(
            hass,
            DOMAIN,
            available_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_HTTPS_AVAILABLE,
            translation_placeholders=_placeholders(entry, hostname=hostname or "-"),
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, available_id)

    expired_id = issue_id(ISSUE_CERTIFICATE_EXPIRED, entry)
    if status == HTTPS_STATUS_EXPIRED:
        ir.async_create_issue(
            hass,
            DOMAIN,
            expired_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_CERTIFICATE_EXPIRED,
            translation_placeholders=_placeholders(entry),
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, expired_id)


def delete_all_issues(hass: HomeAssistant, entry: ConfigEntry) -> None:
    for kind in (ISSUE_PUBLIC_KEY_CHANGED, ISSUE_HTTPS_AVAILABLE, ISSUE_CERTIFICATE_EXPIRED):
        ir.async_delete_issue(hass, DOMAIN, issue_id(kind, entry))
