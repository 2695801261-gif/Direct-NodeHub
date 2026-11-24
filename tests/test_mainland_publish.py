import unittest

from direct_nodehub.mainland_publish import select_mainland_nodes


class MainlandPublishTests(unittest.TestCase):
    def setUp(self):
        self.candidates = [
            {
                "id": "stable-a",
                "name": "A",
                "protocol_status": "verified",
                "stable_status": "stable",
                "risk_policy_decision": "eligible_for_unconfirmed_pool",
            },
            {
                "id": "unstable-b",
                "name": "B",
                "protocol_status": "verified",
                "stable_status": "degraded",
                "risk_policy_decision": "eligible_for_unconfirmed_pool",
            },
            {
                "id": "blocked-c",
                "name": "C",
                "protocol_status": "verified",
                "stable_status": "stable",
                "risk_policy_decision": "reject",
            },
        ]
        self.report = {
            "probe_location": "mainland_china",
            "test_contract": {"vpn_disabled_attested": True},
            "results": [
                {
                    "id": "stable-a",
                    "status": "reachable",
                    "latency_ms": 180,
                    "download_kbps": 900,
                    "upload_kbps": 250,
                },
                {
                    "id": "unstable-b",
                    "status": "reachable",
                    "latency_ms": 100,
                    "download_kbps": 2000,
                    "upload_kbps": 500,
                },
                {
                    "id": "blocked-c",
                    "status": "reachable",
                    "latency_ms": 90,
                    "download_kbps": 2000,
                    "upload_kbps": 500,
                },
            ],
        }

    def test_only_stable_risk_eligible_mainland_nodes_publish(self):
        standard, fast = select_mainland_nodes(self.candidates, self.report, 512, 128)
        self.assertEqual([node["id"] for node in standard], ["stable-a"])
        self.assertEqual([node["id"] for node in fast], ["blocked-c", "stable-a"])
        self.assertEqual(standard[0]["mainland_status"], "reachable")

    def test_fast_pool_uses_local_speed_thresholds(self):
        standard, fast = select_mainland_nodes(self.candidates, self.report, 1000, 128)
        self.assertEqual([node["id"] for node in standard], ["stable-a"])
        self.assertEqual([node["id"] for node in fast], ["blocked-c"])

    def test_fast_pool_does_not_apply_reputation_filter(self):
        standard, fast = select_mainland_nodes(self.candidates, self.report, 512, 128)
        self.assertNotIn("blocked-c", [node["id"] for node in standard])
        self.assertIn("blocked-c", [node["id"] for node in fast])

    def test_rejects_report_without_mainland_attestation(self):
        report = dict(self.report)
        report["test_contract"] = {"vpn_disabled_attested": False}
        with self.assertRaises(ValueError):
            select_mainland_nodes(self.candidates, report, 512, 128)


if __name__ == "__main__":
    unittest.main()
