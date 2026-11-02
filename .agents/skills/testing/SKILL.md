---
name: Testing
description: Use when writing, changing or debugging tests for the orcon_mvs15 integration, or when the test harness, fixtures, stubs or coverage gate need attention.
---

# Testing orcon_mvs15

The suite must run without hardware or a broker: mock MQTT and the session.
Home Assistant comes from `pytest-homeassistant-custom-component`, not from
hand-written imports of Home Assistant internals. `tests/conftest.py` loads the
plugin and enables custom integrations.

## Commands

```sh
python -m pytest -v tests/
python -m pytest -v tests/test_codes.py -k humidity
python scripts/check_coverage.py
```

`python -m pytest` avoids a stale `pytest` shim. The coverage gate is
`scripts/check_coverage.py`; every module must stay above 95%.

## Fixtures and stubs

* Fixtures must be protocol-correct: real frame layout, real byte order and real
  examples from `docs/protocol.md`. Do not invent packet values.
* Recorded gateway traffic belongs in `tests/test_recorded_frames.py`. Extend it
  when adding a frame-level regression.
* Stubs must mirror real behaviour. A stub that hides an `AttributeError` also
  hides the bug.
* Extend the shared stubs in `tests/conftest.py` instead of duplicating a fake
  session or MQTT client in each test.

## Regression tests

Every bug fix needs a test that fails against the previous code. Verify that it
does before claiming the fix works: run the new test against the pre-fix commit
in a scratch worktree, then against the fix.

```sh
git worktree add /tmp/opencode/pre-fix <pre-fix-commit>
cp tests/test_regression.py /tmp/opencode/pre-fix/tests/
cd /tmp/opencode/pre-fix && python -m pytest -q tests/test_regression.py
# expected: failure, because the fix is not present
```

Remove the worktree when done. Never weaken an assertion to make a test pass; if
the expected value is wrong, fix the code or the fixture instead.

## Coverage

CI runs `pytest` with `--cov-report=json` and then
`python scripts/check_coverage.py`. Every module must stay above 95% coverage.
Do not add a module to an exclusion list to pass the gate.
