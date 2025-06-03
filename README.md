# Orcon MVS-15

(Work in progress)

Home-Assistant integration for the [Orcon MVS-15 fan](https://orcon.nl/mechanische-ventilatie/) + remote with CO₂ sensor + RF15 remote.

Uses MQTT and a [Ramses ESP stick](https://indalo-tech.onlineweb.shop/product/ramses-esp)
to communicate with the fan.

Used [ramses_rf](https://github.com/zxdavb/ramses_rf) and [this wiki](https://github.com/zxdavb/ramses_protocol/wiki) for some code/inspiration/help.

## Features

* Creates a fan entity with all supported presets (Away, Auto, Low, Medium, High + 15/30/60m timed modes)
* The fan reported mode is used to update the fan's current preset, so it will notice when the mode was changed by an RF15 remote for example
* Creates a CO₂ sensor
* Creates a humidity sensor
* Will create a Home-Assistant notification if the fan reports a fault

## TODO

* Create a Remote entity for the fan
* Auto-discovery
* Create a random remote id and use that to bind to the fan
* Ramses ESP stick via USB
* Make CO₂ + humidity optional (not supported by all MVS-15s)

## Lovelace

```yaml
type: tile
entity: fan.orcon_mvs_ventilation
show_entity_picture: false
hide_state: true
vertical: false
features_position: inline
features:
  - type: fan-preset-modes
    style: dropdown
```

## Supported Ramses II codes

The following codes are supported by the Orcon MVS-15 fan. Not all codes are used (yet) by the integration.

| Code | Description         | Used | FAN | CO2 | RF  | Broadcast interval | Requestable | Notes                    |
| ---- | ------------------- | ---- | --- | --- | --- | ------------------ | ----------- | ------------------------ |
| 042F | ?                   | No   | Yes | No  | No  | -                  | No          | Broadcasted on powerup   |
| 10E0 | Device info         | Yes  | Yes | Yes | No  | 24h                | Yes         |                          |
| 10E1 | Device ID           | No   | Yes | Yes | No  | -                  | Yes         |                          |
| 1298 | CO2 sensor          | Yes  | No  | Yes | No  | 10m                | Yes         |                          |
| 12A0 | Indoor humidty      | Yes  | Yes | No  | No  | -                  | Yes         |                          |
| 1FC9 | RF Bind             | No   | ?   | ?   |     | -                  | No          |                          |
| 22F1 | Fan mode            | Yes  | Yes | No  | No  | -                  | Yes         |                          |
| 22F3 | Fan mode with timer | Yes  | Yes | No  | No  | -                  | No          |                          |
| 31D9 | Fan state           | Yes  | Yes | No  | No  | 5m                 | Yes         | Fan mode + fault flag    |
| 31E0 | Vent demand         | Yes  | No  | Yes | No  | 5m                 | Yes         |                          |
