# Supported devices

This page lists the Loxone control types and the Home Assistant entities they become.

| Status | Meaning |
|---|---|
| ✅ Supported | Works as described by the Loxone documentation |
| 🟡 Partial | Works for the common use cases; some functions are missing (see Notes) |
| ❌ Not supported | No entity is created |

If your control is missing or only partly supported, please open a [feature request](https://github.com/JoDehli/PyLoxone/issues).

## Lighting

| Loxone control | Home Assistant | Status | Notes |
|---|---|---|---|
| `LightControllerV2` | `light`, `switch` | 🟡 Partial | Moods are exposed as light effects, plus master brightness. Sub-controls (dimmers, color pickers, switches) are created but **disabled by default**. Favorite and additional moods are not used. |
| `Dimmer`, `EIBDimmer` | `light` | ✅ Supported | |
| `ColorPickerV2` | `light` | 🟡 Partial | HSV and color temperature work as a sub-control. Sequences and favorites are missing. The old `ColorPicker` is not supported. |
| `LightController` (V1) | – | ❌ Not supported | |

## Blinds, windows and gates

| Loxone control | Home Assistant | Status | Notes |
|---|---|---|---|
| `Jalousie` | `cover` | ✅ Supported | |
| `Window` | `cover` | ✅ Supported | Includes the partially open (ventilation) position as the `loxone.window_slightly_open` service. |
| `Gate` | `cover` | ✅ Supported | |
| `WindowMonitor` | `binary_sensor`, `sensor` | ✅ Supported | |

## Switches and inputs

| Loxone control | Home Assistant | Status | Notes |
|---|---|---|---|
| `Switch` | `switch` | ✅ Supported | |
| `TimedSwitch` | `switch` | ✅ Supported | Turning on sends a pulse. |
| `Pushbutton` | `button` | ✅ Supported | Buttons are stateless, see [Known limitations](known-limitations.md). |
| `Slider` | `number` | ✅ Supported | |
| `ValueSelector` | `number` | ✅ Supported | |
| `TextInput` | `text`, `sensor` | ✅ Supported | |
| `Radio` | `select` | ✅ Supported | A locked radio block rejects selections. |

## Sensors

| Loxone control | Home Assistant | Status | Notes |
|---|---|---|---|
| `InfoOnlyAnalog` | `sensor` | ✅ Supported | Device class is detected from the unit, see the README. |
| `InfoOnlyDigital` | `binary_sensor` | ✅ Supported | Shows `unknown` until the first value arrives. |
| `InfoOnlyText` | `sensor` | ✅ Supported | Also text memory flags once "Use" is ticked in Loxone Config. |
| `TextState` | `sensor` | ✅ Supported | Read-only. State is limited to 255 characters; the full text is in the `text` attribute. |
| `Meter` | `sensor` | ✅ Supported | |
| `PresenceDetector` | `binary_sensor` | ✅ Supported | |
| `SmokeAlarm` | `binary_sensor` | ✅ Supported | Read-only; mute and confirm commands are not available. |

## Climate and ventilation

| Loxone control | Home Assistant | Status | Notes |
|---|---|---|---|
| `IRoomControllerV2` | `climate`, `switch`, `sensor` | 🟡 Partial | |
| `IRoomController` | `climate` | 🟡 Partial | Timer commands are missing. |
| `AcControl` | `climate` | 🟡 Partial | |
| `ClimateController`, `ClimateControllerUS` | `sensor` | 🟡 Partial | Only the heating/cooling demand is exposed. |
| `Ventilation` | `fan` | 🟡 Partial | Speed and presets plus presence, humidity and air-quality sensors. |

## Security, audio and intercom

| Loxone control | Home Assistant | Status | Notes |
|---|---|---|---|
| `Alarm` | `alarm_control_panel` | ✅ Supported | |
| `AudioZoneV2` | `media_player` | 🟡 Partial | Play, pause, next, previous and volume. Text-to-speech, favorites and presence are missing. |
| `Intercom` | `switch` | 🟡 Partial | Sub-controls appear as switches; the doorbell is not visible. |
| `IntercomV2` (Gen 2) | `binary_sensor`, `switch`, `button`, `sensor`, `text` | 🟡 Partial | Experimental. Ringing, bell mute, dismiss, outputs, voice replies and diagnostics. No camera or two-way audio yet. Secured Intercoms and outputs get no entities. Output buttons are untested on hardware. See the README section "Intercom Gen 2". |

## Other

| Loxone control | Home Assistant | Status | Notes |
|---|---|---|---|
| Message Center / System Status | `sensor`, repairs | ✅ Supported | See the README for templates and [blueprints](blueprints.md). |
| `AlarmChain`, `AlarmClock` | – | ❌ Not supported | |

## Energy

| Loxone control | Home Assistant | Status | Notes |
|---|---|---|---|
| `Wallbox2` (Wallbox Gen. 2) | `switch`, `select`, `number`, `binary_sensor` | ✅ Supported | Charging allow switch, charging mode, manual charging limit in kW, and connected / charging / load shedding / phase switching sensors. The kW range was verified on an 11 kW Wallbox Gen. 2 only. |

!!! tip "Unsupported control?"
    You can still send commands to any control with the websocket direct command service. See the README section "Advanced usage".
