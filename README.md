# Orcon MVS-15

(Work in progress, currently requires a working 15RF remote until pairing a fake remote is implemented)

Home Assistant integration for the [Orcon MVS-15 fan](https://orcon.nl/mechanische-ventilatie/),
(optional) remote with CO₂ sensor and (optional) 15RF remote.

Uses MQTT and a [Ramses ESP stick](https://indalo-tech.onlineweb.shop/product/ramses-esp)
to communicate with the fan.

I used [ramses_rf](https://github.com/zxdavb/ramses_rf) and [this wiki](https://github.com/zxdavb/ramses_protocol/wiki) for some code/inspiration/help.

## Features

- Creates a fan entity with all supported presets (Away, Auto, Low, Medium, High + High 15/30/60m timed modes)
- Auto-detects the fan
- Auto-detects a CO₂ remote and creates an HA sensor
- Auto-detects the fan's humidity sensor and creates an HA sensor
- Creates a binary sensor that triggers when the fan reports a fault
- The fan reported mode is used to update the fan's current preset in HA, so it
  will immediately notice when the mode was changed by a 15RF remote, for example

## TODO

- Set up a fake remote and pair it with the fan
- Ramses ESP stick via USB (currently only supports MQTT)

## Install

You can install this integration by adding its GitHub repository to the HACS
configuration under `Custom repositories`. Then install it in HACS, and add the
`Orcon MVS-15` integration in `Settings > Devices & services`.

## Fan ID

If you don't know the ID of the 15RF remote then use a fake ID (e.g. `29:123456`).
Tail the `packet.log` file in the Home Assistant config directory, and press the
`auto` button on the remote a couple of times. The resulting log entries should
look something like this:

```text
2026-09-11T17:29:09.534250+02:00 081  I --- 29:123456 29:654321 --:------ 22F1 003 000404
```

The remote's ID in this example is `29:123456`.

## Auto-discovery

1. Install and configure the integration. The `remote ID` it asks for is the 15RF remote's ID.
1. Turn the fan off and on again
1. The fan will be discovered by a startup message (042F) it sends out
1. The state of the humidity sensor (part of the fan) will be requested (12A0), and will be set up in HA if it responds
1. The CO₂ sensor/remote will be discovered as soon as it sends a vent demand message (31E0) to the above fan (might take a while)

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
      - persistent_notification  # create an alert in the web UI
      - mobile_app_your_phone  # send a notification through the companion app
```

Check the LED on the fan unit if it reports a fault:

| Flashing red | Error                         |
| -------------|-------------------------------|
| 1x           | Motor not running             |
| 2x           | No value from humidity sensor |
| 3x           | RF communication failure      |

## Protocol

The integration speaks the Ramses II protocol over MQTT. The frame format,
supported codes, discovery flows and retry behaviour are documented in
[docs/protocol.md](docs/protocol.md).

## Troubleshooting

### Debug logging

Enable debug logging by adding the following snippet to `configuration.yaml`

```
logger:
  logs:
    custom_components.orcon_mvs15: debug
```
