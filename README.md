# Orcon MVS-15

(Work in progress)

Home-Assistant integration for the [Orcon MVS-15 fan](https://orcon.nl/mechanische-ventilatie/),
(optional) remote with CO₂ sensor and (optional) RF15 remote.

Uses MQTT and a [Ramses ESP stick](https://indalo-tech.onlineweb.shop/product/ramses-esp)
to communicate with the fan.

I used [ramses_rf](https://github.com/zxdavb/ramses_rf) and [this wiki](https://github.com/zxdavb/ramses_protocol/wiki) for some code/inspiration/help.

## Features

- Creates a fan entity with all supported presets (Away, Auto, Low, Medium, High + High 15/30/60m timed modes)
- [TODO] Auto-detects the fan
- Auto-detects a CO₂ remote and creates an HA sensor
- Auto-detects the fan's humidity sensor and creates an HA sensor
- Creates a binary sensor that triggers when the fan reports a fault
- The fan reported mode is used to update the fan's current preset in HA, so it will notice when the mode was changed by an RF15 remote for example

## Auto-discovery

1. Turn the fan off and on again
1. The fan will be discovered by a startup message (042F) it sends out
1. The state of the humidity sensor (part of the fan) will be requested (12A0), and will be setup in HA if it responds
1. The CO₂ sensor/remote will be discovered as soon as it sends a vent demand message (31E0) to the above fan (might take a while)

## TODO

- Auto-discovery for the fan
- Create a random remote id and use that to bind to the fan
- Ramses ESP stick via USB

## Lovelace

```yaml
type: tile
entity: fan.orcon_mvs_15_fan
show_entity_picture: false
hide_state: true
vertical: false
features_position: inline
features:
  - type: fan-preset-modes
    style: dropdown
```

## Alert on fault

```
alert:
  orcon_mvs_15_fault:
    title: Orcon MVS-15 fault
    name: The fan reported a fault
    done_message: The fan fault was cleared
    entity_id: binary_sensor.orcon_mvs_15_fan_fault
    repeat: 1440
    notifiers:
      - persistent_notification  # create an alert in the web ui
      - mobile_app_your_phone  # send a notification through the companion app
```

Check the LED on the fan unit if it reports a fault:

| Flashing red | Error                         |
| -------------|-------------------------------|
| 1x           | Motor not running             |
| 2x           | No value from humidity sensor |
| 3x           | RF communication failure      |

## Supported Ramses II codes

The following codes are supported by the Orcon MVS-15 fan. Not all codes are used (yet) by the integration.

| Code | Description         | Used | FAN | CO₂ | RF  | Broadcast interval | Requestable | Notes                 |
| ---- | ------------------- | ---- | --- | --- | --- | ------------------ | ----------- | --------------------- |
| 042F | ?                   | Yes  | Yes | No  | No  | -                  | No          | Send on powerup       |
| 10E0 | Device info         | Yes  | Yes | Yes | No  | 24h                | Yes         |                       |
| 10E1 | Device ID           | No   | Yes | Yes | No  | -                  | Yes         |                       |
| 1298 | CO₂ sensor          | Yes  | No  | Yes | No  | 10m                | Yes         |                       |
| 12A0 | Indoor humidty      | Yes  | Yes | No  | No  | -                  | Yes         |                       |
| 1FC9 | RF Bind             | No   | ?   | ?   |     | -                  | No          |                       |
| 22F1 | Fan mode            | Yes  | Yes | No  | No  | -                  | Yes         |                       |
| 22F3 | Fan mode with timer | Yes  | Yes | No  | No  | -                  | No          |                       |
| 31D9 | Fan state           | Yes  | Yes | No  | No  | 5m                 | Yes         | Fan mode + fault flag |
| 31E0 | Vent demand         | Yes  | No  | Yes | No  | 5m                 | Yes         |                       |
