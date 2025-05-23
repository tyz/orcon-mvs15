# Orcon MVS

(Work in progress)

Home-Assistant integration for Orcon MVS-15 fan + remote with CO₂ sensor + RF15 remote.

Uses MQTT and a [Ramses ESP stick](https://indalo-tech.onlineweb.shop/product/ramses-esp)
to communicate with the fan.

Used [ramses_rf](https://github.com/zxdavb/ramses_rf) and [this wiki](https://github.com/zxdavb/ramses_protocol/wiki) for some code/inspiration/help.

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

## Known codes

| Code | Description         | FAN | CO2 | RF  | Broadcast interval | Requestable | Notes                    |
| ---- | ------------------- | --- | --- | --- | ------------------ | ----------- | ------------------------ |
| 1060 | Battery state       | No  | No  | Yes | 15m                | Yes         | Some models (VMN-15LF01) |
| 10E0 | Device info         | Yes | Yes | No  | 24h                | Yes         |                          |
| 1298 | CO2 sensor          | No  | Yes | No  | 10m                | Yes         |                          |
| 12A0 | Indoor humidty      | Yes | No  | No  | -                  | Yes         |                          |
| 1FC9 | RF Bind             | ?   | ?   |     | -                  | No          |                          |
| 22F1 | Fan mode            | Yes | No  | No  | -                  | Yes         |                          |
| 22F3 | Fan mode with timer | Yes | No  | No  | -                  | No          |                          |
| 31D9 | Fan state           | Yes | No  | No  | 5m                 | Yes         | Fan mode + extra flags   |
| 31E0 | Vent demand         | No  | Yes | No  | 5m                 | Yes         |                          |
