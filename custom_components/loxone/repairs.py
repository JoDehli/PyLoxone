"""Repair flows of the Loxone integration (see ``issues.py``)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .issues import ISSUE_PUBLIC_KEY_CHANGED


class PublicKeyChangedRepairFlow(RepairsFlow):
    """Accept the Miniserver's new public key.

    Drops the pinned key and reloads the entry; the next connection pins
    the key the Miniserver presents then.
    """

    def __init__(self, entry_id: str) -> None:
        self.entry_id = entry_id

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            entry = self.hass.config_entries.async_get_entry(self.entry_id)
            if entry is not None:
                data = dict(entry.data)
                data.pop("public_key_pin", None)
                self.hass.config_entries.async_update_entry(entry, data=data)
                self.hass.config_entries.async_schedule_reload(entry.entry_id)
            return self.async_create_entry(data={})
        return self.async_show_form(step_id="confirm", data_schema=vol.Schema({}))


async def async_create_fix_flow(hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None) -> RepairsFlow:
    if issue_id.startswith(ISSUE_PUBLIC_KEY_CHANGED) and data and "entry_id" in data:
        return PublicKeyChangedRepairFlow(str(data["entry_id"]))
    msg = f"Unknown repair issue {issue_id}"
    raise ValueError(msg)
