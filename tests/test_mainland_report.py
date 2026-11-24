import unittest
from direct_nodehub.mainland_report import validate_report
from direct_nodehub.mainland_probe import result_metrics


class MainlandReportTests(unittest.TestCase):
    def test_accept_valid_report(self):
        validate_report({
            "schema_version": 1,
            "probe_location": "mainland_china",
            "tested_at": "2026-11-24T10:00:00Z",
            "probe_id": "home-test",
            "results": [{"id": "abc", "status": "reachable", "latency_ms": 123.4}]
        })

    def test_reject_cloud_claiming_mainland(self):
        with self.assertRaises(ValueError):
            validate_report({
                "schema_version": 1,
                "probe_location": "cloud",
                "tested_at": "2026-11-24T10:00:00Z",
                "probe_id": "runner",
                "results": []
            })


    def test_mainland_latency_rejects_single_echo_service(self):
        latency, download, upload = result_metrics({"http_checks": [
            {"url": "https://api.ipify.org", "status": "ok", "latency_ms": 120},
            {"url": "https://ifconfig.me/ip", "status": "failed", "latency_ms": 6000},
            {"url": "cloudflare-256KiB-download", "status": "ok", "download_kbps": 300},
            {"url": "cloudflare-64KiB-upload", "status": "ok", "upload_kbps": 80}
        ]})
        self.assertEqual(latency, 0.0)

    def test_extract_bidirectional_metrics(self):
        latency, download, upload = result_metrics({"http_checks": [
            {"url": "https://api.ipify.org", "status": "ok", "latency_ms": 120},
            {"url": "https://ifconfig.me/ip", "status": "ok", "latency_ms": 140},
            {"url": "cloudflare-256KiB-download", "status": "ok", "download_kbps": 300},
            {"url": "cloudflare-64KiB-upload", "status": "ok", "upload_kbps": 80}
        ]})
        self.assertEqual(latency, 130)
        self.assertEqual(download, 300)
        self.assertEqual(upload, 80)
if __name__ == "__main__":
    unittest.main()
