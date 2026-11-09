import json, time, hashlib, datetime
import requests
from Crypto.Hash import keccak
BASE = r"D:\ds-arb-test\watch_market\evidence\AVAX02\live-20261109T141903Z\raw"
PROXY = "http://127.0.0.1:7897"
RPC = "https://api.avax.network/ext/bc/C/rpc"
s = requests.Session(); s.trust_env = False
s.proxies = {"http": PROXY, "https": PROXY}
s.headers.update({"User-Agent": "watch_market-readonly-research/1.0", "Content-Type": "application/json"})
now = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
def sel(sig):
    h = keccak.new(digest_bits=256); h.update(sig.encode()); return "0x" + h.hexdigest()[:8]
prev = json.load(open(BASE + r"\avax02_summary.json", encoding="utf-8"))
pinned = hex(prev["pinned_block"])
PAIRS = {"pangolin_wavax_savax": "0x4E9A38F05c38106C1cf5c145Df24959ec50ff70D",
         "traderjoe_v1_wavax_savax": "0x4b946c91C2B1a7d7C40FB3C130CdfBaf8389094d",
         "traderjoe_v21_wavax_savax": "0x883eA72c2A46F7AcB3820855344C43666c6cc5c0"}
calls = []; tags = []
for name, p in PAIRS.items():
    calls.append(("eth_getCode", [p, pinned])); tags.append((name, "code"))
    for f in ["token0()", "token1()", "getReserves()"]:
        calls.append(("eth_call", [{"to": p, "data": sel(f)}, pinned])); tags.append((name, f))
    for f in ["getTokenX()", "getTokenY()", "getBinStep()", "getActiveId()"]:
        calls.append(("eth_call", [{"to": p, "data": sel(f)}, pinned])); tags.append((name, f))
calls.append(("eth_getBlockByNumber", [pinned, False])); tags.append(("block", "pinned_info"))
t0 = time.time()
r = s.post(RPC, json=[{"jsonrpc": "2.0", "id": i, "method": m, "params": pp} for i, (m, pp) in enumerate(calls)], timeout=60)
res = r.json()
out = {"at_utc": now(), "pinned_block": prev["pinned_block"], "requests_meta": {"http_status": r.status_code,
       "n_calls": len(calls), "sha256": hashlib.sha256(r.content).hexdigest(), "elapsed_s": round(time.time()-t0, 3)}}
data = {}
blockinfo = None
for (name, kind), rr in zip(tags, res):
    v = rr.get("result")
    if name == "block":
        blockinfo = v; continue
    data.setdefault(name, {})
    if kind == "code": data[name]["code_bytes"] = (len(v or "0x")-2)//2
    elif kind == "getReserves()": data[name]["reserves_raw"] = v
    elif kind in ("token0()", "token1()", "getTokenX()", "getTokenY()"):
        data[name][kind] = ("0x" + v[-40:]) if v and len(v) >= 66 else None
    elif kind == "getBinStep()":
        data[name][kind] = int(v, 16) if v and v != "0x" else None
    elif kind == "getActiveId()":
        raw = int(v, 16) if v and v != "0x" else None
        data[name][kind] = (raw - 2**32 if raw and raw > 2**31 else raw) if raw is not None else None
out["pairs"] = data
out["pinned_block_time_utc"] = datetime.datetime.fromtimestamp(int(blockinfo["timestamp"], 16), datetime.timezone.utc).isoformat() if blockinfo else None
WAVAX = "0xb31f66aa3c1e785363f0875a1b74e27b85fd66c7"
SAVAX = "0x2b2c81e08f1af8835a78bb2a90ae924ace0ea4be"
# compute for UniV2-like pairs: sAVAX -> WAVAX output for tiers, fee assumptions
tiers = [10**18, 10*10**18, 100*10**18]
results = {}
for name in ["pangolin_wavax_savax", "traderjoe_v1_wavax_savax"]:
    d = data.get(name, {})
    t0_, t1_ = d.get("token0()"), d.get("token1()")
    rv = d.get("reserves_raw")
    if not (t0_ and t1_ and rv and len(rv) >= 130): continue
    r0 = int(rv[2:66], 16); r1 = int(rv[66:130], 16)
    if t0_ == SAVAX and t1_ == WAVAX: in_res, out_res = r0, r1
    elif t0_ == WAVAX and t1_ == SAVAX: in_res, out_res = r1, r0
    else: continue
    rows = []
    for amt in tiers:
        for fee in [0.002, 0.003]:
            dx = int(amt * (1 - fee))
            out_raw = out_res * dx // (in_res + dx)
            rows.append({"amount_in_sAVAX": amt / 10**18, "fee_assumption": fee,
                         "out_WAVAX": out_raw / 10**18,
                         "out_per_in": out_raw / amt,
                         "net_vs_redemption_pct": (out_raw / amt) / 1.2938400259821974 * 100 - 100})
    results[name] = {"token0": t0_, "token1": t1_, "reserve0_raw": str(r0), "reserve1_raw": str(r1),
                     "spot_WAVAX_per_sAVAX_gross": (out_res / in_res),
                     "quotes": rows}
out["univ2_quotes"] = results
# LB spot for traderjoe v2.1 pair
d = data.get("traderjoe_v21_wavax_savax", {})
if d.get("getBinStep()") and d.get("getActiveId()") is not None:
    ratio = (1 + d["getBinStep()"]/1e4) ** (d["getActiveId()"] - 2**23)
    tx, ty = d.get("getTokenX()"), d.get("getTokenY()")
    decX = 18; decY = 18
    spot = ratio * (10 ** (decX - decY))
    if tx == SAVAX and ty == WAVAX:
        out["lb_spot"] = {"tokenX": tx, "tokenY": ty, "binStep": d["getBinStep()"], "activeId": d["getActiveId()"],
                          "spot_WAVAX_per_sAVAX": spot, "net_vs_redemption_pct": spot / 1.2938400259821974 * 100 - 100}
out["requests"] = prev.get("requests", []) + [{"name": "pairs_state", **out["requests_meta"]}]
out["request_count"] = len(out["requests"])
json.dump(out, open(BASE + r"\dex_pairs.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps({k: out[k] for k in ["pinned_block", "pinned_block_time_utc", "pairs", "univ2_quotes", "lb_spot",
    "request_count", "requests_meta"] if k in out}, ensure_ascii=False, indent=1)[:6000])
