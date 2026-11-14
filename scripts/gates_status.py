#!/usr/bin/env python3
"""Report gate file age/status/freshness and whether the scheduler is alive."""

from __future__ import annotations

import json
import sys

from pionex_trading_skills.status import collect


def main() -> int:
    report = collect()
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if not report.get("scheduler", {}).get("alive"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
