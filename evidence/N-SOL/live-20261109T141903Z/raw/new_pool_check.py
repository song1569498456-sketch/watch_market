import json, time, datetime, base64, hashlib
import requests
BASE = r"D:\ds-arb-test\watch_market\evidence\N-SOL\live-20261109T141903Z\raw"
PROXY = "http://127.0.0.1:7897"
RPC = "https://api.mainnet-beta.solana.com"
s = requests.Session(); s.trust_env = False
s.proxies = {"http": PROXY, "https": PROXY}
s.headers.update({"User-Agent": "watch_market-readonly-research/1.0"})
now = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()

summ = json.load(open(BASE + r"\summary.json", encoding="utf-8"))
out = {"prior_raydium_pool_checks": summ.get("raydium_pool_checks"),
       "prior_raydium_pool_rpc_slot": summ.get("raydium_pool_rpc_slot"),
       "prior_raydium_owner_match": summ.get("raydium_pool_owner_matches_program")}

# new pool discovered from Raydium official API list: createdAt epoch 1794169583 (2026-11-08)
new_pool = summ["raydium_pools"][2]  # 4HHcEX... CPMM Standard, createdAt 1794169583
out["target_new_pool"] = new_pool
addrs = [new_pool["id"], new_pool["mintA"], new_pool["mintB"]]
time.sleep(0.7)
r = s.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": "getMultipleAccounts",
                      "params": [addrs, {"encoding": "base64", "commitment": "finalized"}]}, timeout=30)
j = r.json()
out["rpc"] = {"http_status": r.status_code, "at": now(), "bytes": len(r.content),
              "sha256": hashlib.sha256(r.content).hexdigest()}
if "result" in j:
    out["slot"] = j["result"]["context"]["slot"]
    checks = []
    for a, v in zip(addrs, j["result"]["value"]):
        checks.append({"address": a, "owner": v.get("owner") if v else None,
                       "executable": v.get("executable") if v else None,
                       "space": v.get("space") if v else None,
                       "data_bytes": len(base64.b64decode(v["data"][0])) if v and v.get("data") else None})
    out["checks"] = checks
    out["pool_owner_matches_program"] = checks[0]["owner"] == new_pool["programId"]
else:
    out["rpc_error"] = j
time.sleep(0.7)

# account creation signature? try getSignaturesForAddress on new pool -> activity evidence
r2 = s.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": "getSignaturesForAddress",
                       "params": [new_pool["id"], {"limit": 3, "commitment": "finalized"}]}, timeout=30)
j2 = r2.json()
out["sig"] = {"http_status": r2.status_code, "at": now()}
if "result" in j2:
    out["sig"]["count"] = len(j2["result"])
    out["sig"]["items"] = [{"signature": x.get("signature"), "slot": x.get("slot"),
                            "blockTime_utc": (datetime.datetime.fromtimestamp(x["blockTime"], datetime.timezone.utc).isoformat()
                                              if x.get("blockTime") else None)} for x in j2["result"]]
out["finished_at_utc"] = now()
json.dump(out, open(BASE + r"\new_pool_check.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1)[:5000])
