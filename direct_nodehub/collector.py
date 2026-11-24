from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILE = ROOT / "config" / "sources.json"
OUTPUT_FILE = ROOT / "public" / "candidates.json"
POLICY_FILE = ROOT / "config" / "policy.json"
SUPPORTED = {"ss", "vmess", "vless", "trojan", "socks", "socks5", "http", "https"}
MAX_SOURCE_BYTES = 4 * 1024 * 1024
USER_AGENT = "Direct-NodeHub/0.1 (+https://github.com/2695801261-gif/Direct-NodeHub)"


def decode_base64_text(value: str) -> str | None:
    value = re.sub(r"\s+", "", value)
    if not value:
        return None
    value += "=" * ((4 - len(value) % 4) % 4)
    for decoder in (base64.urlsafe_b64decode, base64.b64decode):
        try:
            decoded = decoder(value.encode("ascii")).decode("utf-8-sig", errors="strict")
            if decoded and any(mark in decoded for mark in ("://", "proxies:", "{")):
                return decoded
        except Exception:
            pass
    return None


def _host_port(text: str) -> tuple[str, int] | None:
    try:
        parsed = urlsplit("//" + text)
        if parsed.hostname and parsed.port and 1 <= parsed.port <= 65535:
            return parsed.hostname, parsed.port
    except ValueError:
        return None
    return None


def parse_vmess(uri: str) -> dict[str, Any] | None:
    payload = uri[8:]
    decoded = decode_base64_text(payload)
    if not decoded:
        return None
    try:
        data = json.loads(decoded)
        host, port = str(data.get("add", "")), int(data.get("port", 0))
        if not host or not 1 <= port <= 65535:
            return None
        return {
            "name": str(data.get("ps") or f"vmess-{host}"),
            "type": "vmess",
            "server": host,
            "port": port,
            "uri": uri
        }
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def parse_uri(uri: str) -> dict[str, Any] | None:
    uri = uri.strip()
    if uri.lower().startswith("vmess://"):
        return parse_vmess(uri)
    try:
        parsed = urlsplit(uri)
        scheme = parsed.scheme.lower()
        if scheme not in SUPPORTED or not parsed.hostname or not parsed.port:
            return None
        port = parsed.port
        if not 1 <= port <= 65535:
            return None
        name = unquote(parsed.fragment) or f"{scheme}-{parsed.hostname}"
        return {
            "name": name[:100],
            "type": "socks5" if scheme == "socks" else scheme,
            "server": parsed.hostname,
            "port": port,
            "uri": uri
        }
    except ValueError:
        return None


def parse_clash_yaml(text: str) -> list[dict[str, Any]]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict) or not isinstance(data.get("proxies"), list):
        return []
    result = []
    for item in data["proxies"]:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type", "")).lower()
        host = item.get("server")
        try:
            port = int(item.get("port", 0))
        except (ValueError, TypeError):
            continue
        if kind not in SUPPORTED or not isinstance(host, str) or not host or not 1 <= port <= 65535:
            continue
        result.append({
            "name": str(item.get("name") or f"{kind}-{host}")[:100],
            "type": "socks5" if kind == "socks" else kind,
            "server": host,
            "port": port,
            "config": {k: v for k, v in item.items() if k != "name"}
        })
    return result


def extract_candidates(raw: str) -> list[dict[str, Any]]:
    raw = raw.lstrip("\ufeff").strip()
    if not raw:
        return []
    parsed_yaml = parse_clash_yaml(raw)
    if parsed_yaml:
        return parsed_yaml

    decoded = decode_base64_text(raw)
    if decoded:
        raw = decoded

    candidates: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip().strip("\x00")
        if not line:
            continue
        if line.startswith(("ss://", "vmess://", "vless://", "trojan://", "socks://", "socks5://", "http://", "https://")):
            node = parse_uri(line)
            if node:
                candidates.append(node)
    return candidates


def candidate_id(node: dict[str, Any]) -> str:
    if node.get("uri"):
        uri = node["uri"]
        if uri.startswith("vmess://"):
            decoded = decode_base64_text(uri[8:])
            try:
                payload = json.loads(decoded or "{}")
                payload.pop("ps", None)
                stable = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            except Exception:
                stable = uri.split("#", 1)[0]
        else:
            stable = uri.split("#", 1)[0]
    else:
        config = dict(node.get("config") or {})
        stable = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]


def collect() -> dict[str, Any]:
    config = json.loads(SOURCE_FILE.read_text(encoding="utf-8"))
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    source_results = []

    per_source_limit = int(json.loads(POLICY_FILE.read_text(encoding="utf-8")).get("max_candidates_per_source", 300))
    for source in config.get("sources", []):
        if not source.get("enabled", False):
            continue
        name = source["name"]
        try:
            response = session.get(
                source["url"],
                timeout=(8, 15),
                allow_redirects=True,
                stream=True
            )
            response.raise_for_status()
            chunks = []
            total = 0
            for chunk in response.iter_content(65536):
                total += len(chunk)
                if total > MAX_SOURCE_BYTES:
                    raise ValueError("source exceeds 4 MiB limit")
                chunks.append(chunk)
            body = b"".join(chunks).decode("utf-8-sig", errors="replace")
            parsed = extract_candidates(body)[:per_source_limit]
            added = 0
            for node in parsed:
                key = candidate_id(node)
                if key in seen:
                    existing = next((entry for entry in items if entry["id"] == key), None)
                    if existing is not None:
                        existing.setdefault("sources", [existing.get("source", name)])
                        if name not in existing["sources"]:
                            existing["sources"].append(name)
                    continue
                seen.add(key)
                items.append({
                    "id": key,
                    **node,
                    "source": name,
                    "sources": [name],
                    "status": "unverified",
                    "probe_region": None,
                    "risk_status": "not_checked"
                })
                added += 1
            source_results.append({"source": name, "status": "ok", "parsed": len(parsed), "unique_added": added})
        except Exception as exc:
            source_results.append({"source": name, "status": "error", "error": str(exc)[:240]})

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "schema_version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "notice": "Candidates are unverified. This file is not a safe-to-use subscription.",
        "total_candidates": len(items),
        "sources": source_results,
        "candidates": items
    }
    OUTPUT_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
