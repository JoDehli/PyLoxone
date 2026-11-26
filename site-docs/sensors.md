# Sensors

How the integration decides the device class of a sensor and how to override it.

## Sensor Device Class Detection

Sensors (InfoOnlyAnalog, Meter) are automatically classified based on their unit and Loxone category/name. The following device classes are detected:

| Device class | Detected by |
|---|---|
| `temperature` | Unit: °C, °F |
| `humidity` | Unit: % **and** category or name contains "humidity", "vlhkost", "feucht", or "humidité" |
| `battery` | Unit: % **and** name contains "batt", "akku", or "battery" |
| `energy` | Unit: kWh, Wh, MWh |
| `power` | Unit: W, kW |
| `volume_flow_rate` | Unit: L/h, L/min |
| `water` | Unit: L |
| `illuminance` | Unit: lx, Lx, lux |
| `carbon_dioxide` | Unit: ppm |
| `wind_speed` | Unit: km/h |

Sensors with `%` unit that don't match any keyword are left without a device class.

### Overriding the detected device class

If the automatic detection assigns the wrong device class (or you want to set one for an unclassified sensor), use Home Assistant's built-in [entity customization](https://www.home-assistant.io/docs/configuration/customizing-devices/) in `configuration.yaml`:

```yaml
homeassistant:
  customize:
    sensor.my_percentage_sensor:
      device_class: battery
  customize_glob:
    sensor.*humidity*:
      device_class: humidity
```
