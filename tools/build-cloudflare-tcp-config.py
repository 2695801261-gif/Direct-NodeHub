from __future__ import annotations

import argparse
import getpass
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from direct_nodehub.protocol import to_mihomo_proxy, worker_compatible_tcp_bridge  # noqa: E402

CANDIDATES = ROOT / "public" / "candidates.json"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a private Mihomo config for the experimental Cloudflare WS-to-TCP bridge."
    )
    parser.add_argument("--candidate-id", help="specific eligible candidate ID; default chooses the best cloud-ranked candidate")
    parser.add_argument("--worker-host", help="deployed Worker hostname, without scheme or path; omit to print upstream settings before deployment")
    parser.add_argument("--output", default="cloudflare-tcp-bridge.yaml", help="private local output file")
    args = parser.parse_args()

    data = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    eligible = [
        node for node in data.get("candidates", [])
        if node.get("protocol_status") == "verified"
        and node.get("stable_status") == "stable"
        and node.get("risk_policy_decision") == "eligible_for_unconfirmed_pool"
        and worker_compatible_tcp_bridge(node)
    ]
    eligible.sort(key=lambda node: (
        float(node.get("median_latency_ms") or 1e9),
        -float(node.get("median_download_kbps") or 0),
    ))
    if args.candidate_id:
        selected = next((node for node in eligible if node.get("id") == args.candidate_id), None)
        if selected is None:
            raise SystemExit("The requested candidate is not currently verified, stable, risk-eligible and TCP-bridge-compatible.")
    else:
        if not eligible:
            raise SystemExit("No eligible TLS TCP upstream exists in the current candidate snapshot.")
        selected = eligible[0]

    upstream = to_mihomo_proxy(selected)
    upstream_host = str(upstream["server"])
    upstream_port = int(upstream["port"])
    upstream_tls = bool(upstream.get("tls")) or str(upstream.get("type", "")).lower() == "trojan"

    if not args.worker_host:
        print(json.dumps({
            "selected_candidate_id": selected["id"],
            "selected_candidate_name": selected.get("name"),
            "upstream_protocol": upstream.get("type"),
            "upstream_exit_ip": selected.get("exit_ip"),
            "cloud_latency_ms": selected.get("median_latency_ms"),
            "UPSTREAM_HOST": upstream_host,
            "UPSTREAM_PORT": upstream_port,
            "UPSTREAM_TLS": "true" if upstream_tls else "false",
            "next": "Deploy worker-ws-tcp-bridge.js with these variables and a private RELAY_TOKEN. Then rerun with --worker-host.",
        }, ensure_ascii=False, indent=2))
        return 0

    worker_host = args.worker_host.strip().lower()
    if not re.fullmatch(r"[a-z0-9.-]+", worker_host) or worker_host.startswith(".") or worker_host.endswith("."):
        raise SystemExit("Worker host must be a plain DNS hostname, not a URL.")
    token = getpass.getpass("Enter the Worker RELAY_TOKEN (input hidden): ").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{24,128}", token):
        raise SystemExit("RELAY_TOKEN must contain 24–128 URL-safe characters.")

    client = dict(upstream)
    client["name"] = "Cloudflare-TCP-" + str(selected.get("id"))
    client["server"] = worker_host
    client["port"] = 443
    client["network"] = "ws"
    client["tls"] = True
    client["servername"] = worker_host
    client["ws-opts"] = {
        "path": "/" + token,
        "headers": {"Host": worker_host},
    }
    client.pop("skip-cert-verify", None)

    proxy_name = client["name"]
    config = {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "warning",
        "ipv6": False,
        "proxies": [client],
        "proxy-groups": [
            {"name": "Cloudflare-TCP中转", "type": "select", "proxies": [proxy_name, "DIRECT"]},
            {"name": "PROXY", "type": "select", "proxies": ["Cloudflare-TCP中转", "DIRECT"]},
        ],
        "rules": ["MATCH,PROXY"],
    }
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")

    print(json.dumps({
        "selected_candidate_id": selected["id"],
        "selected_candidate_name": selected.get("name"),
        "upstream_protocol": upstream.get("type"),
        "upstream_exit_ip": selected.get("exit_ip"),
        "cloud_latency_ms": selected.get("median_latency_ms"),
        "private_client_config": str(output),
        "warning": "Keep this YAML private: it contains the relay token. Cloud measurements are not mainland-China measurements.",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
