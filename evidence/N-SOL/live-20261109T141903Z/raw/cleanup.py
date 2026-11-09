import json, hashlib, os, datetime, glob
BASE = r"D:\ds-arb-test\watch_market\evidence\N-SOL\live-20261109T141903Z\raw"
def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
big = os.path.join(BASE, "rpc_programdata_multi.json")
big_meta = {"file": "rpc_programdata_multi.json", "bytes": os.path.getsize(big), "sha256": sha(big)}
summ = json.load(open(os.path.join(BASE, "summary.json"), encoding="utf-8"))
cur_bt = datetime.datetime.fromisoformat(summ["current_blocktime_utc"].replace("+00:00", "+00:00"))
ref = cur_bt
for u in summ["program_upgrades"]:
    bt = u.get("last_deploy_time_utc")
    if bt:
        t = datetime.datetime.fromisoformat(bt)
        age_days = (ref - t).total_seconds() / 86400
        u["age_days_from_blocktime"] = round(age_days, 2)
        u["within_7d_by_blocktime"] = age_days <= 7
        u["within_30d_by_blocktime"] = age_days <= 30
trim = {"note": "原 getMultipleAccounts(base64) 响应含完整程序字节码（约21MB），仅保留解码字段；整包响应仅记字节数与sha256。",
        "source_response": big_meta,
        "context_slot": summ.get("programdata_rpc_slot"),
        "upgrade_evidence": summ["program_upgrades"]}
json.dump(trim, open(os.path.join(BASE, "rpc_programdata_extract.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
os.remove(big)

# correct slot-threshold flags in summary and note
for u in summ["program_upgrades"]:
    bt = u.get("last_deploy_time_utc")
    if bt:
        t = datetime.datetime.fromisoformat(bt)
        ad = (ref - t).total_seconds() / 86400
        u["age_days_from_blocktime"] = round(ad, 2)
        u["within_7d_by_blocktime"] = ad <= 7
        u["within_30d_by_blocktime"] = ad <= 30
summ["slot_threshold_note"] = "脚本内先按 400ms/槽 估算的 within_*_slots 阈值不适用于本轮实测槽速（实测约5槽/秒），已改用区块时间判断；以 *_by_blocktime 为准。"
json.dump(summ, open(os.path.join(BASE, "summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# cleanup obsolete/failed artifacts
for name in ["rpc_programs.json", "rpc_programdata.json", "rpc_pools_mints.json", "rpc_blocktimes.json",
             "rpc_diag.json", "raydium_programId.extract.json", "main.py", "probe.py", "diag.py"]:
    p = os.path.join(BASE, name)
    if os.path.exists(p):
        os.remove(p)

# timestamps for report
def iso(epoch):
    return datetime.datetime.fromtimestamp(int(epoch), datetime.timezone.utc).isoformat() if epoch else None
out = {
 "reference_blocktime_utc": summ["current_blocktime_utc"],
 "reference_slot": summ["current_slot"],
 "pool_created_at": {p["id"]: iso(p["createdAt"]) for p in summ["raydium_pools"] if p.get("createdAt") not in (None, "0")},
 "upgrades": [{"program_id": u["program_id"], "last_deploy_slot": u["last_deploy_slot"],
               "last_deploy_time_utc": u.get("last_deploy_time_utc"),
               "age_days": u.get("age_days_from_blocktime"),
               "within_30d": u.get("within_30d_by_blocktime"),
               "upgrade_authority": u.get("upgrade_authority")} for u in summ["program_upgrades"]],
 "files_after": sorted(os.path.basename(x) for x in glob.glob(BASE + r"\*")),
 "pool_checks_raydium": summ.get("raydium_pool_checks"),
}
json.dump(out, open(os.path.join(BASE, "derived_summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))
