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

from direct_nodehub.protocol import to_mihomo_proxy, worker_compatible_ws  # noqa: E402

CANDIDATES = ROOT / "public" / "candidates.json"
URL_TEST = "https://cp.cloudflare.com/generate_204"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a private Mihomo config for a verified Cloudflare WS relay."
    )
    parser.add_argument("--candidate-id", help="specific eligible candidate ID; default chooses the best cloud-ranked candidate")
    parser.add_argument("--worker-host", help="deployed Worker hostname, without scheme or path; omit to print the upstream URL before deployment")
    parser.add_argument("--output", default="cloudflare-relay.yaml", help="private local output file")
    args = parser.parse_args()

    data = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    eligible = [
        node for node in data.get("candidates", [])
        if node.get("protocol_status") == "verified"
        and node.get("stable_status") == "stable"
        and node.get("risk_policy_decision") == "eligible_for_unconfirmed_pool"
        and worker_compatible_ws(node)
    ]
    eligible.sort(key=lambda node: (
        float(node.get("median_latency_ms") or 1e9),
        -float(node.get("median_download_kbps") or 0),
    ))
    if args.candidate_id:
        selected = next((node for node in eligible if node.get("id") == args.candidate_id), None)
        if selected is None:
            raise SystemExit("The requested candidate is not currently verified, stable, risk-eligible and Worker-compatible.")
    else:
        if not eligible:
            raise SystemExit("No eligible Cloudflare WebSocket upstream exists in the current candidate snapshot.")
        selected = eligible[0]

    upstream = to_mihomo_proxy(selected)
    upstream_host = str(upstream["server"])
    upstream_port = int(upstream["port"])
    upstream_path = str(upstream.get("ws-opts", {}).get("path") or "/")
    if not upstream_path.startswith("/"):
        upstream_path = "/" + upstream_path
    upstream_url = f"https://{upstream_host}:{upstream_port}{upstream_path}"

    if not args.worker_host:
        print(json.dumps({
            "selected_candidate_id": selected["id"],
            "selected_candidate_name": selected.get("name"),
            "upstream_exit_ip": selected.get("exit_ip"),
            "cloud_latency_ms": selected.get("median_latency_ms"),
            "upstream_url_for_cloudflare_worker": upstream_url,
            "next": "Create a Worker from cloudflare/worker-ws-relay.js, set UPSTREAM_URL to the value above, and add a private RELAY_TOKEN. Then rerun this script with --worker-host.",
        }, ensure_ascii=False, indent=2))
        return 0

    worker_host = args.worker_host.strip().lower()
    if not re.fullmatch(r"[a-z0-9.-]+", worker_host) or worker_host.startswith(".") or worker_host.endswith("."):
        raise SystemExit("Worker host must be a plain DNS hostname, not a URL.")
    token = getpass.getpass("Enter the Worker RELAY_TOKEN (input hidden): ").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{24,128}", token):
        raise SystemExit("RELAY_TOKEN must contain 24–128 URL-safe characters.")

    client = dict(upstream)
    client["name"] = "Cloudflare-WS-" + str(selected.get("id"))
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
            {"name": "Cloudflare中转", "type": "select", "proxies": [proxy_name, "DIRECT"]},
            {"name": "PROXY", "type": "select", "proxies": ["Cloudflare中转", "DIRECT"]},
        ],
        "rules": ["MATCH,PROXY"],
    }
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")

    print(json.dumps({
        "selected_candidate_id": selected["id"],
        "selected_candidate_name": selected.get("name"),
        "upstream_exit_ip": selected.get("exit_ip"),
        "cloud_latency_ms": selected.get("median_latency_ms"),
        "upstream_url_for_cloudflare_worker": upstream_url,
        "private_client_config": str(output),
        "warning": "Keep this YAML private: it contains the relay token. Cloud measurements are not mainland-China measurements.",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
