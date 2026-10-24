"""The "Notify on New Loxone Repair Issue" automation from the PR description.

Creating a Loxone message center issue must fire
``repairs_issue_registry_updated`` and produce a persistent notification.
Manual runs of the automation (no event data) must not raise.
"""

from __future__ import annotations

from homeassistant.components import automation
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_mock_service

AUTOMATION_ENTITY_ID = "automation.notify_on_new_loxone_repair_issue"

AUTOMATION_CONFIG = {
    "id": "notify_on_new_loxone_repair_issue",
    "alias": "Notify on New Loxone Repair Issue",
    "description": "Sends a notification whenever a new repair issue is registered.",
    "triggers": [
        {
            "trigger": "event",
            "event_type": "repairs_issue_registry_updated",
            "event_data": {"action": "create", "domain": "loxone"},
        }
    ],
    "conditions": [],
    "actions": [
        {
            "variables": {
                "issue_domain": "{{ trigger.event.data.domain if trigger is defined and trigger.event is defined else '' }}",
                "issue_id": "{{ trigger.event.data.issue_id if trigger is defined and trigger.event is defined else '' }}",
            }
        },
        {
            "if": [
                {
                    "condition": "template",
                    "value_template": "{{ issue_domain == 'loxone' and issue_id != '' }}",
                }
            ],
            "then": [
                {
                    "data": {
                        "title": (
                            "{% set issue_item = issue(issue_domain, issue_id) %}"
                            "{{ issue_item.translation_placeholders.title }}"
                            "{% if issue_item.translation_placeholders.name %}: "
                            "{{ issue_item.translation_placeholders.name }}{% endif %}"
                        ),
                        "message": (
                            "{% set issue_item = issue(issue_domain, issue_id) %}"
                            "{{ issue_item.translation_placeholders.description }}"
                            "{% if issue_item.learn_more_url %}[Loxone Help]"
                            "({{ issue_item.learn_more_url }}){% endif %}"
                        ),
                        "data": {"notification_id": "{{ issue_id }}"},
                    },
                    "action": "notify.persistent_notification",
                }
            ],
        },
    ],
    "mode": "parallel",
    "max": 30,
}


async def _setup_automation(hass):
    assert await async_setup_component(
        hass, automation.DOMAIN, {automation.DOMAIN: [AUTOMATION_CONFIG]}
    )
    await hass.async_block_till_done()


def _create_issue(hass, domain: str, issue_id: str) -> None:
    ir.async_create_issue(
        hass,
        domain,
        issue_id,
        is_fixable=False,
        is_persistent=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="loxone_device_status",
        translation_placeholders={
            "name": "Stromzähler",
            "message_name": "Stromzähler",
            "title": "No internet",
            "description": "The Miniserver has no internet access.",
        },
        learn_more_url="https://www.loxone.com/help",
    )


async def test_new_loxone_issue_sends_notification(hass):
    notify_calls = async_mock_service(hass, "notify", "persistent_notification")
    await _setup_automation(hass)

    _create_issue(hass, "loxone", "entry-uuid-1")
    await hass.async_block_till_done()

    assert len(notify_calls) == 1
    call = notify_calls[0]
    assert call.data["title"] == "No internet: Stromzähler"
    assert "The Miniserver has no internet access." in call.data["message"]
    assert "[Loxone Help](https://www.loxone.com/help)" in call.data["message"]
    assert call.data["data"]["notification_id"] == "entry-uuid-1"


async def test_issue_from_other_domain_sends_no_notification(hass):
    notify_calls = async_mock_service(hass, "notify", "persistent_notification")
    await _setup_automation(hass)

    _create_issue(hass, "other_integration", "other-issue")
    await hass.async_block_till_done()

    assert notify_calls == []


async def test_manual_run_without_event_does_not_error(hass):
    notify_calls = async_mock_service(hass, "notify", "persistent_notification")
    await _setup_automation(hass)

    await hass.services.async_call(
        automation.DOMAIN,
        automation.SERVICE_TRIGGER,
        {"entity_id": AUTOMATION_ENTITY_ID, "skip_condition": True},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert notify_calls == []
