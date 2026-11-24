from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from direct_nodehub.protocol import verify_one

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "public" / "candidates.json"
POLICY = ROOT / "config" / "policy.json"
OUTPUT_DIR = ROOT / "reports" / "mainland"


def result_metrics(result: dict[str, Any]) -> tuple[float, float, float]:
    checks = result.get("http_checks", [])
    download = next((float(x.get("download_kbps", 0)) for x in checks
                     if x.get("url") == "cloudflare-256KiB-download" and x.get("status") == "ok"), 0.0)
    upload = next((float(x.get("upload_kbps", 0)) for x in checks
                   if x.get("url") == "cloudflare-64KiB-upload" and x.get("status") == "ok"), 0.0)
    latencies = [float(x["latency_ms"]) for x in checks
                 if x.get("url") in {"https://api.ipify.org", "https://ifconfig.me/ip", "https://icanhazip.com"}
                 and x.get("status") == "ok" and isinstance(x.get("latency_ms"), (int, float))]
    latency = statistics.median(latencies) if latencies else 0.0
    return latency, download, upload


def test_candidate(node: dict[str, Any], binary: str, index: int, rounds: int,
                   min_download: float, min_upload: float, max_latency: float) -> dict[str, Any]:
    attempts = []
    for attempt in range(rounds):
        result = verify_one(node, binary, preferred_port=30000 + index * rounds + attempt)
        latency, download, upload = result_metrics(result)
        attempts.append({
            "round": attempt + 1,
            "ok": result.get("protocol_status") == "verified" and latency > 0 and latency <= max_latency and download >= min_download and upload >= min_upload,
            "exit_ip": result.get("exit_ip"),
            "protocol_status": result.get("protocol_status"),
            "latency_ms": round(latency, 1) if latency else None,
            "download_kbps": download,
            "upload_kbps": upload,
            "error": result.get("error")
        })
    successful = [x for x in attempts if x["ok"]]
    exit_ips = {x["exit_ip"] for x in successful}
    passed = len(successful) == rounds and len(exit_ips) == 1
    latency_values = [x["latency_ms"] for x in successful if x["latency_ms"] is not None]
    return {
        "id": node["id"],
        "status": "reachable" if passed else "failed",
        "latency_ms": round(statistics.median(latency_values), 1) if latency_values else None,
        "successful_rounds": len(successful),
        "total_rounds": rounds,
        "same_exit_ip": len(exit_ips) == 1,
        "exit_ip": next(iter(exit_ips)) if len(exit_ips) == 1 else None,
        "download_kbps": round(statistics.median([x["download_kbps"] for x in successful]), 1) if successful else 0,
        "upload_kbps": round(statistics.median([x["upload_kbps"] for x in successful]), 1) if successful else 0,
        "rounds": attempts
    }


def run(args: argparse.Namespace) -> Path:
    if not args.confirm_mainland:
        raise SystemExit("Refusing to label this as mainland China: rerun with --confirm-mainland only while physically on a mainland China network with other VPN/proxies disabled.")
    if not CANDIDATES.exists():
        raise FileNotFoundError("public/candidates.json missing; download the repository's current public/candidates.json first.")
    binary = os.environ.get("MIHOMO_BIN") or shutil.which("mihomo")
    if not binary:
        raise RuntimeError("Mihomo binary not found. Set MIHOMO_BIN to the official Mihomo executable.")
    data = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    settings = policy.get("stability", {})
    rounds = max(1, min(int(args.rounds), 5))
    min_download = float(settings.get("minimum_download_kbps", 64))
    min_upload = float(settings.get("minimum_upload_kbps", 32))
    max_latency = float(policy.get("mainland_max_latency_ms", 1200))
    # Probe every cloud-stable protocol-verified candidate locally. Reputation
    # filtering is applied later only to the stable subscription, not the fast pool.
    candidates = [n for n in data.get("candidates", [])
                  if n.get("protocol_status") == "verified" and n.get("stable_status") == "stable"]
    # Cloud ranking is only a test-order hint, never a mainland latency claim.
    candidates.sort(key=lambda n: (
        float(n.get("median_latency_ms") or 1e9),
        -float(n.get("median_download_kbps") or 0),
        -float(n.get("median_upload_kbps") or 0),
    ))
    candidates = candidates[:max(1, min(int(args.limit), 60))]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(test_candidate, node, binary, i, rounds, min_download, min_upload, max_latency)
                   for i, node in enumerate(candidates)]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda x: x["id"])
    tested_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    report = {
        "schema_version": 1,
        "probe_location": "mainland_china",
        "tested_at": tested_at,
        "probe_id": args.probe_id,
        "results": results,
        "test_contract": {
            "rounds": rounds,
            "minimum_download_kib_per_second": min_download,
            "minimum_upload_kib_per_second": min_upload,
            "maximum_latency_ms": max_latency,
            "vpn_disabled_attested": True,
            "meaning": "Actual proxy tunnel and bidirectional transfer tested from the operator-confirmed mainland network."
        }
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{args.probe_id}-{tested_at[:10]}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "report": str(path.relative_to(ROOT)),
        "tested": len(results),
        "reachable": sum(x["status"] == "reachable" for x in results),
        "failed": sum(x["status"] == "failed" for x in results)
    }, ensure_ascii=False, indent=2))
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run real mainland-China Mihomo tunnel and bidirectional-transfer tests.")
    parser.add_argument("--confirm-mainland", action="store_true", help="attest that this machine is on a mainland China network with other VPN/proxies disabled")
    parser.add_argument("--limit", type=int, default=20, help="maximum stable candidates to test (1-60)")
    parser.add_argument("--rounds", type=int, default=3, help="repeat each candidate 1-5 times (default 3)")
    parser.add_argument("--probe-id", default="local-mainland-probe", help="short label for this probe device")
    run(parser.parse_args())
