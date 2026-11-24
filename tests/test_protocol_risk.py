import unittest

from direct_nodehub.protocol import to_mihomo_proxy
from direct_nodehub.risk import classify
from direct_nodehub import publish
from direct_nodehub.stability import upload_metric, download_metric, latency_metric


class ProtocolRiskTests(unittest.TestCase):
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

    def test_cloud_test_url_is_not_google_gstatic(self):
        self.assertEqual(publish.URL_TEST, "https://cp.cloudflare.com/generate_204")


if __name__ == "__main__":
    unittest.main()
