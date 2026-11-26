# Known limitations

- **Pushbuttons are stateless.** They cannot reliably trigger automations. Use a `Switch` as a workaround and turn it off again in the automation or in Loxone itself.
- **LightControllerV2 sub-controls are disabled by default.** Enable them under **Settings → Devices & Services → Entities**, or turn on the integration option *Generate sub-controls for LightControllerV2*.
- **Partially supported controls** (marked 🟡 on [Supported devices](supported-devices.md)) only offer a subset of the functions Loxone defines.
- **Intercom Gen 2 is experimental.** It was written without access to an Intercom Gen 2 and the output buttons are untested on hardware. The camera, two-way audio, Intercoms of a trust member and custom `IntercomV2` devices are not supported.
- **Not supported:** `LightController` (V1), `AlarmChain`, `AlarmClock`.
