from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from direct_nodehub.publish import URL_TEST, unique_configs

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "public" / "candidates.json"
POLICY = ROOT / "config" / "policy.json"


def select_mainland_nodes(
    candidates: list[dict[str, Any]],
    report: dict[str, Any],
    fast_download: float,
    fast_upload: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if report.get("probe_location") != "mainland_china":
        raise ValueError("report is not a mainland-China probe")
    contract = report.get("test_contract", {})
    if contract.get("vpn_disabled_attested") is not True:
        raise ValueError("report does not attest that VPN/proxy was disabled")

    result_map = {
        item["id"]: item
        for item in report.get("results", [])
        if item.get("status") == "reachable"
    }
    selected = []
    for candidate in candidates:
        result = result_map.get(candidate.get("id"))
        if not result:
            continue
        if candidate.get("protocol_status") != "verified":
            continue
        if candidate.get("stable_status") != "stable":
            continue
        if candidate.get("risk_policy_decision") != "eligible_for_unconfirmed_pool":
            continue
        node = dict(candidate)
        node["mainland_status"] = "reachable"
        node["mainland_latency_ms"] = result.get("latency_ms")
        node["mainland_download_kbps"] = float(result.get("download_kbps") or 0)
        node["mainland_upload_kbps"] = float(result.get("upload_kbps") or 0)
        selected.append(node)

    selected.sort(key=lambda node: (
        float(node.get("mainland_latency_ms") or 1e9),
        -float(node.get("mainland_download_kbps") or 0),
        -float(node.get("mainland_upload_kbps") or 0),
    ))
    fast = [
        node for node in selected
        if node["mainland_download_kbps"] >= fast_download
        and node["mainland_upload_kbps"] >= fast_upload
    ]
    fast.sort(key=lambda node: (
        -float(node.get("mainland_download_kbps") or 0),
        float(node.get("mainland_latency_ms") or 1e9),
    ))
    return selected, fast


def make_config(nodes: list[dict[str, Any]], name: str, port: int) -> dict[str, Any]:
    proxies = unique_configs(nodes)
    proxy_names = [proxy["name"] for proxy in proxies]
    group_name = f"{name}-自动优选"
    manual_name = f"{name}-手动选择"
    return {
        "mixed-port": port,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "warning",
        "ipv6": False,
        "proxies": proxies,
        "proxy-groups": [
            {"name": manual_name, "type": "select", "proxies": proxy_names + ["DIRECT"]},
            {"name": group_name, "type": "url-test", "url": URL_TEST, "interval": 300, "tolerance": 80, "lazy": True, "proxies": proxy_names or ["DIRECT"]},
            {"name": "PROXY", "type": "select", "proxies": [group_name, manual_name, "DIRECT"]},
        ],
        "rules": ["MATCH,PROXY"],
    }


def run(report_path: Path) -> dict[str, Any]:
    if not CANDIDATES.exists():
        raise FileNotFoundError("public/candidates.json is missing; use the current repository snapshot")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    candidates_data = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    stability = policy.get("stability", {})
    fast_download = float(stability.get("fast_pool_minimum_download_kbps", 512))
    fast_upload = float(stability.get("fast_pool_minimum_upload_kbps", 128))

    standard, fast = select_mainland_nodes(
        candidates_data.get("candidates", []),
        report,
        fast_download,
        fast_upload,
    )
    output_dir = report_path.parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    standard_path = output_dir / "clash-mainland.yaml"
    fast_path = output_dir / "fast-mainland.yaml"
    standard_path.write_text(
        yaml.safe_dump(make_config(standard, "大陆实测稳定", 7890), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    fast_path.write_text(
        yaml.safe_dump(make_config(fast, "大陆实测高速", 7891), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    summary = {
        "probe_id": report.get("probe_id"),
        "tested_at": report.get("tested_at"),
        "probe_location": "mainland_china",
        "mainland_confirmed_nodes": len(standard),
        "mainland_fast_nodes": len(fast),
        "standard_subscription": str(standard_path),
        "fast_subscription": str(fast_path),
        "fast_minimum_download_kbps": fast_download,
        "fast_minimum_upload_kbps": fast_upload,
        "meaning": "Only nodes that passed the actual local mainland-China tunnel and repeated transfer tests are included.",
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build local-only Clash subscriptions from a mainland-China probe report.")
    parser.add_argument("--report", required=True, type=Path, help="JSON report produced by direct_nodehub.mainland_probe")
    run(parser.parse_args().report)
