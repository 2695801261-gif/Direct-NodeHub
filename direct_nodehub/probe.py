from __future__ import annotations

import concurrent.futures
import json
import socket
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "public" / "candidates.json"
PROBE_FILE = ROOT / "public" / "probe-results.json"
POLICY_FILE = ROOT / "config" / "policy.json"


def tcp_probe(node: dict[str, Any], timeout: float) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        with socket.create_connection((node["server"], int(node["port"])), timeout=timeout):
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            return {
                "id": node["id"],
                "cloud_tcp": "reachable",
                "cloud_tcp_latency_ms": elapsed,
                "cloud_probe_region": "github-hosted-runner (region not guaranteed)",
                "error": None
            }
    except (OSError, ValueError, TypeError) as exc:
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        return {
            "id": node["id"],
            "cloud_tcp": "failed",
            "cloud_tcp_latency_ms": elapsed,
            "cloud_probe_region": "github-hosted-runner (region not guaranteed)",
            "error": str(exc)[:200]
        }


def run_cloud_probes() -> dict[str, Any]:
    if not CANDIDATES.exists():
        raise FileNotFoundError("public/candidates.json missing; run collector first")
    policy = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
    data = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    nodes = data.get("candidates", [])
    timeout = float(policy.get("connect_timeout_seconds", 8))
    max_workers = min(64, max(4, len(nodes)))

    started = time.time()
    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(tcp_probe, node, timeout) for node in nodes]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda item: item["id"])
    result_map = {item["id"]: item for item in results}
    for node in nodes:
        probe = result_map.get(node["id"], {})
        node["cloud_tcp"] = probe.get("cloud_tcp", "not_tested")
        node["cloud_tcp_latency_ms"] = probe.get("cloud_tcp_latency_ms")
        node["cloud_probe_region"] = probe.get("cloud_probe_region")
        node["cloud_tcp_error"] = probe.get("error")

        # A TCP-open port is not proof that the proxy protocol or proxy tunnel works.
        node["protocol_status"] = "not_verified"
        node["mainland_status"] = "not_tested"
        node["publication_status"] = "blocked_pending_protocol_and_mainland_tests"

    data["cloud_tcp_tested_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    data["cloud_tcp_summary"] = {
        "total": len(nodes),
        "reachable": sum(1 for item in results if item["cloud_tcp"] == "reachable"),
        "failed": sum(1 for item in results if item["cloud_tcp"] == "failed"),
        "meaning": "TCP reachability only; not proxy handshake, tunnel, speed, reputation, or mainland reachability."
    }
    CANDIDATES.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    output = {
        "schema_version": 1,
        "generated_at": data["cloud_tcp_tested_at"],
        "test_tier": "cloud_tcp_only",
        "duration_seconds": round(time.time() - started, 2),
        "summary": data["cloud_tcp_summary"],
        "results": results,
        "mainland_test_contract": {
            "required_for_china_confirmed": True,
            "status_values": ["not_tested", "reachable", "failed"],
            "accepted_probe_locations": ["mainland_china"],
            "note": "Cloud runners must never write mainland_china results."
        }
    }
    PROBE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROBE_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


if __name__ == "__main__":
    result = run_cloud_probes()
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
