from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports" / "mainland"


def validate_report(report: dict[str, Any]) -> None:
    required = {"schema_version", "probe_location", "tested_at", "probe_id", "results"}
    missing = required - set(report)
    if missing:
        raise ValueError(f"missing fields: {', '.join(sorted(missing))}")
    if report["schema_version"] != 1:
        raise ValueError("unsupported report schema")
    if report["probe_location"] != "mainland_china":
        raise ValueError("probe_location must be mainland_china")
    if not isinstance(report["results"], list):
        raise ValueError("results must be a list")
    for item in report["results"]:
        if not isinstance(item, dict) or not item.get("id"):
            raise ValueError("each result requires a candidate id")
        if item.get("status") not in {"reachable", "failed"}:
            raise ValueError("status must be reachable or failed")
        if item.get("status") == "reachable" and not isinstance(item.get("latency_ms"), (int, float)):
            raise ValueError("reachable result requires numeric latency_ms")


def import_report(path: Path) -> int:
    report = json.loads(path.read_text(encoding="utf-8"))
    validate_report(report)
    REPORTS.mkdir(parents=True, exist_ok=True)
    target = REPORTS / f"{report['probe_id']}-{report['tested_at'][:10]}.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(report["results"])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m direct_nodehub.mainland_report REPORT.json")
    print(f"Imported {import_report(Path(sys.argv[1]))} mainland test results.")
