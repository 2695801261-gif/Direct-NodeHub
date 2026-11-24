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
            "candidate_snapshot_generated_at": "snapshot-1",
            "test_contract": {"vpn_disabled_attested": True, "rounds": 3},
            "results": [
                {
                    "id": "stable-a",
                    "status": "reachable",
                    "successful_rounds": 3,
                    "total_rounds": 3,
                    "same_exit_ip": True,
                    "exit_ip": "198.51.100.10",
                    "latency_ms": 180,
                    "download_kbps": 900,
                    "upload_kbps": 250,
                },
                {
                    "id": "unstable-b",
                    "status": "reachable",
                    "successful_rounds": 3,
                    "total_rounds": 3,
                    "same_exit_ip": True,
                    "exit_ip": "198.51.100.11",
                    "latency_ms": 100,
                    "download_kbps": 2000,
                    "upload_kbps": 500,
                },
                {
                    "id": "blocked-c",
                    "status": "reachable",
                    "successful_rounds": 3,
                    "total_rounds": 3,
                    "same_exit_ip": True,
                    "exit_ip": "198.51.100.12",
                    "latency_ms": 90,
                    "download_kbps": 2000,
                    "upload_kbps": 500,
                },
            ],
        }

    def test_local_three_round_pass_overrides_cloud_degraded_status(self):
        standard, fast = select_mainland_nodes(self.candidates, self.report, 512, 128)
        self.assertEqual([node["id"] for node in standard], ["unstable-b", "stable-a"])
        self.assertEqual([node["id"] for node in fast], ["blocked-c", "unstable-b", "stable-a"])
        self.assertEqual(standard[0]["mainland_status"], "reachable")

    def test_fast_pool_uses_local_speed_thresholds(self):
        standard, fast = select_mainland_nodes(self.candidates, self.report, 1000, 128)
        self.assertEqual([node["id"] for node in standard], ["unstable-b", "stable-a"])
        self.assertEqual([node["id"] for node in fast], ["blocked-c", "unstable-b"])

    def test_mainland_pool_uses_local_stability_not_cloud_stability(self):
        standard, fast = select_mainland_nodes(self.candidates, self.report, 512, 128)
        self.assertIn("unstable-b", [node["id"] for node in standard])
        self.assertEqual(self.candidates[1]["stable_status"], "degraded")

    def test_fast_pool_does_not_apply_reputation_filter(self):
        standard, fast = select_mainland_nodes(self.candidates, self.report, 512, 128)
        self.assertNotIn("blocked-c", [node["id"] for node in standard])
        self.assertIn("blocked-c", [node["id"] for node in fast])

    def test_rejects_report_with_fewer_than_three_rounds(self):
        report = dict(self.report)
        report["test_contract"] = {"vpn_disabled_attested": True, "rounds": 1}
        with self.assertRaises(ValueError):
            select_mainland_nodes(self.candidates, report, 512, 128)

    def test_rejects_result_without_all_rounds_and_consistent_exit(self):
        report = dict(self.report)
        report["results"] = [dict(item) for item in self.report["results"]]
        report["results"][0]["successful_rounds"] = 2
        report["results"][0]["same_exit_ip"] = False
        standard, fast = select_mainland_nodes(self.candidates, report, 512, 128)
        self.assertNotIn("stable-a", [node["id"] for node in standard])
        self.assertNotIn("stable-a", [node["id"] for node in fast])

    def test_rejects_report_without_mainland_attestation(self):
        report = dict(self.report)
        report["test_contract"] = {"vpn_disabled_attested": False}
        with self.assertRaises(ValueError):
            select_mainland_nodes(self.candidates, report, 512, 128)


if __name__ == "__main__":
    unittest.main()
