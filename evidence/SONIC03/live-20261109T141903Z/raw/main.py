import json, time, hashlib, datetime
import requests
from Crypto.Hash import keccak
BASE = r"D:\ds-arb-test\watch_market\evidence\SONIC03\live-20261109T141903Z\raw"
PROXY = "http://127.0.0.1:7897"
RPC = "https://rpc.soniclabs.com"
s = requests.Session(); s.trust_env = False
s.proxies = {"http": PROXY, "https": PROXY}
s.headers.update({"User-Agent": "watch_market-readonly-research/1.0", "Content-Type": "application/json"})
now = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
reqs = []
def sel(sig):
    h = keccak.new(digest_bits=256); h.update(sig.encode()); return "0x" + h.hexdigest()[:8]
def enc(a): return a[2:].rjust(64, "0")
def save(n, o):
    json.dump(o, open(BASE + "\\" + n, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
def batch(calls, name):
    t0 = time.time()
    r = s.post(RPC, json=[{"jsonrpc": "2.0", "id": k, "method": m, "params": p} for k, (m, p) in enumerate(calls)], timeout=60)
    reqs.append({"name": name, "http_status": r.status_code, "at": now(), "n_calls": len(calls),
                 "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(),
                 "elapsed_s": round(time.time()-t0, 3)})
    d = r.json()
    if isinstance(d, dict): d = [d]
    return d
out = {"started_at_utc": now()}
POOL = "0x5362dBb1e601abF3a4c14c22ffEdA64042E5eAA3"
USDC = "0x29219dd400f2Bf60E5a23d13Be72B486D4038894"
WS = "0x039e2fB66102314Ce7b64Ce5Ce3E5183bc94aD38"
SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
calls = [("eth_chainId", []), ("eth_blockNumber", []), ("eth_getBlockByNumber", ["latest", False]),
         ("eth_getCode", [POOL, "latest"]), ("eth_getStorageAt", [POOL, SLOT, "latest"]),
         ("eth_call", [{"to": POOL, "data": sel("getReservesList()")}, "latest"]),
         ("eth_call", [{"to": POOL, "data": sel("getReserveData(address)") + enc(USDC)}, "latest"]),
         ("eth_call", [{"to": POOL, "data": sel("getReserveData(address)") + enc(WS)}, "latest"]),
         ("eth_call", [{"to": POOL, "data": sel("ADDRESSES_PROVIDER()")}, "latest"])]
res = batch(calls, "aave_identity")
out["chain_id"] = int(res[0]["result"], 16)
out["latest_block"] = int(res[1]["result"], 16)
blk = res[2]["result"]
out["latest_block_time_utc"] = datetime.datetime.fromtimestamp(int(blk["timestamp"], 16), datetime.timezone.utc).isoformat()
out["pinned_block"] = out["latest_block"] - 5
def code_bytes(r): return (len(r.get("result") or "0x")-2)//2
def num(v): return int(v, 16) if v and v != "0x" else None
def addr(v): return ("0x" + v[-40:]) if v and len(v) >= 66 else None
out["pool_code_bytes"] = code_bytes(res[3])
impl = res[4].get("result")
out["pool_impl"] = ("0x" + impl[-40:]) if impl and len(impl) >= 66 else None
def decode_array_addr(v):
    if not v or v == "0x": return []
    h = v[2:]; off = int(h[0:64], 16)*2; ln = int(h[off:off+64], 16); o = []
    for k in range(ln):
        st = off + 64 + k*64
        o.append("0x" + h[st:st+64][-40:])
    return o
out["reserves"] = decode_array_addr(res[5].get("result"))
out["addresses_provider"] = addr(res[8].get("result"))
def decode_reserve(v):
    if not v or v == "0x": return None
    h = v[2:]
    w = [h[i*64:(i+1)*64] for i in range(len(h)//64)]
    if len(w) < 15: return {"words": len(w)}
    cfg = int(w[0], 16)
    d = {"configuration": hex(cfg), "ltv_bps": cfg & 0xFFFF, "liq_threshold_bps": (cfg >> 16) & 0xFFFF,
         "liq_bonus_bps": (cfg >> 32) & 0xFFFF, "decimals": (cfg >> 48) & 0xFF,
         "active": bool((cfg >> 56) & 1), "frozen": bool((cfg >> 57) & 1),
         "borrowing_enabled": bool((cfg >> 58) & 1), "paused": bool((cfg >> 60) & 1),
         "liquidityIndex": int(w[1], 16), "currentLiquidityRate_ray": int(w[2], 16),
         "variableBorrowIndex": int(w[3], 16), "currentVariableBorrowRate_ray": int(w[4], 16),
         "lastUpdateTimestamp": int(w[6], 16), "id": int(w[7], 16),
         "aToken": addr(w[8]), "stableDebtToken": addr(w[9]), "variableDebtToken": addr(w[10]),
         "interestRateStrategy": addr(w[11])}
    return d
rd_usdc = decode_reserve(res[6].get("result"))
rd_ws = decode_reserve(res[7].get("result"))
out["reserve_USDC"] = rd_usdc
out["reserve_wS"] = rd_ws
save("aave_identity.json", out)
time.sleep(0.3)
# second batch: aToken/vDebt totalSupply for USDC and wS (supply/borrow actual)
calls2 = []
labels = []
for name, rd in [("USDC", rd_usdc), ("wS", rd_ws)]:
    if not rd: continue
    for key, fn in [("aToken_totalSupply", "totalSupply()"), ("vDebt_totalSupply", "totalSupply()")]:
        a = rd.get("aToken") if key.startswith("aToken") else rd.get("variableDebtToken")
        if a:
            calls2.append(("eth_call", [{"to": a, "data": sel(fn)}, hex(out["pinned_block"])]))
            labels.append(f"{name}:{key}")
res2 = batch(calls2, "token_totals") if calls2 else []
out["token_totals"] = {lab: (str(num(rr.get("result"))) if rr.get("result") else None) for lab, rr in zip(labels, res2)}
out["finished_at_utc"] = now()
out["requests"] = reqs
out["request_count"] = len(reqs)
save("sonic03_summary.json", out)
print(json.dumps(out, ensure_ascii=False, indent=1)[:9000])
