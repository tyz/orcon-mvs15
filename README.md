# Orcon MVS-15

[![CI](https://github.com/tyz/orcon-mvs15/actions/workflows/ci.yml/badge.svg)](https://github.com/tyz/orcon-mvs15/actions/workflows/ci.yml)
[![CodeQL](https://github.com/tyz/orcon-mvs15/actions/workflows/github-code-scanning/codeql/badge.svg)](https://github.com/tyz/orcon-mvs15/actions/workflows/github-code-scanning/codeql)

Home Assistant integration for the [Orcon MVS-15 fan](https://orcon.nl/mechanische-ventilatie/), the (optional) wired `CO2 ruimtesensor 15RF` with its CO₂ sensor and the (optional) `Afstandsbediening 15RF` wireless remote.

Uses MQTT or a USB serial connection and a [Ramses ESP stick](https://indalotech.co.uk/products/ramses_esp) to communicate with the fan.

I used [ramses_rf](https://github.com/zxdavb/ramses_rf) and [this wiki](https://github.com/zxdavb/ramses_protocol/wiki) for some code/inspiration/help.

## Features

- Creates a fan entity with all supported presets (Away, Auto, Low, Medium, High + High 15/30/60m timed modes)
- Exposes the end and the remaining minutes of a timed preset while it runs
- Optional packet log for debugging, disabled by default
- Auto-detects the fan
- Auto-detects the wired `CO2 ruimtesensor 15RF` and creates a Home Assistant sensor
- Auto-detects the fan's humidity sensor and creates a Home Assistant sensor
- Creates a binary sensor that triggers when the fan reports a fault
- Reports the Ramses ESP firmware version and offers firmware updates over MQTT
- Offers a reboot button for the Ramses ESP gateway and tracks its online state
- Generates a remote and pairs it with the fan, so no 15RF remote is needed
- The mode reported by the fan updates the fan's current preset in Home Assistant, so it immediately notices when the mode was changed by a 15RF wireless remote, for example

## Supported devices

- Orcon MVS-15 ventilation unit (fan, humidity sensor and fault state). The sold model name is `MVS-15xxx`, where `xxx` names the fitted humidity or CO₂ option, for example `MVS-15RH CO2B`.
- Orcon VMC-15RPS34 ventilation unit (same packets as the MVS-15; it reports product ID `5F`)
- Orcon `CO2 ruimtesensor 15RF` wired CO₂ sensor (product ID `51`)
- Orcon `Afstandsbediening 15RF` wireless remote (optional; the integration emulates one, so it is not required)
- Ramses ESP gateway running the Ramses II firmware over MQTT or USB

## Install

Install this integration from the Home Assistant Marketplace:

1. Open **Settings > Marketplace**.
2. Select **Add from link** in the upper-right corner.
3. Enter `https://github.com/tyz/orcon-mvs15` and select **Add**.
4. Open the repository and install **Orcon MVS-15**.
5. Add the integration in **Settings > Devices & services**.

On Home Assistant 2026.10 and older, use HACS instead: add the repository under **Custom repositories** and install it there.

## Installation parameters

The setup form first asks how the Ramses ESP is connected, then for the transport settings:

- **MQTT topic prefix** (MQTT connection) — the base topic of the Ramses ESP gateway, for example `RAMSES/GATEWAY`. The integration discovers the gateway on `<prefix>/+` and then exchanges packets on `<prefix>/<gateway>/rx` and `<prefix>/<gateway>/tx`.
- **Serial port** (USB connection) — the port of the Ramses ESP, picked from the ports Home Assistant knows. The stick exposes two interfaces; use interface `0`, the one whose description ends in `-if00`. The integration reads the board's USB serial number to derive the gateway ID, so there is nothing else to enter.

The integration generates its own remote and pairs it with the fan. Turn the fan off and on again after setup; see [Generated remote](#generated-remote).

The USB descriptor is shared by every ESP32-S3 board, so Home Assistant cannot discover the stick reliably. USB setup is a manual port choice instead.

## Generated remote

The integration generates a remote ID and stores it with the entry. The generated remote behaves like a physical 15RF remote: it sends commands with that ID, but the fan only listens to it after a one-time pairing.

Pairing happens automatically when the fan powers up. The fan opens a short pairing window when it sends its `042F` startup message, and the integration answers with the same `1FC9` offer, accept and confirm exchange that a real remote uses. One successful pairing is enough: the binding survives restarts of Home Assistant, the gateway and the fan. Some fans briefly switch to high and back to auto while pairing.

If a fan factory reset or a missed first attempt leaves the generated remote unpaired, press **Pair again on next fan restart** on the fan device and then turn the fan off and on again. The button does not send anything itself; it clears the current pairing, so the next startup message pairs again. The integration also retries automatically on every startup message until pairing succeeds.

## Auto-discovery

1. Install and configure the integration. It generates its own remote.
1. Turn the fan off and on again.
1. The fan is discovered by the startup message (`042F`) it sends out.
1. The state of the humidity sensor (part of the fan) is requested (`12A0`) and set up in Home Assistant if it responds.
1. The wired `CO2 ruimtesensor 15RF` is discovered as soon as it sends a vent demand message (`31E0`) to the above fan (this might take a while).

## Reconfiguring

If the MQTT topic prefix or serial port is wrong, open the integration's menu in `Settings > Devices & services` and choose **Reconfigure**. Choose the connection you want to change; the other discovered IDs are kept and the entry reloads after the change. Switching between MQTT and USB replaces the gateway ID, because the two gateways are different devices. Reconfiguring keeps the generated remote ID, so the fan stays paired.

## Options

Open the integration's menu in `Settings > Devices & services` and choose **Configure** to change the optional diagnostics. **Write packets to packet.log** is off by default. When enabled, every received packet is appended to `/config/packet.log`, which rolls over at 10 MB. Use it to troubleshoot, then turn it off again.

## Timed modes

The `high_15m`, `high_30m` and `high_60m` presets start a countdown in the integration. While it runs, the fan entity exposes `timer_end` (an ISO 8601 timestamp) and `timer_remaining` (the number of whole minutes left). Any new mode command, from Home Assistant or the remote, replaces the previous
countdown. The preset itself still follows the next state the fan reports.

## Dashboards

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

## Automations

The fan presets are useful automation targets. This example boosts the fan to `high` when the CO₂ level stays above 1200 ppm for two minutes, and returns it to `auto` after ten minutes below 800 ppm. The hysteresis stops the fan switching back and forth around a single threshold.

```yaml
automation:
  - alias: Boost the Orcon MVS-15 on high CO₂
    triggers:
      - trigger: numeric_state
        entity_id: sensor.orcon_mvs_15_co2
        above: 1200
        for: "00:02:00"
    actions:
      - action: fan.set_preset_mode
        target:
          entity_id: fan.orcon_mvs_15_fan
        data:
          preset_mode: high

  - alias: Return the Orcon MVS-15 to auto
    triggers:
      - trigger: numeric_state
        entity_id: sensor.orcon_mvs_15_co2
        below: 800
        for: "00:10:00"
    actions:
      - action: fan.set_preset_mode
        target:
          entity_id: fan.orcon_mvs_15_fan
        data:
          preset_mode: auto
```

Replace the entity IDs with the ones in your installation.

## Data updates

The integration is push-based: the gateway publishes Ramses packets and the integration reacts to them. The fan state and ventilation demand are broadcast every 5 minutes, and device info every 24 hours. The fan's humidity sensor does not broadcast its state, so the integration requests it every 5 minutes. Entities are unavailable until the packet they read has arrived. If the MQTT connection is lost or the USB cable is unplugged, all entities become unavailable and the loss is logged once; they recover when the connection returns. Over MQTT the gateway also reports its own `online`/`offline` state, so a stick that drops off WiFi makes the entities unavailable even while the broker is reachable. After a reconnect the integration re-requests the known device state instead of waiting for the next five-minute broadcast. The USB transport reopens the port automatically, with a backoff that grows to 30 seconds. A configured fan that sends no packet for 30 minutes raises a repair issue; every packet from the fan restarts the window.

## Firmware updates

The gateway reports the firmware it is running on `<prefix>/<gateway>/info/version` and the newest release it found on `<prefix>/<gateway>/info/latest`. Both appear on an update entity on the Ramses ESP device. Home Assistant can ask the stick to install the latest release, or a specific release tag, and waits up to five minutes for the rebooted firmware to report its version.

The update entity needs gateway firmware 0.5.3 or newer: that release added `info/latest`. Older firmware never reports the newest release, so the entity stays `unknown`. Upgrade once with the `update.install` action. Without a version it tells the stick to follow the `latest` release in its configured OTA URL, which also works before `info/latest` exists. With a version it pins a release tag such as `v0.5.3`; a version without the leading `v` is treated as the tag `v0.5.3`. The call still waits for the rebooted firmware to report its version, and afterwards the entity works normally.

The stick downloads the image itself from its configured OTA URL, so it needs WiFi and internet access. The integration does not transfer the firmware and cannot show a download percentage or take a backup. The newest version is whatever the gateway last checked; it checks at boot and every 24 hours.
Firmware installation is offered over MQTT only.

## Gateway reboot

The Ramses ESP device has a **Reboot** button. It sends the firmware's own `reset` command, which restarts the stick; the gateway then reconnects to WiFi and the MQTT broker. The button sits in the configuration category on the gateway device, so it stays off the default dashboard. A reboot is refused while a firmware update is in progress, because restarting would abort the download.

Both transports recover from the restart: MQTT marks the entities unavailable until the gateway publishes `online` again, and USB reopens the port. The integration then re-requests the known fan and CO₂ state, so they return as soon as the gateway is back instead of after the next broadcast.

## Known limitations

- The generated remote is paired automatically on the fan's startup message. If an attempt is missed, turn the fan off and on again or press **Pair again on next fan restart** first.
- The timed-mode countdown is maintained by the integration; the fan's next reported state remains the source of truth for the preset.
- A startup message (`042F`) is accepted from any source while the fan ID is unknown. A neighbouring Orcon unit that powers up while this fan is still being discovered could be adopted as this fan.
- Firmware installation is MQTT-only, reports no download progress, and the offered version can be up to 24 hours old.
- The firmware update entity needs gateway firmware 0.5.3 or newer; older firmware cannot report the latest release.
- The optional `/config/packet.log` (rolled over at 10 MB) is a debugging aid. It is not a stable interface.

## Remove

1. Open `Settings > Devices & services`, select **Orcon MVS-15** and choose **Delete**.
2. If you added this repository as a custom repository, remove it under **Settings > Marketplace > Add from link**. On Home Assistant 2026.10 and older, remove it under **HACS > Custom repositories**.
3. The integration does not create configuration files. If you enabled the packet log, you can delete `/config/packet.log` if you no longer need it.

## Protocol

The integration speaks the Ramses II protocol over MQTT or a USB serial connection. The frame format, supported codes, discovery flows and retry behaviour are documented in [docs/protocol.md](docs/protocol.md).

## Troubleshooting

### The fan stopped responding

When the fan ID is known, the integration asks the fan for its state at startup and keeps watching for its packets. If no packet arrives from the fan for 30 minutes, Home Assistant shows a repair issue under **Settings > System > Repairs**. The issue is deleted automatically as soon as the fan is heard again. Check that the fan has power and that the Ramses ESP gateway is within RF range, then turn the fan off and on again so it announces itself. The watchdog pauses while the MQTT connection is down or the USB port is closed, because an unreachable gateway says nothing about the RF link.

### Debug logging

Enable debug logging by adding the following snippet to `configuration.yaml`

```
logger:
  logs:
    custom_components.orcon_mvs15: debug
```
