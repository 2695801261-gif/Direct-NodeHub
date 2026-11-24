from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from direct_nodehub.protocol import network_of, worker_compatible_ws, worker_compatible_tcp_bridge

import yaml

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "public" / "candidates.json"
OUTPUT = ROOT / "public"
POLICY = ROOT / "config" / "policy.json"
URL_TEST = "https://cp.cloudflare.com/generate_204"


def clean_name(value: Any) -> str:
    name = re.sub(r"[\x00-\x1f,]", " ", str(value or "node")).strip()
    return name[:80] or "node"


def build_config(node: dict[str, Any]) -> dict[str, Any]:
    if isinstance(node.get("config"), dict):
        config = dict(node["config"])
    else:
        from direct_nodehub.protocol import to_mihomo_proxy
        config = to_mihomo_proxy(node)
    config["name"] = clean_name(node.get("name") or node.get("id"))
    return config


def unique_configs(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    used_names = set()
    seen_configs = set()
    for node in nodes:
        config = build_config(node)
        # Different source labels/fragments can describe the exact same proxy.
        # Remove exact duplicates before publishing so clients do not show
        # multiple identical entries as if they were independent working nodes.
        fingerprint_data = dict(config)
        fingerprint_data.pop("name", None)
        fingerprint = json.dumps(
            fingerprint_data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        if fingerprint in seen_configs:
            continue
        seen_configs.add(fingerprint)

        base = config["name"]
        name = base
        index = 2
        while name in used_names:
            name = f"{base}-{index}"
            index += 1
        config["name"] = name
        used_names.add(name)
        result.append(config)
    return result


def latency_of(node: dict[str, Any]) -> float:
    value = node.get("median_latency_ms")
    return float(value) if isinstance(value, (int, float)) else float("inf")


def download_of(node: dict[str, Any]) -> float:
    return float(node.get("median_download_kbps") or 0)


def upload_of(node: dict[str, Any]) -> float:
    return float(node.get("median_upload_kbps") or 0)


def eligible_stable_nodes(nodes: list[dict[str, Any]], max_latency: float) -> list[dict[str, Any]]:
    selected = [
        node for node in nodes
        if node.get("protocol_status") == "verified"
        and node.get("stable_status") == "stable"
        and node.get("risk_status") != "blocked"
        and node.get("risk_policy_decision") == "eligible_for_unconfirmed_pool"
        and latency_of(node) <= max_latency
    ]
    return sorted(selected, key=lambda node: (latency_of(node), -download_of(node), -upload_of(node)))


def run() -> dict[str, Any]:
    data = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    nodes = data.get("candidates", [])
    ws_nodes = [node for node in nodes if network_of(node) == "ws"]
    ws_verified_stable = [
        node for node in ws_nodes
        if node.get("protocol_status") == "verified" and node.get("stable_status") == "stable"
    ]
    ws_worker_compatible = [node for node in ws_nodes if worker_compatible_ws(node)]
    ws_worker_compatible_stable = [
        node for node in ws_verified_stable
        if worker_compatible_ws(node)
        and node.get("risk_status") != "blocked"
        and node.get("risk_policy_decision") == "eligible_for_unconfirmed_pool"
    ]
    tcp_bridge_candidates = [node for node in nodes if worker_compatible_tcp_bridge(node)]
    tcp_bridge_verified_stable = [
        node for node in tcp_bridge_candidates
        if node.get("protocol_status") == "verified"
        and node.get("stable_status") == "stable"
        and node.get("risk_status") != "blocked"
        and node.get("risk_policy_decision") == "eligible_for_unconfirmed_pool"
    ]
    cloudflare_relay_status = {
        "websocket_candidates": len(ws_nodes),
        "protocol_verified_and_stable": len(ws_verified_stable),
        "worker_compatible_candidates": len(ws_worker_compatible),
        "worker_compatible_verified_and_stable": len(ws_worker_compatible_stable),
        "eligible_candidate_ids": [node["id"] for node in ws_worker_compatible_stable[:10]],
        "meaning": "WebSocket-to-WebSocket relay eligibility only; Worker must still be deployed and tested from the actual client network.",
    }
    cloudflare_tcp_bridge_status = {
        "eligible_tls_tcp_candidates": len(tcp_bridge_candidates),
        "protocol_verified_and_stable": len(tcp_bridge_verified_stable),
        "eligible_candidate_ids": [node["id"] for node in tcp_bridge_verified_stable[:10]],
        "meaning": "TLS TCP VLESS/VMess/Trojan only; excludes Reality, XTLS Vision, UDP and upstream WebSocket. Worker must still be deployed and tested from the actual client network.",
    }
    limit = int(policy.get("publication", {}).get("max_nodes", 100))
    stability = policy.get("stability", {})
    max_latency = float(stability.get("max_latency_ms", policy.get("max_cloud_latency_ms", 1000)))
    fast_download = float(stability.get("fast_pool_minimum_download_kbps", 512))
    fast_upload = float(stability.get("fast_pool_minimum_upload_kbps", 128))

    # The stable pool is reputation-screened; the fast pool intentionally is not.
    cloud_stable = [
        node for node in nodes
        if node.get("protocol_status") == "verified"
        and node.get("stable_status") == "stable"
        and latency_of(node) <= max_latency
    ]
    stable = [
        node for node in cloud_stable
        if node.get("risk_status") != "blocked"
        and node.get("risk_policy_decision") == "eligible_for_unconfirmed_pool"
    ]
    stable.sort(key=lambda node: (latency_of(node), -download_of(node), -upload_of(node)))
    screened = [node for node in stable if node.get("risk_status") == "unconfirmed"]
    fast = [
        node for node in cloud_stable
        if download_of(node) >= fast_download and upload_of(node) >= fast_upload
    ]
    fast.sort(key=lambda node: (-download_of(node), latency_of(node), -upload_of(node)))
    # Deduplicate before applying the publication cap so repeated source
    # entries do not crowd out distinct working configurations.
    configs = unique_configs(screened)[:limit]
    names = [node["name"] for node in configs]
    standard = {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "warning",
        "ipv6": False,
        "proxies": configs,
        "proxy-groups": [
            {"name": "节点手动选择", "type": "select", "proxies": names + ["DIRECT"]},
            {"name": "节点自动优选", "type": "url-test", "url": URL_TEST, "interval": 300, "tolerance": 80, "lazy": True, "proxies": names or ["DIRECT"]},
            {"name": "节点故障切换", "type": "fallback", "url": URL_TEST, "interval": 180, "lazy": True, "proxies": names or ["DIRECT"]},
            {"name": "PROXY", "type": "select", "proxies": ["节点自动优选", "节点故障切换", "节点手动选择", "DIRECT"]},
        ],
        "rules": ["MATCH,PROXY"],
    }
    (OUTPUT / "clash.yaml").write_text(
        yaml.safe_dump(standard, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    fast_configs = unique_configs(fast)[:limit]
    fast_names = [node["name"] for node in fast_configs]
    fast_yaml = {
        "mixed-port": 7891,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "warning",
        "ipv6": False,
        "proxies": fast_configs,
        "proxy-groups": [
            {"name": "高速手动选择", "type": "select", "proxies": fast_names + ["DIRECT"]},
            {"name": "高速自动优选", "type": "url-test", "url": URL_TEST, "interval": 300, "tolerance": 80, "lazy": True, "proxies": fast_names or ["DIRECT"]},
            {"name": "PROXY", "type": "select", "proxies": ["高速自动优选", "高速手动选择", "DIRECT"]},
        ],
        "rules": ["MATCH,PROXY"],
    }
    (OUTPUT / "fast.yaml").write_text(
        yaml.safe_dump(fast_yaml, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    chain_configs = unique_configs(stable)[:limit]
    chain_names = [node["name"] for node in chain_configs]
    home = {
        "name": "HOME-RESIDENTIAL-REPLACE-ME",
        "type": "socks5",
        "server": "YOUR_HOME_HOST",
        "port": 1080,
        "username": "YOUR_USERNAME",
        "password": "YOUR_PASSWORD",
        "dialer-proxy": "ENTRY-AUTO",
    }
    chain = {
        "mixed-port": 7892,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "warning",
        "ipv6": False,
        "proxies": chain_configs + [home],
        "proxy-groups": [
            {"name": "ENTRY-AUTO", "type": "url-test", "url": URL_TEST, "interval": 180, "tolerance": 100, "lazy": True, "proxies": chain_names or ["DIRECT"]},
            {"name": "HOME-CHAIN", "type": "select", "proxies": ["HOME-RESIDENTIAL-REPLACE-ME"]},
        ],
        "rules": ["MATCH,HOME-CHAIN"],
    }
    (OUTPUT / "chain-template.yaml").write_text(
        yaml.safe_dump(chain, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    summary = {
        "reputation_screened_stable_nodes": len(configs),
        "fast_stable_nodes": len(fast_configs),
        "chain_entry_nodes": len(chain_configs),
        "chain_template": "public/chain-template.yaml",
        "standard_gate": f"3/3 repeated Mihomo tunnel tests, consistent exit IP, median cloud latency <= {max_latency:g} ms, download >= 128 KiB/s, upload >= 32 KiB/s, risk feeds available and no known-bad match",
        "fast_gate": f"protocol verified, 3/3 stable rounds, cloud latency <= {max_latency:g} ms, download >= {fast_download:g} KiB/s and upload >= {fast_upload:g} KiB/s; no reputation-list filtering",
        "url_test": URL_TEST,
        "test_scope": "GitHub-hosted runner only; not a mainland-China measurement",
        "mainland_status": "not_tested",
        "warning": "Cloud-side validation cannot guarantee reachability or latency from mainland China. Free public nodes may stop working at any time.",
    }
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    status = {
        "generated_at": stamp,
        "summary": summary,
        "cloud_tcp": data.get("cloud_tcp_summary"),
        "protocol": data.get("protocol_summary"),
        "risk": data.get("risk_summary"),
        "stability": data.get("stability_summary"),
        "sources": data.get("sources", []),
        "cloudflare_ws_relay": cloudflare_relay_status,
        "cloudflare_tcp_bridge": cloudflare_tcp_bridge_status,
    }
    (OUTPUT / "status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    html = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Direct-NodeHub 节点状态</title>
<style>
:root{color-scheme:dark}body{font:16px system-ui;background:#101722;color:#e7edf5;max-width:760px;margin:30px auto;padding:0 18px}
section{background:#1b2735;padding:16px;border-radius:12px;margin:14px 0}a{color:#8cc8ff}small,.muted{color:#aab7c7}
li{margin:10px 0}.warn{color:#ffd18a}
</style>
</head>
<body>
<h1>Direct-NodeHub</h1>
<p>自动采集 · 协议验证 · 重复稳定性测试</p>
<section><h2>订阅文件</h2>
<ul>
<li><a href="clash.yaml">云端复测稳定池（Clash / Mihomo）</a></li>
<li><a href="fast.yaml">云端高速池（不做信誉名单筛选；非大陆实测）</a></li>
<li><a href="chain-template.yaml">个人家宽链式模板</a></li>
<li><a href="status.json">完整状态 JSON</a></li>
</ul></section>
<section><h2>验证范围</h2>
<p class="warn">注意：以上是 GitHub 云端运行器的测试结果，不代表中国大陆网络实测。大陆延迟、运营商阻断和本地可用性尚未验证。</p>
<p class="muted">节点可能随时失效。不要用于敏感账号、支付或其他高风险用途。</p>
</section>
<section><h2>中国大陆本地实测</h2>
<p>如果你在中国大陆使用，请先运行本地实测工具。它会逐个建立真实代理隧道、连续测试三轮，并分别生成大陆稳定池和高速池。</p>
<ul>
<li><a href="https://github.com/2695801261-gif/Direct-NodeHub/blob/main/tools/README-mainland.md">Windows 实测操作说明</a></li>
<li><a href="https://github.com/2695801261-gif/Direct-NodeHub/archive/refs/heads/main.zip">下载完整实测工具包</a></li>
</ul>
<p class="muted">实测前必须关闭其他 VPN、代理客户端和系统代理；不要把云端延迟当作大陆延迟。</p>
</section>
<section><h2>Cloudflare 中转实验</h2>
<p>只有通过协议、稳定性和上游兼容性筛选的节点才会列为中转候选。中转不会改变出口 IP，也不保证降低延迟；请先阅读部署限制并在实际网络测试。</p>
<ul><li><a href="https://github.com/2695801261-gif/Direct-NodeHub/blob/main/cloudflare/README.md">Cloudflare WS 中转与 TCP 桥接说明</a></li></ul>
</section>
<section><h2>本轮数据</h2><p id="status">正在读取状态…</p></section>
<script>
fetch('status.json',{cache:'no-store'}).then(r=>r.json()).then(d=>{
 const s=d.summary||{};
 document.getElementById('status').textContent=
 '信誉筛查稳定池 '+(s.reputation_screened_stable_nodes??0)+' 个；不做信誉筛查的高速池 '+(s.fast_stable_nodes??0)+' 个；大陆实测：未完成；Cloudflare WS 中转合格候选 '+(d.cloudflare_ws_relay?.worker_compatible_verified_and_stable??0)+' 个；Cloudflare TCP 桥接合格候选 '+(d.cloudflare_tcp_bridge?.protocol_verified_and_stable??0)+' 个。更新时间：'+(d.generated_at||'未知');
 }).catch(()=>{document.getElementById('status').textContent='状态暂时不可读取。'});
</script>
</body></html>"""
    (OUTPUT / "index.html").write_text(html, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    run()
