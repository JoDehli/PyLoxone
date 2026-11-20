# UI and user-facing functionality

Everything a user can do in the Home Assistant UI, and where it is implemented.

## Config flow

Implemented in `custom_components/loxone/config_flow.py` (`LoxoneFlowHandler`). Strings live in `custom_components/loxone/translations/` (`en.json`, `de.json`, `cs.json`).

| Step | Purpose |
|---|---|
| `user` | Initial setup: host, port, user, password, *Verify the Miniserver TLS certificate*, *generate scenes*, scene delay, *Enable LightControllerV2 subcontrols by default* |
| `reauth_confirm` | Shown when the Miniserver rejects the stored credentials; asks for user and password again |
| `import` | Imports a legacy `loxone:` entry from `configuration.yaml` |

Each Miniserver is one config entry; adding the same Miniserver twice aborts with `already_configured`.

## Options

The options dialog (**Settings → Devices & Services → PyLoxone → Configure**) offers the same connection and generation settings as the setup step. The option keys are defined in `const.py` (`CONF_VERIFY_SSL`, `CONF_SCENE_GEN`, `CONF_SCENE_GEN_DELAY`, `CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN`).

## Services

Defined in `services.yaml`, texts in `translations/en.json`.

| Service | Purpose |
|---|---|
| `loxone.reload` | Reconnects to the Miniserver and refreshes all entities |
| `loxone.refresh_token` | Refreshes the authentication token immediately |
| `loxone.event_websocket_command` | Sends a command to a control by entity or UUID |
| `loxone.event_secured_websocket_command` | Same for secured controls (visualisation password) |
| `loxone.sync_areas` | Assigns Home Assistant areas from the Loxone rooms |
| `loxone.enable_sun_automation` / `disable_sun_automation` | Sun automation for Jalousie |
| `loxone.quick_shade` | Moves a Jalousie to the shade position |

## Repairs and diagnostics

- **Message Center:** problems reported by the Miniserver appear as repair issues (`loxone_status`, `loxone_device_status`) and in the Message Center sensor. The [blueprints](../blueprints.md) can react to new issues.
- **Diagnostics** (`diagnostics.py`) and **system health** (`system_health.py`) provide data for bug reports.

## Adding or changing UI text

1. Change the key in `translations/en.json` first; add the same key to `de.json` and `cs.json`.
2. Keep keys in `services.yaml` and the `services` block of `en.json` in sync.
3. Run `./scripts/test`; `hassfest` runs in CI and fails on missing or malformed translations.
