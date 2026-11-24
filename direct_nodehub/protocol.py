from __future__ import annotations
import base64, concurrent.futures, ipaddress, json, os, shutil, socket, subprocess, tempfile, time, urllib.parse
from pathlib import Path
from typing import Any
import requests, yaml
ROOT=Path(__file__).resolve().parents[1]; CANDIDATES=ROOT/"public"/"candidates.json"; OUTPUT=ROOT/"public"/"protocol-results.json"; POLICY=ROOT/"config"/"policy.json"
ECHO_URLS=["https://api.ipify.org","https://ifconfig.me/ip","https://icanhazip.com"]
DOWNLOAD_URL="https://speed.cloudflare.com/__down?bytes=262144"
UPLOAD_URL="https://speed.cloudflare.com/__up"
def _b64(v):
    v += "="*((4-len(v)%4)%4); return base64.urlsafe_b64decode(v.encode())
def _params(p): return {k:v[-1] for k,v in urllib.parse.parse_qs(p.query,keep_blank_values=True).items()}
def _from_uri(uri,name):
    p=urllib.parse.urlsplit(uri); scheme=p.scheme.lower(); q=_params(p)
    if scheme=="vmess":
        d=json.loads(_b64(uri[8:]).decode()); n={"name":name,"type":"vmess","server":d["add"],"port":int(d["port"]),"uuid":d["id"],"alterId":int(d.get("aid",0)),"cipher":d.get("scy") or "auto"}
        net=(d.get("net") or "tcp").lower()
        if net not in {"tcp","ws","grpc","http","h2"}: raise ValueError("unsupported VMess transport")
        if net!="tcp": n["network"]=net
        if net=="ws":
            n["ws-opts"]={"path":d.get("path") or "/"}
            if d.get("host"): n["ws-opts"]["headers"]={"Host":d["host"]}
        if d.get("tls") in ("tls","true",True): n["tls"]=True; n["servername"]=d.get("sni") or d.get("host") or d["add"]
        return n
    host=p.hostname; port=p.port
    if not host or not port: raise ValueError("missing server or port")
    if scheme=="ss":
        user=urllib.parse.unquote(p.username or ""); password=urllib.parse.unquote(p.password or "")
        if not password and user:
            decoded=_b64(user).decode()
            if ":" not in decoded: raise ValueError("invalid Shadowsocks credentials")
            user,password=decoded.split(":",1)
        if ":" in user: method,password=user.split(":",1)
        elif user and password: method=user
        else: raise ValueError("unsupported Shadowsocks URI form")
        return {"name":name,"type":"ss","server":host,"port":port,"cipher":method,"password":password,"udp":True}
    if scheme in {"hysteria2","hy2"}:
        n={"name":name,"type":"hysteria2","server":host,"port":port,"password":urllib.parse.unquote(p.username or "")}
        if q.get("sni"): n["sni"]=q["sni"]
        if q.get("obfs"): n["obfs"]=q["obfs"]
        if q.get("obfs-password"): n["obfs-password"]=q["obfs-password"]
        if q.get("insecure")=="1": n["skip-cert-verify"]=True
        return n
    if scheme=="tuic":
        n={"name":name,"type":"tuic","server":host,"port":port,"uuid":urllib.parse.unquote(p.username or ""),"password":urllib.parse.unquote(p.password or "")}
        if q.get("congestion_control"): n["congestion-controller"]=q["congestion_control"]
        if q.get("udp_relay_mode"): n["udp-relay-mode"]=q["udp_relay_mode"]
        if q.get("alpn"): n["alpn"]=q["alpn"].split(",")
        if q.get("sni"): n["sni"]=q["sni"]
        if q.get("allow_insecure")=="1": n["skip-cert-verify"]=True
        return n
    if scheme in {"socks","socks5","http","https"}:
        n={"name":name,"type":"socks5" if scheme in {"socks","socks5"} else "http","server":host,"port":port}
        if p.username is not None: n["username"]=urllib.parse.unquote(p.username); n["password"]=urllib.parse.unquote(p.password or "")
        if scheme=="https": n["tls"]=True
        return n
    if scheme not in {"vless","trojan"}: raise ValueError("unsupported scheme")
    user=urllib.parse.unquote(p.username or ""); n={"name":name,"type":scheme,"server":host,"port":port}
    if scheme=="vless":
        n["uuid"]=user
        if q.get("encryption") not in (None,"","none"): raise ValueError("unsupported VLESS encryption")
        if q.get("flow"): n["flow"]=q["flow"]
    else: n["password"]=user
    net=q.get("type",q.get("network","tcp")).lower()
    if net not in {"tcp","ws","grpc","http","h2"}: raise ValueError("unsupported transport")
    if net!="tcp": n["network"]=net
    if net=="ws":
        n["ws-opts"]={"path":urllib.parse.unquote(q.get("path","/"))}
        if q.get("host"): n["ws-opts"]["headers"]={"Host":q["host"]}
    if net=="grpc": n["grpc-opts"]={"grpc-service-name":q.get("serviceName",q.get("service_name",""))}
    security=q.get("security","")
    if security in {"tls","reality"} or q.get("sni"):
        n["tls"]=True; n["servername"]=q.get("sni") or q.get("host") or host
        if q.get("alpn"): n["alpn"]=q["alpn"].split(",")
        if q.get("fp"): n["client-fingerprint"]=q["fp"]
    if security=="reality":
        key=q.get("pbk") or q.get("publicKey")
        if not key: raise ValueError("Reality URI missing public key")
        n["reality-opts"]={"public-key":key,"short-id":q.get("sid","")}; n["client-fingerprint"]=q.get("fp","chrome")
    if q.get("allowInsecure","").lower()=="true": n["skip-cert-verify"]=True
    return n
def to_mihomo_proxy(c):
    if isinstance(c.get("config"),dict):
        n=dict(c["config"]); n["name"]=c.get("name") or c["id"]; return n
    if not c.get("uri"): raise ValueError("candidate has no complete URI or proxy config")
    return _from_uri(c["uri"],c.get("name") or c["id"])
def _egress(port):
    px={"http":f"http://127.0.0.1:{port}","https":f"http://127.0.0.1:{port}"}; s=requests.Session(); s.trust_env=False; ips=[]; checks=[]
    for url in ECHO_URLS:
        started=time.perf_counter()
        try:
            r=s.get(url,proxies=px,timeout=(3,6)); r.raise_for_status(); ip=r.text.strip().splitlines()[0]
            import ipaddress; ipaddress.ip_address(ip); ips.append(ip); checks.append({"url":url,"status":"ok","ip":ip,"latency_ms":round((time.perf_counter()-started)*1000,1)})
        except Exception as e: checks.append({"url":url,"status":"failed","latency_ms":round((time.perf_counter()-started)*1000,1),"error":str(e)[:160]})
    started=time.perf_counter()
    try:
        with s.get(DOWNLOAD_URL,proxies=px,timeout=(3,8),stream=True) as response:
            response.raise_for_status(); total=0
            for chunk in response.iter_content(65536):
                total+=len(chunk)
                if total>=262144: break
        elapsed=max(time.perf_counter()-started,0.001)
        checks.append({"url":"cloudflare-256KiB-download","status":"ok" if total>=262144 else "partial","bytes":total,"duration_ms":round(elapsed*1000,1),"download_kbps":round(total/1024/elapsed,1)})
    except Exception as e: checks.append({"url":"cloudflare-256KiB-download","status":"failed","error":str(e)[:160]})
    started=time.perf_counter()
    try:
        payload=bytes(65536)
        response=s.post(UPLOAD_URL,data=payload,headers={"Content-Type":"application/octet-stream"},timeout=(3,8))
        response.raise_for_status()
        elapsed=max(time.perf_counter()-started,0.001)
        checks.append({"url":"cloudflare-64KiB-upload","status":"ok","bytes":len(payload),"duration_ms":round(elapsed*1000,1),"upload_kbps":round(len(payload)/1024/elapsed,1)})
    except Exception as e:
        checks.append({"url":"cloudflare-64KiB-upload","status":"failed","error":str(e)[:160]})
    return ips,checks
def verify_one(c,binary,preferred_port=19000):
    out={"id":c["id"],"protocol_status":"failed","exit_ip":None,"exit_ip_agreement":0,"http_checks":[],"error":None}
    try:
        proxy=to_mihomo_proxy(c)
        with tempfile.TemporaryDirectory(prefix="dnh-") as td:
            cfgpath=Path(td)/"config.yaml"; port=preferred_port
            while True:
                with socket.socket() as sock:
                    try: sock.bind(("127.0.0.1",port)); break
                    except OSError:
                        port+=1
                        if port>25000: raise RuntimeError("no local port available")
            cfg={"mixed-port":port,"allow-lan":False,"mode":"global","log-level":"error","ipv6":False,"proxies":[proxy],"proxy-groups":[{"name":"GLOBAL","type":"select","proxies":[proxy["name"]]}],"rules":["MATCH,GLOBAL"]}
            cfgpath.write_text(yaml.safe_dump(cfg,allow_unicode=True,sort_keys=False),encoding="utf-8")
            check=subprocess.run([binary,"-t","-f",str(cfgpath),"-d",td],capture_output=True,text=True,timeout=8)
            if check.returncode: raise RuntimeError(("mihomo config rejected: "+(check.stderr or check.stdout))[:300])
            proc=subprocess.Popen([binary,"-f",str(cfgpath),"-d",td],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                deadline=time.time()+10
                while time.time()<deadline:
                    if proc.poll() is not None: raise RuntimeError("mihomo exited during startup")
                    try:
                        with socket.create_connection(("127.0.0.1",port),timeout=.3): break
                    except OSError: time.sleep(.25)
                ips,checks=_egress(port); out["http_checks"]=checks
                if not ips: raise RuntimeError("no valid public IP returned through proxy")
                counts={ip:ips.count(ip) for ip in set(ips)}; best,agreement=max(counts.items(),key=lambda x:x[1]); out["exit_ip"]=best; out["exit_ip_agreement"]=agreement
                out["protocol_status"]="verified" if agreement>=2 else "partial"
                if agreement<2: out["error"]="fewer than two echo services agreed on exit IP"
            finally:
                proc.terminate()
                try: proc.wait(timeout=3)
                except subprocess.TimeoutExpired: proc.kill()
    except Exception as e: out["error"]=str(e)[:300]
    return out
def network_of(candidate):
    config = candidate.get("config")
    if isinstance(config, dict):
        return str(config.get("network") or "tcp").lower()
    try:
        return str(to_mihomo_proxy(candidate).get("network") or "tcp").lower()
    except Exception:
        return "unknown"


def worker_compatible_ws(candidate):
    """Return true only when a fixed-origin HTTPS Worker relay can preserve WS host/SNI."""
    try:
        proxy = to_mihomo_proxy(candidate)
    except Exception:
        return False
    if str(proxy.get("network") or "tcp").lower() != "ws" or not proxy.get("tls"):
        return False
    # The Worker fetch API controls its own TLS fingerprint and ALPN.
    if proxy.get("client-fingerprint") or proxy.get("alpn"):
        return False
    server = str(proxy.get("server") or "").strip().lower()
    sni = str(proxy.get("servername") or proxy.get("sni") or server).strip().lower()
    ws_opts = proxy.get("ws-opts") if isinstance(proxy.get("ws-opts"), dict) else {}
    headers = ws_opts.get("headers") if isinstance(ws_opts.get("headers"), dict) else {}
    # This relay can reproduce the URL-derived Host/SNI only. It deliberately
    # rejects custom headers and early-data settings it does not forward.
    extra_headers = {str(key).lower() for key in headers if str(key).lower() != "host"}
    host = str(headers.get("Host") or headers.get("host") or server).strip().lower()
    early_data = ws_opts.get("max-early-data") or ws_opts.get("early-data-header-name")
    return bool(
        server and server == sni == host
        and not proxy.get("skip-cert-verify")
        and not extra_headers
        and not early_data
    )


def worker_compatible_tcp_bridge(candidate):
    """TLS TCP candidates that can be safely wrapped in a Worker WebSocket tunnel."""
    try:
        proxy = to_mihomo_proxy(candidate)
    except Exception:
        return False
    kind = str(proxy.get("type") or "").lower()
    network = str(proxy.get("network") or "tcp").lower()
    if kind not in {"vless", "vmess", "trojan"} or network != "tcp":
        return False
    if (
        proxy.get("flow")
        or proxy.get("reality-opts")
        or proxy.get("skip-cert-verify")
        or proxy.get("client-fingerprint")
        or proxy.get("alpn")
    ):
        # cloudflare:sockets does not expose controls for reproducing a
        # candidate-specific TLS fingerprint or ALPN list.
        return False
    server = str(proxy.get("server") or "").strip().lower()
    try:
        port = int(proxy.get("port") or 0)
    except (TypeError, ValueError):
        return False
    if not server or port < 1 or port > 65535 or port == 25:
        return False
    try:
        ipaddress.ip_address(server)
        return False
    except ValueError:
        pass
    sni = str(proxy.get("servername") or proxy.get("sni") or server).strip().lower()
    tls_enabled = bool(proxy.get("tls")) or kind == "trojan"
    return tls_enabled and sni == server


def select_protocol_candidates(nodes, max_candidates=80, websocket_quota=20):
    ranked = sorted(nodes, key=lambda n: n.get("cloud_tcp_latency_ms") or 999999)
    websocket = [node for node in ranked if network_of(node) == "ws"]
    other = [node for node in ranked if network_of(node) != "ws"]
    # Prioritize candidates compatible with either fixed-origin Worker bridge.
    websocket.sort(key=lambda node: (
        not worker_compatible_ws(node),
        float(node.get("cloud_tcp_latency_ms") or 999999),
    ))
    other.sort(key=lambda node: (
        not worker_compatible_tcp_bridge(node),
        float(node.get("cloud_tcp_latency_ms") or 999999),
    ))
    ws_limit = min(max(0, int(websocket_quota)), max(0, int(max_candidates)))
    selected_ws = websocket[:ws_limit]
    selected_other = other[:max(0, int(max_candidates) - len(selected_ws))]
    return selected_ws + selected_other


def run():
    if not CANDIDATES.exists(): raise FileNotFoundError("run collector first")
    binary=os.environ.get("MIHOMO_BIN") or shutil.which("mihomo")
    if not binary: raise RuntimeError("mihomo binary not found")
    policy=json.loads(POLICY.read_text()); data=json.loads(CANDIDATES.read_text()); tcp=[n for n in data.get("candidates",[]) if n.get("cloud_tcp")=="reachable"]
    probe_policy=policy.get("protocol_probe",{}); selected=select_protocol_candidates(tcp, int(probe_policy.get("max_candidates",80)), int(probe_policy.get("websocket_probe_quota",20)))
    def task(pair):
        index,node=pair
        return verify_one(node,binary,preferred_port=20000+index)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        tested=list(pool.map(task,enumerate(selected)))
    byid={r["id"]:r for r in tested}
    for n in data.get("candidates",[]):
        r=byid.get(n["id"])
        if r: n.update({"protocol_status":r["protocol_status"],"exit_ip":r["exit_ip"],"exit_ip_agreement":r["exit_ip_agreement"],"protocol_error":r["error"]})
        else: n.setdefault("protocol_status","not_tested")
        n["mainland_status"]="not_tested"
    selected_transports={}
    for node in selected:
        transport=network_of(node)
        selected_transports[transport]=selected_transports.get(transport,0)+1
    selected_websocket_ids=[node["id"] for node in selected if network_of(node)=="ws"]
    summary={"total_tcp_reachable":len(tcp),"tested":len(tested),"verified":sum(r["protocol_status"]=="verified" for r in tested),"partial":sum(r["protocol_status"]=="partial" for r in tested),"failed":sum(r["protocol_status"]=="failed" for r in tested),"selected_transports":selected_transports,"selected_websocket_count":len(selected_websocket_ids),"selected_websocket_ids":selected_websocket_ids,"region":"github-hosted-runner (region not guaranteed)","meaning":"Mihomo tunnel and HTTP egress from cloud; not a mainland China test."}
    stamp=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()); data["protocol_tested_at"]=stamp; data["protocol_summary"]=summary; CANDIDATES.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n")
    OUTPUT.parent.mkdir(parents=True,exist_ok=True); OUTPUT.write_text(json.dumps({"schema_version":1,"generated_at":stamp,"summary":summary,"results":tested},ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(summary,ensure_ascii=False,indent=2)); return summary
if __name__=="__main__": run()
