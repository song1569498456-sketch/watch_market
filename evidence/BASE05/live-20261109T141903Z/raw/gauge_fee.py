import json, time, hashlib, datetime
import requests
from Crypto.Hash import keccak
BASE = r"D:\ds-arb-test\watch_market\evidence\BASE05\live-20260909T141903Z\raw"
BASE = r"D:\ds-arb-test\watch_market\evidence\BASE05\live-20261109T141903Z\raw"
PROXY = "http://127.0.0.1:7897"
RPC = "https://mainnet.base.org"
s = requests.Session(); s.trust_env = False
s.proxies = {"http": PROXY, "https": PROXY}
s.headers.update({"User-Agent": "watch_market-readonly-research/1.0", "Content-Type": "application/json"})
now = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
def sel(sig):
    h = keccak.new(digest_bits=256); h.update(sig.encode()); return "0x" + h.hexdigest()[:8]
def enc_addr(a): return a[2:].rjust(64, "0")
prev = json.load(open(BASE + r"\base05_summary.json", encoding="utf-8"))
pinned = hex(prev["pinned_block"])
POOL = prev["pool"]
FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"
VOTER = "0x16613524e02ad97edfef371bc883f2f5d6c480a5"
calls = [("eth_getCode", [VOTER, pinned]),
         ("eth_call", [{"to": FACTORY, "data": sel("getFee(address)") + enc_addr(POOL)}, pinned]),
         ("eth_call", [{"to": FACTORY, "data": sel("isPool(address)") + enc_addr(POOL)}, pinned]),
         ("eth_call", [{"to": FACTORY, "data": sel("isPaused()")}, pinned]),
         ("eth_call", [{"to": VOTER, "data": sel("gauges(address)") + enc_addr(POOL)}, pinned]),
         ("eth_call", [{"to": POOL, "data": sel("poolFees()")}, pinned]),
         ("eth_call", [{"to": POOL, "data": sel("observationLength()")}, pinned])]
t0 = time.time()
r = s.post(RPC, json=[{"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls)], timeout=60)
res = r.json()
out = {"at_utc": now(), "pinned_block": prev["pinned_block"], "pool": POOL,
       "req": {"http_status": r.status_code, "n_calls": len(calls), "sha256": hashlib.sha256(r.content).hexdigest(),
               "elapsed_s": round(time.time()-t0, 3)}}
out["voter_code_bytes"] = (len(res[0].get("result") or "0x")-2)//2
out["factory_getFee_pool"] = res[1].get("result")
out["factory_isPool_pool"] = res[2].get("result")
out["factory_isPaused"] = res[3].get("result") if res[3].get("result") else res[3].get("error")
g = res[4].get("result")
out["voter_gauges"] = ("0x" + g[-40:]) if g and len(g) >= 66 else None
out["pool_poolFees_result"] = res[5].get("result") if res[5].get("result") else res[5].get("error")
out["observationLength"] = int(res[6]["result"], 16) if res[6].get("result") and res[6]["result"] != "0x" else None
gauge = out["voter_gauges"] if out["voter_gauges"] and int(out["voter_gauges"], 16) != 0 else None
out["gauge"] = gauge
if gauge:
    calls = [("eth_getCode", [gauge, pinned])]
    for f in ["isAlive()", "rewardRate()", "totalSupply()", "rewardToken()", "periodFinish()", "feesVotingReward()"]:
        calls.append(("eth_call", [{"to": gauge, "data": sel(f)}, pinned]))
    t0 = time.time()
    r2 = s.post(RPC, json=[{"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls)], timeout=60)
    res2 = r2.json()
    out["gauge_req"] = {"http_status": r2.status_code, "n_calls": len(calls), "sha256": hashlib.sha256(r2.content).hexdigest(),
                        "elapsed_s": round(time.time()-t0, 3)}
    gs = {}
    gs["code_bytes"] = (len(res2[0].get("result") or "0x")-2)//2
    for i, f in enumerate(["isAlive()", "rewardRate()", "totalSupply()", "rewardToken()", "periodFinish()", "feesVotingReward()"]):
        v = res2[1+i].get("result")
        if f in ("isAlive()",): gs[f] = bool(int(v, 16)) if v and v != "0x" else None
        elif f in ("rewardToken()", "feesVotingReward()"): gs[f] = ("0x" + v[-40:]) if v and len(v) >= 66 else None
        else: gs[f] = int(v, 16) if v and v != "0x" else None
    out["gauge_state"] = gs
out["finished_at_utc"] = now()
json.dump(out, open(BASE + r"\gauge_fee.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1)[:4000])
