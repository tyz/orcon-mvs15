---
name: Home Assistant translations
description: Use when a user-visible string changes (config flow title, entity name, abort or error reason), when adding or removing a translation key, or when the translation files drift from strings.json.
---

# Keep the translation files key-synced

`custom_components/orcon_mvs15/strings.json` is the reference. This repository
ships `translations/en.json` and `translations/nl.json`; every file must contain
exactly the same key paths. `tests/test_translations.py` enforces that, checks
the fan preset names against `Code22f1.presets()`, and verifies that exception
and issue placeholders resolve in every message.

## The rule that matters

**Never overwrite an existing translated value.** These are real translations,
not generated copies. Add keys that are absent, and remove a key only when it was
removed from `strings.json`. Product names that are identical in both languages
may keep the same text.

## Procedure

1. Change `strings.json` first. Only then touch `translations/`.
2. Report the drift, writing nothing:

       python .agents/skills/ha-translations/scripts/check_translations.py

3. Add the missing keys. `--fix` inserts the English value as a scaffold only;
   write the real Dutch text in `translations/nl.json` before committing. Never
   leave English there unless the string is a product name:

       python .agents/skills/ha-translations/scripts/check_translations.py --fix

4. Read `git diff --stat`. Expect additions only. A deletion means the script
   touched existing text: that is a bug, so stop and report it — do not repair it
   by hand.
5. If you removed a key from `strings.json` on purpose, drop the leftovers:

       python .agents/skills/ha-translations/scripts/check_translations.py --prune-extra

   Use this only when the reported extras are exactly the keys you deleted. It
   deletes anything absent from `strings.json`, including a value someone meant
   to keep, when `strings.json` itself is wrong.
6. Re-run the plain check. It must exit 0 and report that every file matches.
7. Run the translation tests and the full gate:

       python -m pytest -q tests/test_translations.py
       pre-commit run --all-files

## Notes

- The script compares dotted paths including intermediate objects, which catches
  the same structural drift as the nested key-tree comparison in
  `tests/test_translations.py`. It reproduces the files byte for byte when
  nothing changes.
- An added key lands in the position it has in `strings.json`, so the diff stays
  additions-only even when the key was missing rather than new.
- `en.json` legitimately equals the English text in `strings.json`. Never "fix"
  that by inventing a translation.
- Never regenerate a file from scratch with a fresh `json.dump`: that reorders
  keys and produces a diff in every file even where nothing changed.
- Entity names live under `entity.<platform>.<translation_key>.name` in
  `strings.json`. The key must match `_attr_translation_key` on the entity class.
- Every exception and issue message must keep the placeholders the tests expect:
  `tests/test_translations.py` formats them and compares the field set.
- A new fan preset needs a translation in every file and an icon in `icons.json`;
  `tests/test_translations.py::test_icons_cover_every_preset` catches a mismatch.
