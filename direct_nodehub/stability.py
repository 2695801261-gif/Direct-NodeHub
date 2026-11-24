from __future__ import annotations
import concurrent.futures,json,os,shutil,statistics,time
from pathlib import Path
from direct_nodehub.protocol import verify_one
ROOT=Path(__file__).resolve().parents[1]
CANDIDATES=ROOT/"public"/"candidates.json"
PROTOCOL=ROOT/"public"/"protocol-results.json"
OUTPUT=ROOT/"public"/"stability-results.json"
POLICY=ROOT/"config"/"policy.json"
def download_metric(result):
    for check in result.get("http_checks",[]):
        if check.get("url")=="cloudflare-256KiB-download" and check.get("status")=="ok":
            return float(check.get("download_kbps",0))
    return 0.0
def upload_metric(result):
    for check in result.get("http_checks",[]):
        if check.get("url")=="cloudflare-64KiB-upload" and check.get("status")=="ok":
            return float(check.get("upload_kbps",0))
    return 0.0
def run():
    data=json.loads(CANDIDATES.read_text())
    protocol=json.loads(PROTOCOL.read_text())
    policy=json.loads(POLICY.read_text())
    settings=policy.get("stability",{})
    rounds=int(settings.get("rounds",3))
    minimum=float(settings.get("minimum_download_kbps",64))
    minimum_upload=float(settings.get("minimum_upload_kbps",16))
    required=int(settings.get("required_successful_rounds",3))
    binary=os.environ.get("MIHOMO_BIN") or shutil.which("mihomo")
    if not binary: raise RuntimeError("mihomo binary not found for stability test")
    byid={n["id"]:n for n in data.get("candidates",[])}
    selected=[byid[r["id"]] for r in protocol.get("results",[]) if r.get("protocol_status")=="verified" and r.get("id") in byid]
    def check(pair):
        index,node=pair
        attempts=[]
        for attempt in range(rounds):
            result=verify_one(node,binary,preferred_port=24000+index*rounds+attempt)
            speed=download_metric(result)
            upload=upload_metric(result)
            ok=result.get("protocol_status")=="verified" and speed>=minimum and upload>=minimum_upload
            attempts.append({"round":attempt+1,"ok":ok,"protocol_status":result.get("protocol_status"),"exit_ip":result.get("exit_ip"),"exit_ip_agreement":result.get("exit_ip_agreement"),"download_kbps":speed,"upload_kbps":upload,"error":result.get("error")})
        good=[a for a in attempts if a["ok"]]
        ips=[a["exit_ip"] for a in good]
        same_ip=bool(ips) and len(set(ips))==1
        stable=len(good)>=required and same_ip
        degraded=len(good)>=max(2,required-1) and same_ip
        return {"id":node["id"],"stable_status":"stable" if stable else ("degraded" if degraded else "unstable"),"successful_rounds":len(good),"total_rounds":rounds,"same_exit_ip":same_ip,"median_download_kbps":round(statistics.median([a["download_kbps"] for a in good]),1) if good else 0,"median_upload_kbps":round(statistics.median([a["upload_kbps"] for a in good]),1) if good else 0,"rounds":attempts}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(check,enumerate(selected)))
    rmap={x["id"]:x for x in results}
    for node in data.get("candidates",[]):
        result=rmap.get(node["id"])
        if result: node.update({k:v for k,v in result.items() if k!="rounds"})
        elif node.get("protocol_status")=="verified": node["stable_status"]="not_tested"
    summary={"candidates_tested":len(results),"stable":sum(r["stable_status"]=="stable" for r in results),"degraded":sum(r["stable_status"]=="degraded" for r in results),"unstable":sum(r["stable_status"]=="unstable" for r in results),"rounds":rounds,"required_successful_rounds":required,"minimum_download_kbps":minimum,"minimum_upload_kbps":minimum_upload,"test_region":"github-hosted-runner (region not guaranteed)","meaning":"Repeated tunnel establishment, consistent exit IP, 256 KiB HTTPS download and 64 KiB HTTPS upload; not a mainland measurement."}
    stamp=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())
    data["stability_tested_at"]=stamp
    data["stability_summary"]=summary
    CANDIDATES.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n")
    OUTPUT.write_text(json.dumps({"schema_version":1,"generated_at":stamp,"summary":summary,"results":results},ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return summary
if __name__=="__main__": run()
