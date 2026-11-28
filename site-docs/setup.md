# Setup and configuration

Add the recorder exclusion before you use the integration, then choose a local or cloud connection.

## Recorder configuration (important)

!!! warning "Add this before you use the integration"
    A Loxone system generates a few thousand events per day. Without this exclusion, Home Assistant records all of them and the database can grow very quickly. Add it to your `configuration.yaml`.

```yaml
recorder:
  exclude:
    event_types:
      - loxone_event
```

## Config for the gen2 miniserver
If you have the gen2 miniserver you should connect via local access. It is more reliable and faster than a cloud connection.

### Config for cloud connection
Please use this only in case local access is not possible.

Example:
- Miniserver Ip: https://dns.loxonecloud.com/123456789ABC
- Port: 443

Change 123456789ABC to your miniserver Serial Number.

## LightControllerV2 Sub-Controls

Each `LightControllerV2` in Loxone groups individual lighting outputs (dimmers, color pickers, switches) as sub-controls. These are registered in the Home Assistant entity registry but **disabled by default** to keep the UI clean.

To access individual light outputs:

1. Open **Settings → Devices & Services → Entities**
2. Filter by your LightControllerV2 device
3. Enable the sub-control entities you want to use (dimmer, color picker, etc.)

The integration option **"Generate sub-controls for LightControllerV2"** controls the default enabled state for newly created sub-control entities. When enabled, new sub-controls start as enabled; when disabled (the default), they start as disabled but remain visible in the entity registry for manual activation.

## Room controller: set temperature

These two integration options control what happens when a temperature is set on an `IRoomControllerV2` while it runs in an automatic mode, for example from the thermostat card or by voice ("Alexa, set the kitchen to 22 degrees").

- **Room controller: set temperature as**
    - **Comfort temperature adjustment** (default): adjusts the comfort temperature until the scheduled comfort period ends. This is the behaviour of earlier versions.
    - **Manual override (fixed setpoint)**: starts the Loxone manual override timer at the requested temperature, as the Loxone app does. The controller stays in its automatic mode and returns to the schedule when the timer ends. A new temperature while an override runs replaces it.
- **Room controller: manual override length in hours**: how long the manual override lasts. Default 4, minimum 0.5. The Miniserver needs an end time, so an override without one is not possible.

Manual operating modes and heat/cool ranges are not affected by these options. Voice assistants cannot pass a duration with the temperature, so voice commands always use the configured length.

## Log Configuration
Use the following settings if you paste a log into a issue:

```yaml
logger:
  default: warning
  logs:
    homeassistant: warning
    homeassistant.helpers: warning
    custom_components.loxone: debug
    pyloxone_api.connection: debug
```

The Loxone communication lives in the [pyloxone-api](https://github.com/JoDehli/pyloxone-api) package, which is a separate package (logger name `pyloxone_api`, not `custom_components.loxone`). Use `pyloxone_api.connection: debug` to see the login steps (`authwithtoken`, `gettoken`, ...).

## Token storage

After a successful login the integration saves the Loxone token in its config entry (`.storage/core.config_entries` in your Home Assistant config folder). The token is bound to the host, port and user of the entry. It is used for later starts so that no password login is needed. A token for a different host, port or user is ignored.

- After updating from an older version, the first start performs one password login. This is expected.
- Treat the `.storage` folder as sensitive: the stored token logs in as your Loxone user.
- Removing the integration tries to invalidate the token on the Miniserver. This only works while the connection is still open; otherwise the token expires on its own.
