# Blueprints

This repository ships two Home Assistant blueprints for the Loxone integration. They live in [`blueprints/`](blueprints/):

| Blueprint | Type | File | Purpose |
|---|---|---|---|
| [Loxone Message Center repair issue](#loxone-message-center-repair-issue) | Automation | `blueprints/loxone_repair_issue.yaml` | Run your own actions when the Miniserver raises a new repair issue |
| [Loxone secured command](#loxone-secured-command) | Script | `blueprints/secured_command_input_helper.yaml` | Send a command to a secured Loxone control, asking for the visualisation password |

## Installing a blueprint

Blueprints must be placed in the folder that matches their type. Home Assistant rejects a blueprint that sits in the wrong folder with an error such as `Found incorrect blueprint type script, expected automation`.

Go to **Settings → Automations & Scenes → Blueprints → Import Blueprint** and paste the URL for the blueprint you want:

- Loxone Message Center repair issue (automation):

  ```
  https://github.com/JoDehli/PyLoxone/blob/master/blueprints/loxone_repair_issue.yaml
  ```

- Loxone secured command (script):

  ```
  https://github.com/JoDehli/PyLoxone/blob/master/blueprints/secured_command_input_helper.yaml
  ```

The import dialog places each blueprint in the correct folder for its type. After importing, the blueprint appears when you create a new automation or script from a blueprint.

> The secured command link only works after that file has been merged to `master`. Until then, it returns "not found".

---

## Loxone Message Center repair issue

File: [`blueprints/loxone_repair_issue.yaml`](blueprints/loxone_repair_issue.yaml)
Type: automation

### What it does

The Loxone integration reports problems from the Miniserver Message Center as repair issues (System Status). This blueprint runs whenever a **new** Loxone repair issue is created and then runs the actions you choose, for example:

- a mobile notification
- a TTS announcement
- flashing a light

### Trigger and conditions

- **Trigger:** the Home Assistant event `repairs_issue_registry_updated` with `action: create` and `domain: loxone`. Only newly created issues start the automation. Updates and removals are ignored.
- **Condition:** the issue severity must be at least the **Minimum severity** you chose.

### Inputs

| Input | Default | Description |
|---|---|---|
| Minimum severity | `warning` | Run the actions only for issues of this severity or higher. Options: Warning, Error, Critical. |
| Actions | — | The actions to run for each new issue. Required. |

### Variables for your actions

Use these variables in templates inside your actions:

| Variable | Content |
|---|---|
| `issue_id` | Unique id of the Message Center entry |
| `issue_title` | Title, plus the affected device name when known |
| `issue_message` | Description, including when the problem occurred |
| `issue_help_url` | Link to the Loxone help page (may be empty) |
| `issue_severity` | `warning`, `error` or `critical` |
| `issue_entry` | The raw Message Center entry sent by the Miniserver |

### Example action

A mobile notification for each new issue:

```yaml
action: notify.mobile_app_your_phone
data:
  title: "Loxone: {{ issue_title }}"
  message: "{{ issue_message }}"
  data:
    url: "{{ issue_help_url }}"
```

Replace `notify.mobile_app_your_phone` with your own notification service.

### Settings

- **Mode:** `queued`, with a maximum of 20 queued runs. If many issues arrive at once, they are processed one after another.

---

## Loxone secured command

File: [`blueprints/secured_command_input_helper.yaml`](blueprints/secured_command_input_helper.yaml)
Type: script

### What it does

Sends a command to a secured Loxone control, such as a gate, door or alarm that requires the visualisation password. The script does not store the password. Whoever runs the script enters the password each time.

### Steps the script performs

1. Checks that a code was entered. If the code is empty or only spaces, the script stops with the error "No code was provided" and sends nothing.
2. Calls the action `loxone.event_secured_websocket_command` with:
   - `device`: the selected Loxone entity
   - `value`: the command, as a string
   - `code`: the password, with surrounding spaces removed

### Inputs

| Input | Default | Description |
|---|---|---|
| Secured Loxone entity | — | The Loxone entity to control. Required. |
| Command | `pulse` | Text sent to the control, for example `pulse`, `on`, `off`, `open`, `close` or `delayedon/1`. |

### Field at run time

| Field | Type | Required | Description |
|---|---|---|---|
| Code | Password text | Yes | The visualisation password for the control. |

### Quick start: add it to the UI

1. Import the blueprint with the link above (**Settings → Automations & Scenes → Blueprints → Import Blueprint**).
2. Go to **Settings → Automations & Scenes → Scripts → Create script → Create from blueprint** and select **Loxone secured command**.
3. Choose the Loxone entity and enter the command (for example `delayedon/1`), then save.
4. Open the script and choose **Run script** (German UI: **Skript ausführen**). Enter the visualisation password when asked.

Once saved, the script is an entity (for example `script.loxone_secured_command`). You can run it from the Scripts list, from the script's menu, or from a dashboard button with a password helper (see below).

### Creating the script

1. Go to **Settings → Automations & Scenes → Scripts → Create script → Create from blueprint**.
2. Choose **Loxone secured command**.
3. Select the Loxone entity and enter the command.
4. Save. The script now appears under **Scripts** with its own entity id, such as `script.loxone_secured_command`.

### Running the script

- **From the scripts list or the script's menu:** choose **Run script** (German: **Ausführen** / **Skript ausführen**). Home Assistant asks for the code.
- **From a dashboard button:** a button cannot ask for the code when tapped. Use a password helper instead (see below).

### Dashboard button with a password helper

1. Create a **Text** helper in **Password** mode, for example `input_text.loxone_code`.
2. Add a **Button** card with this tap action, using your script's entity id:

   ```yaml
   type: button
   name: Alarmanlage delayedon/1
   tap_action:
     action: perform-action
     perform_action: script.loxone_secured_command
     data:
       command: delayedon/1
       code: "{{ states('input_text.loxone_code') }}"
   ```

3. Type the code into the helper before tapping the button.

The helper keeps its value until you change it. Anyone who can use the dashboard can then run the command, so only do this on a dashboard you trust.

> **Security note:** do not write the code directly into the button's YAML. The dashboard configuration is stored in plain text.

---

## Troubleshooting

| Problem | Cause and fix |
|---|---|
| `Invalid blueprint: Found incorrect blueprint type script, expected automation` | The script blueprint is in the automation folder. Move it to `config/blueprints/script/`. |
| "No code was provided" | The code field was empty or only spaces. Enter the password again. |
| The button does nothing | Check that the script entity id in the button matches your script, and that the helper contains the code. |
