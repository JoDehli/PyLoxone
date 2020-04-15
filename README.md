# PyLoxone
Home Assistant binding for Loxone. 

A special thanks to Pawel Pieczul from the great openhab2 house automation software. 
He really helped me a lot to with the new token based authentification. Thanks Pawel!!!

#### This release works for the version 0.103.0 and newer!!

## Manual installation
1. Download the zip file and extract  all files into your `config` directory.
2. Add the following section to your `configuration.yaml` and restart:

```yaml
loxone:
  port: 8080
  host: hostadress
  username: username
  password: password
  generate_scenes: false # default is true
```

## Hacs installation
1. Install hacs to your homeassistant installation. See https://hacs.xyz/docs/installation/manual
2. Add this repository to hacs: https://github.com/JoDehli/PyLoxone
3. Install the PyLoxone binding
4. Add the following section to your `configuration.yaml` and restart:

```yaml
loxone:
  port: 8080
  host: hostadress
  username: username
  password: password
  generate_scenes: false # default is true
```

## Websocket direct command
Send command direct to the loxone for example a pulse event to a switch:

```yaml
{
"uuid":"0f1e0b31-0179-7f77-ffff403fb0c34b9e",
"value":"pulse"
}
```

## Supported Loxone Entites
- InfoOnlyAnalog and InfoOnlyDigital
- Switch, TimedSwitch and Pushbutton
- Jalousie, Window and Gate
- Intercom
- LightControllerV2
- Alarm
- LeftRightAnalog, UpDownAnalog, Slider
