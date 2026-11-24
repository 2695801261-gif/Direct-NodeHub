import unittest
from direct_nodehub.mainland_report import validate_report


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


if __name__ == "__main__":
    unittest.main()
