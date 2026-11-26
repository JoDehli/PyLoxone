# Intercom Gen 2

Support for native local `IntercomV2` devices.

## Entities

Native local `IntercomV2` devices are discovered automatically. All entities of
one Intercom are grouped on one device below the Miniserver:

| Entity | Purpose |
| --- | --- |
| Ringing binary sensor | The bell's ringing state, for dashboards and automations |
| Mute doorbell switch | Mutes/unmutes the Loxone bell; the state follows the Miniserver's feedback |
| Dismiss ringing button | Stops the bell without starting a conversation |
| Output buttons | Pulse the output subcontrols Loxone exposes, such as a door release |
| Play reply buttons | Play the voice replies configured in Loxone; each button shows its text as the `message` attribute |
| Online binary sensor | Whether the Intercom device is ready |
| Device status sensor | `unknown`, `online`, `rebooting` or `initializing` |
| Firmware sensor | Diagnostic entity, disabled by default; the firmware is also shown in the device information |

Only the states and outputs Loxone exposes to the configured account become
entities. An output pulse does not report whether a door is actually unlocked.
PIN-protected (secured) Intercoms and outputs get no switch or button; use the
`loxone.event_secured_websocket_command` action with the code instead. While a
control is locked in Loxone, its switch and buttons are unavailable.

For a ringing notification, trigger on the Ringing sensor changing from `off` to
`on`. Repeated presses while it is still ringing are not separate events.

Not supported yet: the camera with two-way audio, Intercoms of a trust member
and custom `IntercomV2` devices. This part was written without access to an
Intercom Gen 2; the output buttons in particular are untested on hardware.
Based on the work of jpulik in [#542](https://github.com/JoDehli/PyLoxone/pull/542).
