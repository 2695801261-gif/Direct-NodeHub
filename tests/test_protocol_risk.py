import unittest

from direct_nodehub.collector import candidate_id

from direct_nodehub.protocol import to_mihomo_proxy, select_protocol_candidates, worker_compatible_ws, worker_compatible_tcp_bridge
from direct_nodehub.risk import classify
from direct_nodehub import publish
from direct_nodehub.stability import upload_metric, download_metric, latency_metric


class ProtocolRiskTests(unittest.TestCase):
    def test_candidate_id_ignores_uri_query_parameter_order_and_fragment(self):
        first = {
            "uri": "vless://123e4567-e89b-12d3-a456-426614174000@edge.example:443?security=tls&type=ws&path=%2Fws&sni=edge.example#one"
        }
        second = {
            "uri": "vless://123e4567-e89b-12d3-a456-426614174000@edge.example:443?sni=edge.example&path=%2Fws&type=ws&security=tls#two"
        }
        self.assertEqual(candidate_id(first), candidate_id(second))

    def test_vless_reality(self):
        candidate = {
            "id": "x",
            "name": "edge",
            "uri": "vless://123e4567-e89b-12d3-a456-426614174000@example.com:443?encryption=none&security=reality&sni=www.example.com&fp=chrome&pbk=PUBKEY&sid=abcd&type=tcp#edge",
        }
        node = to_mihomo_proxy(candidate)
        self.assertEqual(node["type"], "vless")
        self.assertTrue(node["tls"])
        self.assertEqual(node["reality-opts"]["public-key"], "PUBKEY")

    def test_yaml_config_preserved(self):
        node = to_mihomo_proxy({
            "id": "a",
            "name": "x",
            "config": {
                "type": "ss",
                "server": "1.2.3.4",
                "port": 443,
                "cipher": "aes-128-gcm",
                "password": "p",
            },
        })
        self.assertEqual(node["server"], "1.2.3.4")
        self.assertEqual(node["name"], "x")

    def test_unknown_scheme_rejected(self):
        with self.assertRaises(ValueError):
            to_mihomo_proxy({"id": "a", "uri": "wireguard://bad"})

    def test_tor_blocked(self):
        self.assertEqual(classify("8.8.8.8", set(), {"8.8.8.8"})["risk_status"], "blocked")

    def test_unlisted_quarantined(self):
        self.assertEqual(classify("1.1.1.1", set(), set())["risk_status"], "unconfirmed")

    def test_missing_ip_unknown(self):
        self.assertEqual(classify(None, set(), set())["risk_status"], "unknown")

    def test_upload_metric_reads_successful_upload(self):
        result = {"http_checks": [{"url": "cloudflare-64KiB-upload", "status": "ok", "upload_kbps": 42.5}]}
        self.assertEqual(upload_metric(result), 42.5)

    def test_upload_metric_rejects_failed_upload(self):
        result = {"http_checks": [{"url": "cloudflare-64KiB-upload", "status": "failed", "upload_kbps": 99}]}
        self.assertEqual(upload_metric(result), 0.0)

    def test_download_metric_reads_successful_download(self):
        result = {"http_checks": [{"url": "cloudflare-256KiB-download", "status": "ok", "download_kbps": 128}]}
        self.assertEqual(download_metric(result), 128.0)

    def test_latency_metric_requires_two_successful_echoes(self):
        result = {"http_checks": [
            {"url": "https://api.ipify.org", "status": "ok", "latency_ms": 80},
            {"url": "https://ifconfig.me/ip", "status": "failed", "latency_ms": 3000},
            {"url": "https://icanhazip.com", "status": "ok", "latency_ms": 120},
        ]}
        self.assertEqual(latency_metric(result), 100.0)

    def test_latency_metric_rejects_single_echo(self):
        result = {"http_checks": [
            {"url": "https://api.ipify.org", "status": "ok", "latency_ms": 80},
            {"url": "https://ifconfig.me/ip", "status": "failed", "latency_ms": 3000},
        ]}
        self.assertIsNone(latency_metric(result))


    def test_protocol_probe_reserves_slots_for_websocket(self):
        nodes = [
            {"id": "tcp-1", "cloud_tcp_latency_ms": 1, "config": {"type": "ss", "network": "tcp"}},
            {"id": "ws-1", "cloud_tcp_latency_ms": 50, "config": {"type": "vless", "network": "ws"}},
            {"id": "tcp-2", "cloud_tcp_latency_ms": 2, "config": {"type": "ss", "network": "tcp"}},
            {"id": "ws-2", "cloud_tcp_latency_ms": 60, "config": {"type": "trojan", "network": "ws"}},
            {"id": "tcp-3", "cloud_tcp_latency_ms": 3, "config": {"type": "ss", "network": "tcp"}},
        ]
        selected = select_protocol_candidates(nodes, max_candidates=3, websocket_quota=2)
        self.assertEqual([node["id"] for node in selected], ["ws-1", "ws-2", "tcp-1"])

    def test_worker_compatible_tls_vless_tcp_bridge(self):
        candidate = {
            "id": "tcp",
            "config": {
                "type": "vless",
                "network": "tcp",
                "tls": True,
                "server": "origin.example",
                "servername": "origin.example",
                "uuid": "123e4567-e89b-12d3-a456-426614174000",
            },
        }
        self.assertTrue(worker_compatible_tcp_bridge(candidate))

    def test_worker_tcp_bridge_rejects_reality_and_ip_sni_mismatch(self):
        reality = {
            "id": "reality",
            "config": {
                "type": "vless",
                "network": "tcp",
                "tls": True,
                "server": "origin.example",
                "servername": "origin.example",
                "reality-opts": {"public-key": "key"},
            },
        }
        ip_host = {
            "id": "ip",
            "config": {
                "type": "vless",
                "network": "tcp",
                "tls": True,
                "server": "203.0.113.10",
                "servername": "origin.example",
            },
        }
        self.assertFalse(worker_compatible_tcp_bridge(reality))
        self.assertFalse(worker_compatible_tcp_bridge(ip_host))

    def test_worker_compatible_tls_websocket(self):
        candidate = {
            "id": "ws",
            "config": {
                "type": "vless",
                "network": "ws",
                "tls": True,
                "server": "edge.example",
                "servername": "edge.example",
                "ws-opts": {"path": "/ws", "headers": {"Host": "edge.example"}},
            },
        }
        self.assertTrue(worker_compatible_ws(candidate))

    def test_worker_rejects_mismatched_upstream_host_or_sni(self):
        candidate = {
            "id": "ws",
            "config": {
                "type": "vless",
                "network": "ws",
                "tls": True,
                "server": "origin.example",
                "servername": "front.example",
                "ws-opts": {"path": "/ws", "headers": {"Host": "front.example"}},
            },
        }
        self.assertFalse(worker_compatible_ws(candidate))

    def test_worker_rejects_unforwarded_websocket_headers(self):
        candidate = {
            "id": "ws",
            "config": {
                "type": "vless",
                "network": "ws",
                "tls": True,
                "server": "edge.example",
                "servername": "edge.example",
                "ws-opts": {"path": "/ws", "headers": {"Host": "edge.example", "Origin": "https://other.example"}},
            },
        }
        self.assertFalse(worker_compatible_ws(candidate))

    def test_protocol_probe_prioritizes_worker_tcp_bridge_candidates(self):
        nodes = [
            {"id": "ordinary", "cloud_tcp_latency_ms": 1, "config": {"type": "ss", "network": "tcp"}},
            {"id": "bridge", "cloud_tcp_latency_ms": 100, "config": {
                "type": "vless", "network": "tcp", "tls": True,
                "server": "origin.example", "servername": "origin.example",
            }},
        ]
        selected = select_protocol_candidates(nodes, max_candidates=2, websocket_quota=0)
        self.assertEqual([node["id"] for node in selected], ["bridge", "ordinary"])

    def test_protocol_probe_respects_total_limit(self):
        nodes = [
            {"id": f"ws-{i}", "cloud_tcp_latency_ms": i, "config": {"type": "vless", "network": "ws"}}
            for i in range(10)
        ]
        selected = select_protocol_candidates(nodes, max_candidates=4, websocket_quota=20)
        self.assertEqual(len(selected), 4)

    def test_cloud_test_url_is_not_google_gstatic(self):
        self.assertEqual(publish.URL_TEST, "https://cp.cloudflare.com/generate_204")


if __name__ == "__main__":
    unittest.main()
