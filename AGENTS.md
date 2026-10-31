# Project Context & Agent Guidelines

`orcon_mvs15` is a custom Home Assistant integration for the Orcon MVS-15
ventilation fan, its optional CO₂/15RF remote and its humidity sensor. It talks
Ramses II over MQTT through a Rameses ESP stick. This file is the operating
manual for agents working on the integration. The wire protocol lives in
`docs/protocol.md`; user-facing documentation lives in `README.md`; the packet
naming rules live in `custom_components/orcon_mvs15/README.naming.md`.

## Project Facts

| | |
|---|---|
| Domain | `orcon_mvs15` — must match `custom_components/orcon_mvs15/` |
| Transport | MQTT (`homeassistant.components.mqtt`) through a Rameses ESP gateway |
| Client layer | `protocol` modules (`ramses_packet.py`, `codes.py`, `ramses_packet_queue.py`) are Home Assistant-free; `mqtt.py` is transport; `ramses_esp.py` is the protocol session |
| Platforms | `fan`, `sensor`, `binary_sensor` in a single config entry |
| Discovery | MQTT wildcard `<base_topic>/+` for the gateway; Ramses `042F`, `12A0` and `31E0` packets for devices |
| Update model | `local_push` — the gateway pushes packets; humidity is polled because `12A0` is not broadcast |
| Quality scale | Not yet present. Target tier is Bronze; add `quality_scale.yaml` only when the claims are true |

## Before You Change Anything

1. Run the checks below. If one fails before your change, stop and report it —
   do not "fix" unrelated failures and never delete or `xfail` a test to get
   green.
2. Read `README.md`, `docs/protocol.md`, `custom_components/orcon_mvs15/TODO.txt`
   and, once it exists, `quality_scale.yaml`.
3. Skim `git log -20` to absorb the commit style.
4. Check `git status`. Uncommitted work belongs to the user; never overwrite or
   revert it.
5. Home Assistant is not installed by default. Before trusting `mypy` or running
   integration tests, install the approved dev pin described below.

## Workflow & Commands

* Linting: `pre-commit run --all-files` — run it twice; the first pass may
  reformat. The project Ruff rule set is pinned in `ruff.toml`.
* Type checking: `mypy custom_components/` — only meaningful with Home Assistant
  installed; without it, HA imports are silently ignored.
* Tests: `pytest -v tests/`. Pytest configuration lives in `pyproject.toml`;
  `tests/conftest.py` loads `pytest-homeassistant-custom-component` and enables
  custom integrations.
* Compile check: `python -m compileall -q custom_components/orcon_mvs15`.
* Approved test environment: `pip install -r requirements-test.txt`, which pins
  `pytest-homeassistant-custom-component==0.13.375` and therefore
  `homeassistant==2026.10.4`; it requires Python `>=3.14`.
* CI: no workflow exists yet. It is planned in M5 and must run `pre-commit`,
  `mypy` against the installed Home Assistant version, `pytest` and hassfest.

## How To Change Code

* **Prefer the `edit` tool over Python string surgery.** `edit` fails loudly when
  an anchor is missing or ambiguous; `s.replace()` silently replaces the wrong
  occurrence. Use a script only for genuinely repetitive, line-local changes.
* **Never re-indent a block with find-and-replace.** Replace the whole function
  in one exact edit, or extract a helper so no re-indentation is needed.
* **A script that prints `patched` proves nothing.** After an edit touching more
  than about ten lines: format, lint, compile the touched file, then read
  `git diff`. The diff and the tests are the evidence.
* **Do not re-read large files.** Use `grep -n -A/-B` for context and
  `sed -n '120,180p'` for a slice.
* **Do not split commits retroactively.** Decide commit boundaries before
  editing. One honest commit beats a patch-and-revert dance.
* **Never `git checkout -- <file>`, `git reset --hard` or `git stash drop`.**
  Back up to `/tmp/opencode/` before any bulk operation.
* **Run the linter and tests after every change**, not once at the end.

## Coding Conventions

* Type hints are mandatory everywhere.
* Docstrings follow Google style.
* Keep functions small and single-purpose.
* Formatting is enforced by `ruff format`.
* Do not add `# type: ignore` or `cast()` to silence a finding; fix the cause or
  use the correct type.

## Home Assistant Guidelines

* **Asynchronous execution:** never run blocking I/O (network, files,
  `time.sleep()`) on the event loop. Use native `async`/`await` or
  `hass.async_add_executor_job()`.
* **Dependency management:** do not add or change `requirements` in
  `manifest.json`, or dependencies in project metadata, without explicit
  permission.
* **Architecture separation:** communication stays out of entity classes,
  wrapped in the session/coordinator layers. Protocol decoding must stay free of
  Home Assistant imports.
* **Lifecycle:** use `entry.runtime_data` for per-entry state, not
  `hass.data[DOMAIN]`. Register teardown with `entry.async_on_unload(...)`.
  Use `async_at_started`/`ConfigEntryNotReady` instead of ad-hoc sleeps.
* **Error handling:** catch raw transport/protocol exceptions at the boundary and
  translate them into `HomeAssistantError`, `ConfigEntryNotReady`, or a domain
  exception callers can act on. Never log-and-continue when the caller needs to
  know a command failed.
* **Availability:** entities must be `unavailable` whenever the device cannot be
  controlled or no state has been received. "Optimistic but wrong" is worse than
  "unavailable".
* **Entity unique IDs must be stable.** Never derive them from anything the user
  can change (address, MAC, name). Ramses IDs are the current stable identity.
* **Device registry:** use `async_get_device_by_identifier(identifier,
  config_entry_id)`; `async_get_device()` is deprecated. Pass the config entry ID,
  never the gateway Ramses ID.
* **Discovery** uses the integration's own transport helpers, not a fresh scan.
* **Quality scale:** claims are checked against the code. If the code does not do
  it, the rule is `exempt` with a reason or `todo`, not `done`.
* **Naming:** always "Home Assistant", two words, never hyphenated.

## Current Architecture

* `mqtt.py` — subscribes to gateway topics and publishes envelopes. It currently
  also performs gateway discovery and waits for the first wildcard message.
* `ramses_esp.py` — protocol session: packet parsing/dispatch, expected-response
  retries, device discovery and packet logging. It currently touches the device
  registry and the event loop directly; split transport/registry concerns out in
  M3.
* `handlers.py` — turns decoded `Code` payloads into coordinator updates and
  device-registry updates.
* `coordinator.py` — push-only coordinators for the fan, CO₂ sensor and remote.
* `discover_entity.py` — creates entities once a Ramses ID is known or discovered.
* `fan.py`, `sensor.py`, `binary_sensor.py` — entities. They currently build
  their own `DeviceInfo`; centralise this in M3/M4.

Planned direction (M1–M5): test harness first, then correctness fixes, typed
runtime data, a central device-info helper, explicit code registry, entity
translation keys/availability, config-flow options/reconfigure, diagnostics,
`quality_scale.yaml`, and CI.

## Testing

* No device or MQTT broker is needed: the suite must mock MQTT and the session.
* Home Assistant is mocked through `pytest-homeassistant-custom-component`, not
  hand-written imports of Home Assistant internals.
* Fixtures must be protocol-correct: real frame layout, real byte order, real
  examples from `docs/protocol.md`. Do not invent values.
* Stubs must mirror real behaviour, not smooth it over. A stub that hides an
  `AttributeError` also hides the bug.
* Every bug fix needs a test that fails against the previous code. Verify that it
  does before claiming the fix works.
* Never weaken an assertion to make a test pass.

## Platform and Protocol Gotchas

* MQTT receive frames are `{"ts": ISO-8601, "msg": "<frame>"}`; publish frames are
  `{"msg": "<frame>"}` on `<base>/<gateway>/tx`.
* The frame is `SSS TT --- SSSSSSS DDDDDDD AAAAAAA CCCC LLL DATA`. `LLL` is the
  byte count; `DATA` has twice as many hex characters.
* `042F` is broadcast on fan power-up and is not requestable. The current filter
  accepts it from **any** source and uses `ann_id` as the fan ID, so a
  neighbouring Orcon can be adopted. Treat this as a known risk, not a feature.
* `31D9` and `12A0` use `src_id` as the fan/humidity device ID. `042F` uses
  `ann_id`.
* `22F1` carries 3-byte fan modes. Timed modes use `22F3` with 7 bytes. The
  integration does not track when a timed mode ends.
* `12A0` is not announced; it must be polled. Current code starts polling only
  after the first response, so a lost first response means no further polls.
* Signal strength is received as a negative dBm value; handlers negate it into the
  value exposed by the sensors.
* Expected-response matching is by type, code, source and destination. A packet
  must be in the retry queue **before** it is published; otherwise a fast
  response can be missed by the queue.
* Packet logging currently writes to `/config/packet.log`, rolls over at 10 MB and
  is always on. It is a debugging aid, not a stable interface.
* `10E0` device info is broadcast every 24 hours and is requestable; `31D9` fan
  state is broadcast every 5 minutes; `31E0` vent demand every 5 minutes.

## Dead Ends — Do Not Re-Investigate

* `via_device` in `DeviceInfo` is deprecated — use `via_device_id`.
* `device_registry.async_get_device()` is deprecated and breaks in HA 2027.8 — use
  `async_get_device_by_identifier()`.
* `PlatformNotReady` is only for `async_setup_platform`. Entry setup must raise
  `ConfigEntryNotReady`.
* `CONCENTRATION_PARTS_PER_MILLION` was replaced by `UnitOfRatio.PARTS_PER_MILLION`;
  do not revert that fix.
* `origin/test` is stale debug work (`XXX` logging, `_value`, reverted registry
  fixes). Do not merge it.
* `_dev_hex_to_id("FFFFFF")` returns nine spaces. The correct meaning is
  unverified; do not change it without protocol evidence.
* `ruff.toml` pins the project rule set (`E4`, `E7`, `E9`, `F`, `ANN`) so local
  Ruff and the pre-commit hook agree. Do not run Ruff with `--select ALL`; it
  flags unrelated pre-existing code.
* `custom_components/poetry.lock` has no matching `pyproject.toml`, so
  `poetry update --lock` cannot run there. Do not invent project metadata in a
  documentation or bug-fix change.
* Do not "solve" neighbour `042F` discovery by accepting more packet types or
  sources. Ownership verification is a design decision, not a filter tweak.

## Version Control

* The default branch is `master`. Work on a branch named after the change, for
  example `docs/agents-and-protocol` or `fix/gateway-discovery`.
* New commits use Conventional Commits (`docs:`, `fix:`, `chore:`), one commit per
  logical change.
* Open a pull request describing the problem and the approach. Do not merge your
  own pull request unless explicitly asked.
* Do not push, tag, force-push or delete a remote branch without the user's
  permission. A local commit is not permission to publish it.

## Documentation

* `README.md` is the user-facing manual: features, installation, troubleshooting.
  Keep it current when behaviour changes.
* `docs/protocol.md` is the technical reference. Correct it when reality
  contradicts it.
* `custom_components/orcon_mvs15/TODO.txt` is the working list. Tick items only
  after the user approves the result.
* Comments explain *why*, not *what*. Name firmware/protocol bugs and where they
  were observed.

## External Resources

* [ramses_rf](https://github.com/zxdavb/ramses_rf) and the
  [Ramses protocol wiki](https://github.com/zxdavb/ramses_protocol/wiki) for
  packet semantics and field layouts.
* [Rameses ESP](https://indalo-tech.onlineweb.shop/product/ramses-esp) for the
  MQTT gateway behaviour.
* Home Assistant developer docs for config entries, coordinators and device
  registry APIs.

## Language

* Code, comments, documentation and commit messages are **English**.
* This repository translates `en` and `nl` only. Keep
  `custom_components/orcon_mvs15/strings.json` (once added),
  `translations/en.json` and `translations/nl.json` key-synced in the same change.
* A removed key is removed from every file. Product names that are identical in a
  language are not untranslated; leave them.

## Your Environment

* Linux, Python 3.14.6. You run in an OCI container; only `/project` and
  `/project/.opencode` survive a restart. Use `/tmp/opencode` for scratch files.
* Home Assistant is not preinstalled. Install the approved test pin before
  meaningful type checking or tests.
* `pre-commit` environments are cached; `pre-commit autoupdate` is allowed when
  updating lint tooling, but keep that in its own commit.
* Ask for missing tooling instead of working around it.

## Reporting

When you finish, report what you **verified**, not what you intended: the exact
commands and their results, what changed in behaviour, and what remains open. If
something failed or was skipped, say so explicitly.
