# Implemented control types

Current state of the Loxone control types from the [Loxone Structure File](https://www.loxone.com/wp-content/uploads/datasheets/StructureFile.pdf) in the integration: which file handles them and what is still missing. The user-facing summary is on [Supported devices](../supported-devices.md). All files are in `custom_components/loxone/`.

Status: **implemented** = covers the Structure File spec, **partial** = works, with the gaps listed, **missing** = no entity.

## Lighting

| Control type | File | Status | Open gaps |
|---|---|---|---|
| `LightControllerV2` | `light.py`, `switch.py` | partial | Moods as effects, master brightness, on/off from moods and master value. `favoriteMoods` / `additionalMoods` unused; mood-maintenance commands missing |
| `Dimmer`, `EIBDimmer` | `light.py` | implemented | Cosmetic only: no min/max/step attributes |
| `ColorPickerV2` (also `ColorPicker`) | `light.py` (sub-control) | partial | HSV and color temperature work. Sequences and favorites missing; V1 `ColorPicker` unsupported |
| `LightController` | – | missing | |

## Blinds, windows, gates

| Control type | File | Status | Open gaps |
|---|---|---|---|
| `Jalousie` | `cover.py` | implemented | Commands `up`/`UpOff`, `down`/`DownOff`, `manualPosBlind`, `setAdjustingEndPos`, `endPosAdjustment` not used |
| `Window` | `cover.py` | implemented | Commands `open/on`, `open/off`, `close/on`, `close/off` not used. `slightlyOpen/` is exposed as the service `loxone.window_slightly_open`; `lockedReason` and the window type are read as attributes |
| `Gate` | `cover.py` | implemented | Commands `forceOpen`, `forceClose`, `PartiallyOpen`, `getState`, `stop` not used |
| `WindowMonitor` | `window_monitor.py` → `binary_sensor.py`, `sensor.py` | implemented | |

## Switches and inputs

| Control type | File | Status | Open gaps |
|---|---|---|---|
| `Switch` | `switch.py` | implemented | States `lockedOn`, `jLocked` not used |
| `TimedSwitch` | `switch.py` | implemented | `turn_on` only sends `pulse`; the permanent `on` command is missing |
| `Pushbutton` | `button.py` | implemented | Only `pulse`; `on` / `off` missing |
| `Slider` | `number.py` | implemented | States `error`, `jLocked` not used |
| `ValueSelector` | `number.py` | implemented | States `increaseOnly`, `jLocked` not used |
| `TextInput` | `sensor.py`, `text.py` | implemented | `jLocked` and limits not used |
| `Radio` | `select.py` | implemented | `jLocked` is decoded and a locked block rejects selections. Commands `next` / `prev` missing |

## Sensors

| Control type | File | Status | Open gaps |
|---|---|---|---|
| `InfoOnlyAnalog` | `sensor.py` | implemented | State `error` not used. The JSON sometimes uses the type name `analog` |
| `InfoOnlyDigital` | `binary_sensor.py` | implemented | `text` / `image` / `color` not used. The JSON sometimes uses the type name `digital`. Reports `unknown` until the first event |
| `InfoOnlyText` | `sensor.py` | implemented | `details.format` ignored; no 255-character cap |
| `TextState` | `sensor.py` | implemented | Read-only. State capped at 255 characters, full text in the `text` attribute. `textAndIcon` is treated as plain text and not yet verified against a live event |
| `Meter` | `sensor.py` | implemented | `totalDay` / `totalWeek` / …, `displayType`, `powerName`, `storageMax` and the `reset` command missing |
| `PresenceDetector` | `binary_sensor.py` | implemented | Commands `{value}`, `time/{value}`, `presence/{value}`, `deactivate/{value}` missing |
| `SmokeAlarm` | `binary_sensor.py` | implemented | Alarm state from `level`. Commands `mute`, `confirm`, `servicemode/{number}`, `startDrill` missing |

## Climate and ventilation

| Control type | File | Status | Open gaps |
|---|---|---|---|
| `IRoomControllerV2` | `climate.py`, `switch.py`, `sensor.py` | partial | `setComfortModeTemp` sends the offset. `setecoplus*` commands are undocumented but accepted by the Miniserver |
| `IRoomController` | `climate.py` | partial | Timer commands, `stop` / `error` / `manualMode` missing; undocumented valve/prepare states to verify |
| `AcControl` | `climate.py` | partial | Direct state access, `minTemp` / `maxTemp` ignored, stray `setMode` on power-off; no real instance tested |
| `ClimateController`, `ClimateControllerUS` | `sensor.py` | partial | Only the request/demand relay. The mode numbering differs between the two types |
| `Ventilation` | `fan.py` | partial | Speed and presets plus presence, humidity and air-quality sub-sensors. `setMode/2..6` is undocumented and the preset ids are hardcoded |

## Energy

| Control type | File | Status | Open gaps |
|---|---|---|---|
| `Wallbox2` (Wallbox Gen. 2) | `wallbox2.py` → `switch.py`, `select.py`, `number.py`, `binary_sensor.py` | implemented | Commands `allow/on`, `allow/off`, `setmode/<id>`, `manualLimit/<kW>`. `min`/`max` are assumed to be kW and verified only on an 11 kW Wallbox Gen. 2 |

## Security, audio, intercom

| Control type | File | Status | Open gaps |
|---|---|---|---|
| `Alarm` | `alarm_control_panel.py` | implemented | |
| `AudioZoneV2` | `media_player.py` | partial | Transport only (play, pause, next, previous, volume, step; stop maps to pause). Missing: `tts`, favorites, presence/bluetooth, availability from `serverState`. Zones with `volumeModes: 2` get wrong absolute-volume commands |
| `Intercom` | `switch.py` | partial | V1 sub-controls as switches only. The doorbell (`bell` state) and `answer` are not visible; `securedDetails` unused |
| `IntercomV2` (Gen 2) | `intercom/` → `binary_sensor.py`, `switch.py`, `button`, `sensor`, `text` | partial | No camera or two-way audio. Intercoms of a trust member and custom devices are skipped. Secured Intercoms and outputs get no entities. The output buttons send `pulse`, which is not documented for Intercom subcontrols, and are untested on hardware |

## Not implemented

`AlarmChain`, `AlarmClock`, `LightController`.

## Sources

Loxone's documents are not part of this repository. Download them from Loxone:

- [Structure File](https://www.loxone.com/wp-content/uploads/datasheets/StructureFile.pdf): format of `LoxAPP3.json` and the control types
- [Communicating with the Miniserver](https://www.loxone.com/wp-content/uploads/datasheets/CommunicatingWithMiniserver.pdf): commands, secured commands, events
- Code: `custom_components/loxone/`
