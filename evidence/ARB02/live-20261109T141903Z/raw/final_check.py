import json, time, hashlib, datetime
import requests
from Crypto.Hash import keccak
BASE = r"D:\ds-arb-test\watch_market\evidence\ARB02\live-20261109T141903Z\raw"
PROXY = "http://127.0.0.1:7897"
RPC = "https://arb1.arbitrum.io/rpc"
s = requests.Session(); s.trust_env = False
s.proxies = {"http": PROXY, "https": PROXY}
s.headers.update({"User-Agent": "watch_market-readonly-research/1.0", "Content-Type": "application/json"})
now = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
reqs = []
def sel(sig):
    h = keccak.new(digest_bits=256); h.update(sig.encode()); return "0x" + h.hexdigest()[:8]
prev = json.load(open(BASE + r"\arb02_summary.json", encoding="utf-8"))
pinned = hex(prev["pinned_block"])
QUOTER = "0x61fFE014bA17989E743c5F6cB21bF9697530B21e"
pools = prev["pools"]
pool_list = [pools[k]["pool"] for k in ["WETH/USDC", "USDC/USDT", "USDT/WETH"]]
calls = [("eth_call", [{"to": QUOTER, "data": sel("factory()")}, pinned]),
         ("eth_call", [{"to": QUOTER, "data": sel("WETH9()")}, pinned])]
for p in pool_list:
    calls.append(("eth_call", [{"to": p, "data": sel("liquidity()")}, pinned]))
    calls.append(("eth_call", [{"to": p, "data": sel("slot0()")}, pinned]))
t0 = time.time()
r = s.post(RPC, json=[{"jsonrpc": "2.0", "id": i, "method": m, "params": pp} for i, (m, pp) in enumerate(calls)], timeout=60)
reqs.append({"name": "quoter_identity_and_pool_state", "http_status": r.status_code, "at": now(), "n_calls": len(calls),
             "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(), "elapsed_s": round(time.time()-t0, 3)})
res = r.json()
out = {"at_utc": now(), "pinned_block": prev["pinned_block"], "quoter": QUOTER,
       "quoter_factory": None, "quoter_weth9": None, "pool_states": {}}
if res[0].get("result") and len(res[0]["result"]) >= 66: out["quoter_factory"] = "0x" + res[0]["result"][-40:]
if res[1].get("result") and len(res[1]["result"]) >= 66: out["quoter_weth9"] = "0x" + res[1]["result"][-40:]
for k, p in enumerate(pool_list):
    liq = res[2 + k*2].get("result")
    slot0 = res[3 + k*2].get("result")
    out["pool_states"][p] = {
        "liquidity": str(int(liq, 16)) if liq and liq != "0x" else None,
        "sqrtPriceX96": str(int(slot0[2:66], 16)) if slot0 and len(slot0) >= 66 else None,
        "tick": int(int(slot0[66:130], 16) - 2**256) if slot0 and len(slot0) >= 130 and int(slot0[66:130], 16) > 2**255 else (int(slot0[66:130], 16) if slot0 and len(slot0) >= 130 else None)}
out["requests"] = reqs
json.dump(out, open(BASE + r"\final_check.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1)[:3000])
