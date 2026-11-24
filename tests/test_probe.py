import unittest
from unittest.mock import patch

from direct_nodehub.probe import tcp_probe


class ProbeTests(unittest.TestCase):
    def test_tcp_success_is_not_mainland_confirmation(self):
        node = {"id": "abc", "server": "127.0.0.1", "port": 80}
        with patch("direct_nodehub.probe.socket.create_connection"):
            result = tcp_probe(node, 1)
        self.assertEqual(result["cloud_tcp"], "reachable")
        self.assertNotIn("mainland_status", result)
        self.assertEqual(result["cloud_probe_region"], "github-hosted-runner (region not guaranteed)")

    def test_tcp_failure(self):
        node = {"id": "abc", "server": "127.0.0.1", "port": 65000}
        with patch("direct_nodehub.probe.socket.create_connection", side_effect=OSError("refused")):
            result = tcp_probe(node, 1)
        self.assertEqual(result["cloud_tcp"], "failed")
        self.assertIn("refused", result["error"])


if __name__ == "__main__":
    unittest.main()
