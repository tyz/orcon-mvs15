# Recorded gateway frames

These files hold frames captured from a real Orcon MVS-15 installation. They
are replayed by `tests/test_recorded_frames.py`.

| Role | Address | Device info |
|---|---|---|
| HGI (gateway) | `18:149960` | requests only, no `10E0` broadcast |
| Wireless remote, sold as `Afstandsbediening 15RF` | `29:163058` | no `10E0`; only `22F1`/`22F3` |
| Fan, sold as `MVS-15xxx` | `29:224547` | product `26`, `VMC-15RP01` |
| Wired CO₂ sensor, sold as `CO2 ruimtesensor 15RF` | `32:093959` | product `51`, `VMS-15CM17` |

The capture was taken from the packet log the integration writes to
`/config/packet.log`. Only these changes were made:

* the leading ISO-8601 timestamp was removed, so the files are stable;
* the signal strength and the frame itself are untouched;
* repeated broadcasts were reduced to one representative line per value;
* traffic from other installations was left out, except where a value does not
  occur on the captured installation. Those lines are listed under
  “Neighbouring devices” below.

Each line is one gateway `msg` payload:

```text
SSS  T --- SSSSSSS DDDDDDD AAAAAAA CCCC LLL DATA
```

## Files

| File | Contents |
|---|---|
| `power_up.log` | `042F` power-up broadcasts, plus the frame `startup-emu.sh` publishes with signal strength `000` |
| `startup.log` | The fan's real restart in order: `042F`, `10E0`, `31D9`, `12A0` |
| `device_info.log` | `10E0` broadcasts and responses for the fan and the CO₂ sensor |
| `fan_state.log` | `31D9` broadcasts covering every mode, the fault bit and unknown modes |
| `fan_modes.log` | `22F1` and `22F3` preset frames, including command echoes with signal strength `000` |
| `vent_demand.log` | `31E0` broadcasts and the request/response pair |
| `co2_levels.log` | `1298` CO₂ broadcasts and the request/response pair |
| `humidity.log` | `12A0` humidity responses and the request |

## Neighbouring devices

The gateway also hears other installations. Their frames are used only where
the captured fan or remote never produced a value:

* same-family fans (product `26`): the power-ups from `29:224179` and
  `29:223489`, and the states from `29:225395`, `29:225692`, `29:224195` and
  `29:227645`;
* other 15RF wireless remotes (no `10E0` captured): the presets from `29:166254`,
  `29:163284`, `29:163883` and `29:176871`;
* other wired CO₂ sensors (product `51`): the vent demand from `32:097067`,
  `32:094514`, `32:096802`, `32:096763`, `32:096887` and `32:093949`;
* a neighbouring device of another Orcon system (`29:167925`, product `27`,
  `VMN-15LF01`, possibly a WTW unit across the street): the extra `10E0` line
  in `device_info.log`.

## Out of scope

WTW systems across the street use the same transport but send additional codes.
They are out of scope for now, so none of their frames are used here.

## Signal strength `000`

The `22F1`/`22F3` command echoes with signal strength `000` carry the remote as
source because the integration publishes commands with `src_id` set to the
remote. The session treats a zero signal strength as “sent by this integration”
and ignores the frame, except for `042F`, where the same value is used for the
local test injection.
