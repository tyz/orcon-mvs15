#!/usr/bin/env python3
"""Keep the Orcon MVS-15 translation files key-synced with strings.json.

``tests/test_translations.py`` compares the nested key trees of
``strings.json`` and every ``translations/*.json``. This script performs the same
comparison locally, per file, and can add missing keys without touching a single
existing value.

Usage:
    python check_translations.py                  # report drift, change nothing
    python check_translations.py --fix            # add missing keys (English scaffold)
    python check_translations.py --prune-extra    # delete keys absent from strings.json

Exit codes: 0 clean, 1 drift, 2 unusable input.
"""

from __future__ import annotations

import argparse
import copy
import json
import pathlib
import sys
from collections.abc import Iterator

type JSONValue = (
    dict[str, JSONValue] | list[JSONValue] | str | int | float | bool | None
)

DEFAULT_COMPONENT = (
    pathlib.Path(__file__).resolve().parents[4] / "custom_components" / "orcon_mvs15"
)


class StructureError(Exception):
    """A path holds an object in strings.json but a scalar in a translation."""


def flatten(node: JSONValue, prefix: str = "") -> set[str]:
    """Return every dotted path in node, intermediate objects included.

    This catches the same structural drift as the nested key-tree comparison in
    ``tests/test_translations.py``. Intermediate objects are part of the set on
    purpose: a translation that loses a whole section must fail, not just the
    leaves underneath it.
    """
    keys: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else key
            keys.add(path)
            keys |= flatten(value, path)
    return keys


def leaves(node: JSONValue, prefix: str = "") -> Iterator[str]:
    """Yield the dotted paths of the scalar leaves under node."""
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else key
            yield from leaves(value, path)
    else:
        yield prefix


def reorder(target: dict[str, JSONValue], source: dict[str, JSONValue]) -> None:
    """Put the shared keys of target in source order, leaving extras at the end.

    Every translation file follows the key order of strings.json. Restoring a
    missing key without this would append it to its parent and show up in the
    diff as a deletion plus an addition, which is exactly the noise the caller is
    told to treat as a bug.
    """
    ordered = {key: target[key] for key in source if key in target}
    ordered.update({key: value for key, value in target.items() if key not in ordered})
    target.clear()
    target.update(ordered)


def add_missing(
    target: dict[str, JSONValue], source: dict[str, JSONValue], prefix: str = ""
) -> list[str]:
    """Copy keys that are absent from target out of source, never overwriting.

    Args:
        target: Parsed translation file, modified in place.
        source: Parsed strings.json.
        prefix: Dotted path of the parent, used for reporting.

    Returns:
        The dotted paths that were added.

    Raises:
        StructureError: If a shared path holds an object on one side and a
            scalar on the other, which no automatic merge can resolve.
    """
    added: list[str] = []
    added_here = False
    for key, value in source.items():
        path = f"{prefix}.{key}" if prefix else key
        if key not in target:
            target[key] = copy.deepcopy(value)
            added.extend(leaves(value, path))
            added_here = True
        elif isinstance(value, dict) and isinstance(target[key], dict):
            added.extend(add_missing(target[key], value, path))
        elif isinstance(value, dict) != isinstance(target[key], dict):
            target_kind = (
                "object"
                if isinstance(target[key], dict)
                else type(target[key]).__name__
            )
            source_kind = "object" if isinstance(value, dict) else type(value).__name__
            raise StructureError(
                f"{path}: {target_kind} in the translation, {source_kind} in strings.json"
            )
    if added_here:
        reorder(target, source)
    return added


def prune_extra(
    target: dict[str, JSONValue], source: dict[str, JSONValue], prefix: str = ""
) -> list[str]:
    """Delete keys that do not exist in source, recursing into shared objects.

    Args:
        target: Parsed translation file, modified in place.
        source: Parsed strings.json.
        prefix: Dotted path of the parent, used for reporting.

    Returns:
        The dotted paths that were removed.
    """
    removed: list[str] = []
    for key in list(target):
        path = f"{prefix}.{key}" if prefix else key
        if key not in source:
            del target[key]
            removed.append(path)
        elif isinstance(source[key], dict) and isinstance(target[key], dict):
            removed.extend(prune_extra(target[key], source[key], path))
    return removed


def write(path: pathlib.Path, data: dict[str, JSONValue]) -> None:
    """Write a translation file in the formatting the repository already uses.

    json.dumps with indent=2 and ensure_ascii=False reproduces the existing files
    byte for byte, so a file that only gains keys produces a diff of exactly
    those keys.
    """
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def report(name: str, missing: set[str], extra: set[str]) -> None:
    """Print one line per kind of drift, naming every path."""
    if missing:
        print(f"{name}: missing {len(missing)}: {', '.join(sorted(missing))}")
    if extra:
        print(f"{name}: extra {len(extra)}: {', '.join(sorted(extra))}")


def main() -> int:
    """Compare every translation file against strings.json and optionally repair it."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--component",
        type=pathlib.Path,
        default=DEFAULT_COMPONENT,
        help="Integration directory to check (default: the Orcon MVS-15 component).",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help=(
            "Add keys missing from a translation using the English value as a "
            "scaffold; translate the value before committing."
        ),
    )
    parser.add_argument(
        "--prune-extra",
        action="store_true",
        help="Delete keys that are absent from strings.json.",
    )
    args = parser.parse_args()

    reference_path = args.component / "strings.json"
    translation_dir = args.component / "translations"
    if not reference_path.is_file():
        print(f"error: {reference_path} does not exist", file=sys.stderr)
        return 2

    reference: dict[str, JSONValue] = json.loads(
        reference_path.read_text(encoding="utf-8")
    )
    reference_keys = flatten(reference)

    files = sorted(translation_dir.glob("*.json"))
    if not files:
        print(f"error: no translation files in {translation_dir}", file=sys.stderr)
        return 2

    problems = 0
    changed = 0

    for path in files:
        try:
            data: dict[str, JSONValue] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as err:
            print(f"{path.name}: invalid JSON: {err}")
            problems += 1
            continue

        if not (args.fix or args.prune_extra):
            missing = reference_keys - flatten(data)
            extra = flatten(data) - reference_keys
            if missing or extra:
                problems += 1
                report(path.name, missing, extra)
            continue

        try:
            added = add_missing(data, reference) if args.fix else []
            removed = prune_extra(data, reference) if args.prune_extra else []
        except StructureError as err:
            print(f"{path.name}: {err}")
            problems += 1
            continue

        if added or removed:
            write(path, data)
            changed += 1
            for key in added:
                print(f"{path.name}: added {key}")
            for key in removed:
                print(f"{path.name}: removed {key}")

        # Re-check after the repair, so an operation that fixes one thing and
        # leaves another is still reported as drifted.
        missing = reference_keys - flatten(data)
        extra = flatten(data) - reference_keys
        if missing or extra:
            problems += 1
            report(path.name, missing, extra)

    print()
    if problems:
        print(
            f"{problems} of {len(files)} files drifted from strings.json ({len(reference_keys)} paths)"
        )
        return 1
    if changed:
        print(
            f"updated {changed} of {len(files)} files; {len(reference_keys)} paths now match"
        )
        return 0
    print(f"{len(files)} files match strings.json ({len(reference_keys)} key paths)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
