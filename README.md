# PyLoxone
![Installs](https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=Installations&cacheSeconds=15600&url=https://analytics.home-assistant.io/custom_integrations.json&query=$.loxone.total)
[![Latest release](https://img.shields.io/github/v/release/JoDehli/PyLoxone?label=version)](https://github.com/JoDehli/PyLoxone/releases/latest)
![Hassfest](https://img.shields.io/github/actions/workflow/status/JoDehli/PyLoxone/hassfest.yaml?label=hassfest)
![HACS](https://img.shields.io/github/actions/workflow/status/JoDehli/PyLoxone/validate.yaml?label=HACS)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

If you want to support my work on this binding you can buy me a coffee:

<a href="https://www.buymeacoffee.com/JoDehli" target="_blank"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy Me A Coffee" style="height: 41px !important;width: 174px !important;box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;-webkit-box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;" ></a>


Home Assistant binding for Loxone. 

📖 **Documentation:** https://jodehli.github.io/PyLoxone/ (supported devices, known limitations, blueprints and the developer guide)

A special thanks to Pawel Pieczul from the great openhab2 house automation software. 
He really helped me a lot to with the new token based authentication. Thanks Pawel!!!

#### This release works for the version 2025.2.4 and newer!!

## Quick start

1. Install the integration with [HACS](https://hacs.xyz) by adding `https://github.com/JoDehli/PyLoxone` as a custom repository, or copy the `custom_components/loxone` folder into your Home Assistant configuration directory.
2. Restart Home Assistant.
3. Add the recorder exclusion below to your `configuration.yaml`.
4. Go to **Settings → Devices & Services → Add Integration**, search for **PyLoxone** and enter your Miniserver's connection details.

> [!CAUTION]
> Add this to your `configuration.yaml` before you use the integration. A Loxone system generates a few thousand events per day. Without this exclusion, Home Assistant records all of them and the database can grow very quickly.

```yaml
recorder:
  exclude:
    event_types:
      - loxone_event
```

## Documentation

- [Supported devices](https://jodehli.github.io/PyLoxone/supported-devices/): which Loxone controls become which Home Assistant entities
- [Setup and configuration](https://jodehli.github.io/PyLoxone/setup/): local or cloud connection, options, logging
- [Sensors](https://jodehli.github.io/PyLoxone/sensors/): device class detection
- [Message Center and repairs](https://jodehli.github.io/PyLoxone/message-center/): system status sensor, repair issues, automations
- [Intercom Gen 2](https://jodehli.github.io/PyLoxone/intercom-gen2/) (experimental)
- [Known limitations](https://jodehli.github.io/PyLoxone/known-limitations/)
- [Blueprints](https://jodehli.github.io/PyLoxone/blueprints/)
- [Advanced usage and examples](https://jodehli.github.io/PyLoxone/advanced/): websocket commands, custom entities, how to find UUIDs
- [Developer guide](https://jodehli.github.io/PyLoxone/developer/): dev container, tests, architecture

Commands and states for each control are described in the Loxone [Structure File](https://www.loxone.com/wp-content/uploads/datasheets/StructureFile.pdf).
