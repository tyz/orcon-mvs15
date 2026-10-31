"""Fail when any integration module is below the quality-scale coverage bar.

The integration quality scale requires more than 95% coverage in every module,
not only in total. Coverage.py can only enforce a total, so this script reads
the JSON report and checks each file separately.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

THRESHOLD = 95.0


def failing_modules(report: dict) -> list[tuple[str, float]]:
    """Return the modules that do not exceed the coverage threshold."""
    return [
        (filename, file_report["summary"]["percent_covered"])
        for filename, file_report in report["files"].items()
        if file_report["summary"]["percent_covered"] <= THRESHOLD
    ]


def main(path: Path) -> int:
    """Check a coverage JSON report and print each module below the bar."""
    report = json.loads(path.read_text())
    failures = failing_modules(report)
    for filename, percent in failures:
        print(f"{filename}: {percent:.1f}% (needs more than {THRESHOLD:.0f}%)")
    if failures:
        return 1
    print(f"All {len(report['files'])} modules are above {THRESHOLD:.0f}% coverage.")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "coverage.json")))
