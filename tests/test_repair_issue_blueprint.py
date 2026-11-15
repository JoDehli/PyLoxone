"""The ``loxone_repair_issue`` automation blueprint shipped in ``blueprints/``.

A new Loxone repair issue must run the user's actions with the issue
details exposed as variables, honouring the minimum severity input.
"""

from __future__ import annotations

import pathlib
from unittest.mock import patch

from homeassistant.components import automation
from homeassistant.components.blueprint import models
from homeassistant.core import callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from homeassistant.util import yaml as yaml_util
from pytest_homeassistant_custom_component.common import async_mock_service

BLUEPRINT_PATH = "loxone_repair_issue.yaml"
BLUEPRINT_FILE = (
    pathlib.Path(__file__).parent.parent
    / "blueprints"
    / BLUEPRINT_PATH
)

ENTRY = {"entryUuid": "entry-uuid-1", "severity": 3, "title": "Device offline"}


@callback
def _load_blueprint(self, path):
    assert path == BLUEPRINT_PATH
    return models.Blueprint(
        yaml_util.load_yaml(BLUEPRINT_FILE),
        expected_domain=self.domain,
        path=path,
        schema=automation.config.AUTOMATION_BLUEPRINT_SCHEMA,
    )


async def _setup_automation(hass, min_severity: str = "warning"):
    with patch(
        "homeassistant.components.blueprint.models.DomainBlueprints._load_blueprint",
        _load_blueprint,
    ):
        assert await async_setup_component(
            hass,
            automation.DOMAIN,
            {
                automation.DOMAIN: {
                    "use_blueprint": {
                        "path": BLUEPRINT_PATH,
                        "input": {
                            "min_severity": min_severity,
                            "actions": [
                                {
                                    "action": "test.notify",
                                    "data": {
                                        "id": "{{ issue_id }}",
                                        "title": "{{ issue_title }}",
                                        "message": "{{ issue_message }}",
                                        "url": "{{ issue_help_url }}",
                                        "severity": "{{ issue_severity }}",
                                        "event_id": "{{ issue_entry.title }}",
                                    },
                                }
                            ],
                        },
                    }
                }
            },
        )
    await hass.async_block_till_done()


def _create_issue(
    hass,
    issue_id: str = "entry-uuid-1",
    domain: str = "loxone",
    severity: ir.IssueSeverity = ir.IssueSeverity.ERROR,
) -> None:
    ir.async_create_issue(
        hass,
        domain,
        issue_id,
        is_fixable=False,
        is_persistent=True,
        severity=severity,
        translation_key="loxone_device_status",
        translation_placeholders={
            "name": "Kitchen Light",
            "message_name": "Kitchen Light",
            "title": "Device offline",
            "description": "The device is not reachable.",
        },
        learn_more_url="https://www.loxone.com/help",
        data={"entry": ENTRY, "devices": []},
    )


async def test_blueprint_runs_actions_with_issue_variables(hass):
    calls = async_mock_service(hass, "test", "notify")
    await _setup_automation(hass)

    _create_issue(hass)
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data == {
        "id": "entry-uuid-1",
        "title": "Device offline: Kitchen Light",
        "message": "The device is not reachable.",
        "url": "https://www.loxone.com/help",
        "severity": "error",
        "event_id": "Device offline",
    }


async def test_blueprint_skips_issues_below_min_severity(hass):
    calls = async_mock_service(hass, "test", "notify")
    await _setup_automation(hass, min_severity="critical")

    _create_issue(hass, "warning-issue", severity=ir.IssueSeverity.WARNING)
    _create_issue(hass, "error-issue", severity=ir.IssueSeverity.ERROR)
    _create_issue(hass, "critical-issue", severity=ir.IssueSeverity.CRITICAL)
    await hass.async_block_till_done()

    assert [call.data["id"] for call in calls] == ["critical-issue"]


async def test_blueprint_ignores_other_domains(hass):
    calls = async_mock_service(hass, "test", "notify")
    await _setup_automation(hass)

    _create_issue(hass, "other-issue", domain="other_integration")
    await hass.async_block_till_done()

    assert calls == []
