from __future__ import annotations
import ipaddress,json,time
from pathlib import Path
from typing import Any
import requests
ROOT=Path(__file__).resolve().parents[1]; CANDIDATES=ROOT/"public"/"candidates.json"; OUTPUT=ROOT/"public"/"risk-results.json"
FEEDS={"ipsum":"https://raw.githubusercontent.com/stamparm/ipsum/master/ipsum.txt","tor_exit_list":"https://check.torproject.org/torbulkexitlist"}
def download_set(url):
    r=requests.get(url,timeout=20,headers={"User-Agent":"Direct-NodeHub/0.1"}); r.raise_for_status(); found=set()
    for line in r.text.splitlines():
        parts=line.strip().split()
        if not parts or parts[0].startswith("#"): continue
        try: found.add(str(ipaddress.ip_address(parts[0])))
        except ValueError: continue
    return found
def classify(ip,threat,tor):
    if not ip: return {"risk_status":"unknown","risk_score":None,"risk_reasons":["no_verified_exit_ip"]}
    try: addr=ipaddress.ip_address(ip)
    except ValueError: return {"risk_status":"unknown","risk_score":None,"risk_reasons":["invalid_exit_ip"]}
    if not addr.is_global: return {"risk_status":"blocked","risk_score":100,"risk_reasons":["non_public_exit_ip"]}
    reasons=[]
    if str(addr) in tor: reasons.append("tor_exit_node")
    if str(addr) in threat: reasons.append("ipsum_threat_intel_match")
    if reasons: return {"risk_status":"blocked","risk_score":100,"risk_reasons":reasons}
    return {"risk_status":"unconfirmed","risk_score":None,"risk_reasons":["not_listed_in_downloaded_threat_feeds"]}
def run():
    if not CANDIDATES.exists(): raise FileNotFoundError("run collector first")
    data=json.loads(CANDIDATES.read_text()); feeds={}; lists={}
    for name,url in FEEDS.items():
        try: lists[name]=download_set(url); feeds[name]={"status":"ok","entries":len(lists[name])}
        except Exception as e: lists[name]=set(); feeds[name]={"status":"error","error":str(e)[:180]}
    results=[]
    for node in data.get("candidates",[]):
        r=classify(node.get("exit_ip"),lists.get("ipsum",set()),lists.get("tor_exit_list",set())); node.update(r)
        decision="reject" if r["risk_status"]=="blocked" else "quarantine"
        if r["risk_status"]=="unconfirmed" and all(v["status"]=="ok" for v in feeds.values()): decision="eligible_for_unconfirmed_pool"
        node["risk_policy_decision"]=decision; results.append({"id":node["id"],**r,"decision":decision})
    summary={"total":len(results),"blocked":sum(r["risk_status"]=="blocked" for r in results),"unconfirmed":sum(r["risk_status"]=="unconfirmed" for r in results),"unknown":sum(r["risk_status"]=="unknown" for r in results),"feeds":feeds,"warning":"Not listed in threat feeds does not prove an IP is clean; this is not a reputation guarantee."}
    stamp=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()); data["risk_checked_at"]=stamp; data["risk_summary"]=summary; CANDIDATES.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n")
    OUTPUT.parent.mkdir(parents=True,exist_ok=True); OUTPUT.write_text(json.dumps({"schema_version":1,"generated_at":stamp,"summary":summary,"results":results},ensure_ascii=False,indent=2)+"\n"); print(json.dumps(summary,ensure_ascii=False,indent=2)); return summary
if __name__=="__main__": run()
