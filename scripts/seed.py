#!/usr/bin/env python3
"""Seed sample data and optionally generate a schedule (local/mock)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.services import sample_data, scheduler  # noqa: E402


def main() -> None:
    result = sample_data.seed_sample_data(reset=True)
    week = result["weekId"]
    sched = scheduler.generate_schedule(week, save=True)
    enriched = scheduler.enrich_schedule(sched)
    print(json.dumps({
        "weekId": week,
        "employees": len(result["employees"]),
        "days": list(enriched["enriched"].keys()),
        "shiftCounts": sched.get("shiftCounts"),
        "warnings": enriched.get("warnings"),
        "weekend": {
            "שישי": enriched["enriched"].get("שישי"),
            "שבת": enriched["enriched"].get("שבת"),
        },
        "sampleDay": {
            day: enriched["enriched"][day]
            for day in list(enriched["enriched"])[:2]
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
