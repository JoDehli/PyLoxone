# Message Center and repairs

The Miniserver's Message Center (System Status) reports problems such as offline devices, low batteries or failed updates. The integration shows them as a sensor and as repair issues.

## Message Center (System Status)

The Loxone Miniserver keeps a Message Center (shown as **System Status** in the Loxone app). It lists problems such as offline devices, low batteries, missing internet access or failed updates. The integration brings these messages into Home Assistant in two ways.

### The Message Center sensor

For each Message Center in your Loxone configuration, the integration creates a diagnostic sensor on the Miniserver device. Its entity id comes from the Loxone name, for example `sensor.system_status`. When the Miniserver reports a change, the integration fetches the current entries straight away.

- **State**: the highest severity among the active entries:

  | State | Meaning |
  |---|---|
  | `0` | No active messages |
  | `1` | Info |
  | `2` | Warning |
  | `3` | Error |
  | `4` | Critical |

- **`status` attribute**: the number of active entries for each severity, e.g. `{2: 3, 3: 1}` means three warnings and one error.

#### Example: message templates

A template sensor that turns the numeric state into readable text:

```yaml
template:
  - sensor:
      - name: Loxone System Status Text
        state: >-
          {% set level = states('sensor.system_status') | int(0) %}
          {{ {0: 'OK', 1: 'Info', 2: 'Warning', 3: 'Error', 4: 'Critical'}.get(level, 'Unknown') }}
```

A Markdown card that shows the entry counts and lists every active Loxone issue. It uses the `status` attribute and the `issues()` template function:

```yaml
type: markdown
title: Loxone System Status
content: >-
  {% set counts = state_attr('sensor.system_status', 'status') or {} %}
  **{{ counts.get(4, 0) }}** critical, **{{ counts.get(3, 0) }}** errors, **{{ counts.get(2, 0) }}** warnings

  {% for key, item in issues().items() if key[0] == 'loxone' %}
  - **{{ item.translation_placeholders.title }}**{% if item.translation_placeholders.name %}: {{ item.translation_placeholders.name }}{% endif %} ({{ item.severity }})
  {% else %}
  No active Loxone issues.
  {% endfor %}
```

### Repairs

Each active Message Center entry also appears as a repair issue under **Settings → System → Repairs**, next to the repairs from any other integration. Each issue shows:

- the Loxone title and the affected device;
- the description and the time the problem occurred;
- a link to the affected Home Assistant entity, when there is one;
- a **Learn more** link to the Loxone help page, when Loxone provides one.

Loxone severities map to Home Assistant repair severities as follows: Info and Warning → `warning`, Error → `error`, Critical → `critical`. You can't fix these issues from Home Assistant. When an entry is resolved or acknowledged in Loxone, the repair issue is removed automatically.

#### Example: automation for new repair issues

To do more than show the repair, react to the `repairs_issue_registry_updated` event. This example automation reads the new repair issue and creates a persistent notification for it:

```yaml
alias: Notify on New Loxone Repair Issue
description: Sends a notification whenever a new repair issue is registered.
triggers:
  - event_type: repairs_issue_registry_updated
    trigger: event
    event_data:
      action: create
      domain: loxone
conditions: []
actions:
  - variables:
      title: >-
        {% set issue_item = issue(trigger.event.data.domain,
        trigger.event.data.issue_id) %}{{
        issue_item.translation_placeholders.title }}{% if
        issue_item.translation_placeholders.name %}: {{
        issue_item.translation_placeholders.name }}{% endif %}
      message: >-
        {% set issue_item = issue(trigger.event.data.domain,
        trigger.event.data.issue_id) %}{{
        issue_item.translation_placeholders.description }}
      help_link: >-
        {% set issue_item = issue(trigger.event.data.domain,
        trigger.event.data.issue_id) %}{% if issue_item.learn_more_url %}
        [Loxone Help]({{ issue_item.learn_more_url }}){% endif %}
  - data:
      title: '{{ title }}'
      message: |-
        {{ message }}
        {{ help_link }}
      data:
        notification_id: '{{ trigger.event.data.issue_id }}'
    action: notify.persistent_notification
```

## Blueprints

The repository ships an automation blueprint that runs your own actions for new repair issues. See the [Blueprints](blueprints.md) page for import instructions.

#### Blueprint: run your own actions for new repair issues

The repository includes an automation blueprint, [`blueprints/loxone_repair_issue.yaml`](https://github.com/JoDehli/PyLoxone/blob/master/blueprints/loxone_repair_issue.yaml). It triggers on every new Loxone repair issue and runs the actions you choose, such as a mobile notification, a TTS announcement or flashing a light. You can also set a minimum severity so that only errors or critical issues run your actions.

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FJoDehli%2FPyLoxone%2Fblob%2Fmaster%2Fblueprints%2Floxone_repair_issue.yaml)

You can also import it manually: go to **Settings → Automations & Scenes → Blueprints → Import Blueprint** and paste this URL:

```
https://github.com/JoDehli/PyLoxone/blob/master/blueprints/loxone_repair_issue.yaml
```

Your actions can use these variables in templates:

| Variable | Content |
|---|---|
| `issue_id` | Unique id of the Message Center entry |
| `issue_title` | Title, plus the affected device name when known |
| `issue_message` | Description, including when the problem occurred |
| `issue_help_url` | Link to the Loxone help page (may be empty) |
| `issue_severity` | `warning`, `error` or `critical` |
| `issue_entry` | The raw Message Center entry from the Miniserver |

For example, to send a notification to your phone:

```yaml
action: notify.mobile_app_my_phone
data:
  title: "{{ issue_title }}"
  message: "{{ issue_message }}"
  data:
    url: "{{ issue_help_url }}"
```
