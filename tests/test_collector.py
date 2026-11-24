import base64
import json
import unittest

from direct_nodehub.collector import extract_candidates, parse_uri


class CollectorTests(unittest.TestCase):
    def test_vless_uri(self):
        node = parse_uri("vless://uuid@example.com:443?encryption=none#sample")
        self.assertEqual(node["type"], "vless")
        self.assertEqual(node["server"], "example.com")
        self.assertEqual(node["port"], 443)

    def test_trojan_uri(self):
        node = parse_uri("trojan://secret@example.net:8443#edge")
        self.assertEqual(node["type"], "trojan")
        self.assertEqual(node["port"], 8443)

    def test_vmess_uri(self):
        payload = {"v": "2", "ps": "vmess-test", "add": "node.example.org", "port": "2053"}
        encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        node = parse_uri("vmess://" + encoded)
        self.assertEqual(node["type"], "vmess")
        self.assertEqual(node["server"], "node.example.org")
        self.assertEqual(node["port"], 2053)

    def test_base64_subscription(self):
        source = "trojan://pw@edge.example.com:443#one\nvless://id@edge2.example.com:443#two"
        encoded = base64.b64encode(source.encode()).decode()
        nodes = extract_candidates(encoded)
        self.assertEqual(len(nodes), 2)

    def test_clash_yaml(self):
        source = """proxies:
  - name: test
    type: socks5
    server: 127.0.0.1
    port: 1080
"""
        nodes = extract_candidates(source)
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["type"], "socks5")

    def test_reject_bad_port(self):
        self.assertIsNone(parse_uri("vless://id@example.com:99999#bad"))


if __name__ == "__main__":
    unittest.main()
