from __future__ import annotations

import concurrent.futures
import json
import os
import shutil
import statistics
import time
from pathlib import Path
from typing import Any

from direct_nodehub.protocol import verify_one

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "public" / "candidates.json"
PROTOCOL = ROOT / "public" / "protocol-results.json"
OUTPUT = ROOT / "public" / "stability-results.json"
POLICY = ROOT / "config" / "policy.json"
ECHO_URLS = {
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
    "https://icanhazip.com",
}


def download_metric(result: dict[str, Any]) -> float:
    for check in result.get("http_checks", []):
        if check.get("url") == "cloudflare-256KiB-download" and check.get("status") == "ok":
            return float(check.get("download_kbps", 0))
    return 0.0


def upload_metric(result: dict[str, Any]) -> float:
    for check in result.get("http_checks", []):
        if check.get("url") == "cloudflare-64KiB-upload" and check.get("status") == "ok":
            return float(check.get("upload_kbps", 0))
    return 0.0


def latency_metric(result: dict[str, Any]) -> float | None:
    values = [
        float(check["latency_ms"])
        for check in result.get("http_checks", [])
        if check.get("url") in ECHO_URLS
        and check.get("status") == "ok"
        and isinstance(check.get("latency_ms"), (int, float))
    ]
    if len(values) < 2:
        return None
    return round(statistics.median(values), 1)


def run() -> dict[str, Any]:
    data = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    settings = policy.get("stability", {})
    rounds = max(1, min(int(settings.get("rounds", 3)), 5))
    minimum = float(settings.get("minimum_download_kbps", 64))
    minimum_upload = float(settings.get("minimum_upload_kbps", 16))
    required = max(1, min(int(settings.get("required_successful_rounds", rounds)), rounds))
    max_latency = float(settings.get("max_latency_ms", policy.get("max_cloud_latency_ms", 1000)))
    binary = os.environ.get("MIHOMO_BIN") or shutil.which("mihomo")
    if not binary:
        raise RuntimeError("mihomo binary not found for stability test")

    byid = {node["id"]: node for node in data.get("candidates", [])}
    selected = [
        byid[item["id"]]
        for item in protocol.get("results", [])
        if item.get("protocol_status") == "verified" and item.get("id") in byid
    ]

    def check(pair: tuple[int, dict[str, Any]]) -> dict[str, Any]:
        index, node = pair
        attempts = []
        for attempt in range(rounds):
            result = verify_one(
                node,
                binary,
                preferred_port=24000 + index * rounds + attempt,
            )
            latency = latency_metric(result)
            speed = download_metric(result)
            upload = upload_metric(result)
            same_protocol = result.get("protocol_status") == "verified"
            latency_ok = latency is not None and latency <= max_latency
            ok = (
                same_protocol
                and latency_ok
                and speed >= minimum
                and upload >= minimum_upload
            )
            attempts.append({
                "round": attempt + 1,
                "ok": ok,
                "protocol_status": result.get("protocol_status"),
                "exit_ip": result.get("exit_ip"),
                "exit_ip_agreement": result.get("exit_ip_agreement"),
                "latency_ms": latency,
                "latency_ok": latency_ok,
                "download_kbps": speed,
                "upload_kbps": upload,
                "error": result.get("error"),
            })

        good = [attempt for attempt in attempts if attempt["ok"]]
        ips = [attempt["exit_ip"] for attempt in good if attempt.get("exit_ip")]
        same_ip = bool(ips) and len(set(ips)) == 1
        stable = len(good) >= required and same_ip
        degraded = len(good) >= max(2, required - 1) and same_ip
        return {
            "id": node["id"],
            "stable_status": "stable" if stable else ("degraded" if degraded else "unstable"),
            "successful_rounds": len(good),
            "total_rounds": rounds,
            "same_exit_ip": same_ip,
            "median_latency_ms": round(statistics.median([a["latency_ms"] for a in good]), 1) if good else None,
            "median_download_kbps": round(statistics.median([a["download_kbps"] for a in good]), 1) if good else 0,
            "median_upload_kbps": round(statistics.median([a["upload_kbps"] for a in good]), 1) if good else 0,
            "rounds": attempts,
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(check, enumerate(selected)))

    result_map = {item["id"]: item for item in results}
    for node in data.get("candidates", []):
        result = result_map.get(node["id"])
        if result:
            node.update({key: value for key, value in result.items() if key != "rounds"})
        elif node.get("protocol_status") == "verified":
            node["stable_status"] = "not_tested"

    summary = {
        "candidates_tested": len(results),
        "stable": sum(item["stable_status"] == "stable" for item in results),
        "degraded": sum(item["stable_status"] == "degraded" for item in results),
        "unstable": sum(item["stable_status"] == "unstable" for item in results),
        "rounds": rounds,
        "required_successful_rounds": required,
        "minimum_download_kbps": minimum,
        "minimum_upload_kbps": minimum_upload,
        "maximum_cloud_latency_ms": max_latency,
        "test_region": "github-hosted-runner (region not guaranteed)",
        "meaning": "Repeated Mihomo tunnel, consistent exit IP, latency, HTTPS download and upload from GitHub-hosted runner only; not a mainland China measurement.",
    }
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    data["stability_tested_at"] = stamp
    data["stability_summary"] = summary
    CANDIDATES.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT.write_text(
        json.dumps({"schema_version": 1, "generated_at": stamp, "summary": summary, "results": results}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    run()
