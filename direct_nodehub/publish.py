from __future__ import annotations
import json,re,time
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1]
CANDIDATES=ROOT/"public"/"candidates.json"
OUTPUT=ROOT/"public"
POLICY=ROOT/"config"/"policy.json"
def clean_name(value):
    value=re.sub(r"[\x00-\x1f,]", " ", str(value or "node")).strip()
    return value[:80] or "node"
def build_config(node):
    if node.get("config"):
        cfg=dict(node["config"])
    else:
        from direct_nodehub.protocol import to_mihomo_proxy
        cfg=to_mihomo_proxy(node)
    cfg["name"]=clean_name(node.get("name") or node.get("id"))
    return cfg
def unique_configs(nodes):
    result=[]; used=set()
    for node in nodes:
        cfg=build_config(node); base=cfg["name"]; name=base; index=2
        while name in used:
            name=f"{base}-{index}"; index+=1
        cfg["name"]=name; used.add(name); result.append(cfg)
    return result
def run():
    data=json.loads(CANDIDATES.read_text())
    policy=json.loads(POLICY.read_text())
    nodes=data.get("candidates",[])
    limit=int(policy.get("publication",{}).get("max_nodes",100))
    stable=[n for n in nodes if n.get("protocol_status")=="verified" and n.get("stable_status")=="stable" and n.get("risk_status")!="blocked"]
    # Reputation-screened list: only IPs checked against all configured feeds and not found in known-bad lists.
    screened=[n for n in stable if n.get("risk_status")=="unconfirmed" and n.get("risk_policy_decision")=="eligible_for_unconfirmed_pool"]
    # Fast list intentionally does not require a positive reputation result, but known-bad exits remain excluded.
    fast=[n for n in stable if float(n.get("median_download_kbps") or 0)>=256]
    screened=screened[:limit]; fast=fast[:limit]
    configs=unique_configs(screened); names=[n["name"] for n in configs]
    standard={"mixed-port":7890,"allow-lan":False,"mode":"rule","log-level":"warning","ipv6":False,"proxies":configs,
      "proxy-groups":[
       {"name":"节点手动选择","type":"select","proxies":names+["DIRECT"]},
       {"name":"节点自动优选","type":"url-test","url":"https://www.gstatic.com/generate_204","interval":300,"tolerance":80,"lazy":True,"proxies":names or ["DIRECT"]},
       {"name":"节点故障切换","type":"fallback","url":"https://www.gstatic.com/generate_204","interval":180,"lazy":True,"proxies":names},
       {"name":"PROXY","type":"select","proxies":["节点自动优选","节点故障切换","节点手动选择","DIRECT"]}],
      "rules":["MATCH,PROXY"]}
    (OUTPUT/"clash.yaml").write_text(yaml.safe_dump(standard,allow_unicode=True,sort_keys=False),encoding="utf-8")
    fastconfigs=unique_configs(fast); fastnames=[n["name"] for n in fastconfigs]
    fast_yaml={"mixed-port":7891,"allow-lan":False,"mode":"rule","log-level":"warning","ipv6":False,"proxies":fastconfigs,
      "proxy-groups":[
       {"name":"高速手动选择","type":"select","proxies":fastnames+["DIRECT"]},
       {"name":"高速自动优选","type":"url-test","url":"https://www.gstatic.com/generate_204","interval":300,"tolerance":80,"lazy":True,"proxies":fastnames or ["DIRECT"]},
       {"name":"PROXY","type":"select","proxies":["高速自动优选","高速手动选择","DIRECT"]}],
      "rules":["MATCH,PROXY"]}
    (OUTPUT/"fast.yaml").write_text(yaml.safe_dump(fast_yaml,allow_unicode=True,sort_keys=False),encoding="utf-8")
    # Chain direction: public node is the first hop; the user's own home endpoint is the final hop.
    chainconfigs=unique_configs(stable[:limit]); chainnames=[n["name"] for n in chainconfigs]
    home={"name":"HOME-RESIDENTIAL-REPLACE-ME","type":"socks5","server":"YOUR_HOME_HOST","port":1080,"username":"YOUR_USERNAME","password":"YOUR_PASSWORD","dialer-proxy":"ENTRY-AUTO"}
    chain={"mixed-port":7892,"allow-lan":False,"mode":"rule","log-level":"warning","ipv6":False,"proxies":chainconfigs+[home],
      "proxy-groups":[
       {"name":"ENTRY-AUTO","type":"url-test","url":"https://www.gstatic.com/generate_204","interval":180,"tolerance":100,"lazy":True,"proxies":chainnames or ["DIRECT"]},
       {"name":"HOME-CHAIN","type":"select","proxies":["HOME-RESIDENTIAL-REPLACE-ME"]}],
      "rules":["MATCH,HOME-CHAIN"]}
    (OUTPUT/"chain-template.yaml").write_text(yaml.safe_dump(chain,allow_unicode=True,sort_keys=False),encoding="utf-8")
    summary={"reputation_screened_stable_nodes":len(configs),"fast_stable_nodes":len(fastconfigs),"chain_entry_nodes":len(chainconfigs),"chain_template":"public/chain-template.yaml","standard_gate":"3/3 stable rounds, exit IP agreement, download >=64 KiB/s, risk feeds available and no known-bad match","fast_gate":"3/3 stable rounds, exit IP agreement, download >=256 KiB/s; positive reputation confirmation not required, known-bad IPs still excluded","chain_direction":"public node as entry hop; user-owned home endpoint as final hop via dialer-proxy","mainland_status":"not_tested","warning":"Cloud runner results do not guarantee mainland reachability. Chain template placeholders must be replaced locally; never commit home credentials."}
    stamp=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())
    status={"generated_at":stamp,"summary":summary,"cloud_tcp":data.get("cloud_tcp_summary"),"protocol":data.get("protocol_summary"),"risk":data.get("risk_summary"),"stability":data.get("stability_summary"),"sources":data.get("sources",[])}
    (OUTPUT/"status.json").write_text(json.dumps(status,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    html="""<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Direct-NodeHub 状态</title><style>body{font:16px system-ui;background:#101722;color:#e7edf5;max-width:760px;margin:36px auto;padding:0 18px}a{color:#8cc8ff}section{background:#1b2735;padding:16px;border-radius:12px;margin:14px 0}small{color:#aab7c7}</style><h1>Direct-NodeHub</h1><p>公开节点云端筛选状态</p><section><h2>订阅文件</h2><p><a href="clash.yaml">信誉情报筛选稳定池</a></p><p><a href="fast.yaml">高速稳定池</a></p><p><a href="chain-template.yaml">家宽链式代理模板</a></p><p><a href="status.json">JSON 状态</a></p></section><section><h2>测试边界</h2><p>云端协议与下载测试不代表中国大陆连通性。大陆状态尚未测试。</p><small>免费公开节点可能随时失效；不要用于敏感账号或支付。</small></section></html>"""
    (OUTPUT/"index.html").write_text(html,encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return summary
if __name__=="__main__": run()
