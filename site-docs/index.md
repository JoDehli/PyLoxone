# PyLoxone

PyLoxone is a Home Assistant integration for the Loxone Miniserver. It reads the Miniserver's structure file and maps each Loxone control to a Home Assistant entity.

- [Supported devices](supported-devices.md): which Loxone controls become which Home Assistant entities
- [Known limitations](known-limitations.md)
- [Blueprints](blueprints.md): ready-made automations and scripts

## Installation

=== "HACS (recommended)"

    1. [Install HACS](https://hacs.xyz/docs/use/download/download/) if you have not already.
    2. In HACS, open the menu → **Custom repositories** and add
       `https://github.com/JoDehli/PyLoxone` with the type **Integration**.
    3. Search for **PyLoxone**, install it and restart Home Assistant.
    4. Go to **Settings → Devices & Services → Add Integration**, search for **PyLoxone** and fill in the connection details.

=== "Manual"

    1. Download the latest release and extract it.
    2. Copy the `custom_components/loxone` folder into the `custom_components` folder next to your `configuration.yaml`.
    3. Restart Home Assistant.
    4. Go to **Settings → Devices & Services → Add Integration**, search for **PyLoxone** and fill in the connection details.

!!! info "Requirements"
    Home Assistant 2025.2.4 or newer.

!!! note "More setup details"
    The [setup page](setup.md) covers the recorder configuration, the Gen 2 Miniserver and the cloud connection.
