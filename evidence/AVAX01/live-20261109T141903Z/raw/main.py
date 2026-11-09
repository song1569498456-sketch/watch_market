import json, time, hashlib, datetime
import requests
from Crypto.Hash import keccak
BASE = r"D:\ds-arb-test\watch_market\evidence\AVAX01\live-20261109T141903Z\raw"
PROXY = "http://127.0.0.1:7897"
RPC = "https://api.avax.network/ext/bc/C/rpc"
s = requests.Session(); s.trust_env = False
s.proxies = {"http": PROXY, "https": PROXY}
s.headers.update({"User-Agent": "watch_market-readonly-research/1.0", "Content-Type": "application/json"})
now = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
reqs = []
def sel(sig):
    h = keccak.new(digest_bits=256); h.update(sig.encode()); return "0x" + h.hexdigest()[:8]
def save(n, o):
    json.dump(o, open(BASE + "\\" + n, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
def batch(calls, name, pinned="latest"):
    t0 = time.time()
    payload = [{"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls)]
    try:
        r = s.post(RPC, json=payload, timeout=60)
        reqs.append({"name": name, "http_status": r.status_code, "at": now(), "n_calls": len(calls),
                     "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(),
                     "elapsed_s": round(time.time()-t0, 3)})
        d = r.json()
        if isinstance(d, dict): d = [d]
        return d
    except Exception as e:
        reqs.append({"name": name, "error": repr(e), "at": now()})
        return []
def decode_str(v):
    if not v or len(v) < 130: return None
    try:
        h = v[2:]; ln = int(h[64:128], 16)
        if ln > 100: return None
        return bytes.fromhex(h[128:128+ln*2]).decode("utf-8", "replace")
    except Exception:
        return None

POOL = "0x7f90122BF0700F9E7e1F688fe926940E8839F353"
NATIVE_USDC = "0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E"
out = {"started_at_utc": now()}
# 1) chain
res = batch([("eth_chainId", []), ("eth_blockNumber", []), ("eth_getBlockByNumber", ["latest", False])], "chain_identity")
m = {x.get("id"): x for x in res}
out["chain_id"] = int(m[0]["result"], 16) if m.get(0, {}).get("result") else None
block = int(m[1]["result"], 16) if m.get(1, {}).get("result") else None
blk = m[2].get("result") or {}
out["latest_block"] = block
out["latest_block_time_utc"] = datetime.datetime.fromtimestamp(int(blk["timestamp"], 16), datetime.timezone.utc).isoformat() if blk.get("timestamp") else None
out["base_fee_wei"] = blk.get("baseFeePerGas")
out["pinned_block"] = block - 5 if block else None
pinned = hex(out["pinned_block"]) if out.get("pinned_block") else "latest"
time.sleep(0.4)
# 2) pool static + token identity (pinned block)
def call(to, data): return ("eth_call", [{"to": to, "data": data}, pinned])
calls = [("eth_getCode", [POOL, pinned])]
tags = ["pool_code"]
for i in range(3):
    calls.append(call(POOL, sel("coins(uint256)") + hex(i)[2:].rjust(64, "0"))); tags.append(f"coin_{i}")
    calls.append(call(POOL, sel("underlying_coins(uint256)") + hex(i)[2:].rjust(64, "0"))); tags.append(f"underlying_{i}")
    calls.append(call(POOL, sel("balances(uint256)") + hex(i)[2:].rjust(64, "0"))); tags.append(f"balance_{i}")
calls += [call(POOL, sel("A()")), call(POOL, sel("fee()"))]; tags += ["A", "fee"]
time.sleep(0.4)
res = batch(calls, "pool_static")
vals = {}
for tag, rr in zip(tags, res):
    v = rr.get("result")
    if tag == "pool_code":
        vals[tag] = (len(v or "0x")-2)//2
    elif v and len(v) >= 66:
        words = [v[2+i*64:2+(i+1)*64] for i in range(len(v)//64)]
        vals[tag] = int(words[0], 16)
out["static_raw"] = vals
coins = ["0x" + hex(vals.get(f"coin_{i}", 0))[-40:] if vals.get(f"coin_{i}") else None for i in range(3)]
underlying = ["0x" + hex(vals.get(f"underlying_{i}", 0))[-40:] if vals.get(f"underlying_{i}") else None for i in range(3)]
out["coins"] = coins; out["underlying_coins"] = underlying
out["balances"] = [str(vals.get(f"balance_{i}")) for i in range(3)]
out["A"] = vals.get("A"); out["fee"] = vals.get("fee")
# token meta: underlying + wrapped + native USDC
tokens = list(dict.fromkeys([t for t in underlying if t] + [t for t in coins if t] + [NATIVE_USDC]))
calls = []; tags = []
for t in tokens:
    calls.append(call(t, sel("symbol()"))); tags.append(("symbol", t))
    calls.append(call(t, sel("decimals()"))); tags.append(("decimals", t))
time.sleep(0.4)
res = batch(calls, "token_meta")
tmeta = {}
for (kind, t), rr in zip(tags, res):
    v = rr.get("result")
    tmeta.setdefault(t, {})
    if kind == "symbol": tmeta[t]["symbol"] = decode_str(v)
    else: tmeta[t]["decimals"] = int(v, 16) if v and v != "0x" else None
out["token_meta"] = tmeta
save("avax01_static.json", out)
time.sleep(0.4)
# 3) same-block sequential quotes: DAI.e(0)->USDC.e(1)->USDT.e(2)->DAI.e(0)
def dy_data(i, j, dx):
    return sel("get_dy_underlying(int128,int128,uint256)") + f"{i:064x}" + f"{j:064x}" + f"{dx:064x}"
def quote_leg(i, j, inputs):
    calls = [call(POOL, dy_data(i, j, x)) for x in inputs]
    res = batch(calls, f"quote_leg_{i}_to_{j}")
    return [int(rr["result"], 16) if rr.get("result") and rr["result"] != "0x" else None for rr in res]
tiers = [10**18, 10*10**18, 100*10**18, 1000*10**18]  # DAI.e 18 decimals
time.sleep(0.4)
leg1 = quote_leg(0, 1, tiers)   # [10**18, 10*10**18, 100*10**18, 1000*10**18]
time.sleep(0.4)
leg2 = quote_leg(1, 2, [x for x in leg1 if x]) if all(leg1) else []
time.sleep(0.4)
leg3 = quote_leg(2, 0, [x for x in leg2 if x]) if leg2 and all(leg2) else []
rows = []
if all(leg1) and all(leg2) and all(leg3):
    for k in range(len(tiers)):
        rows.append({"amount_in_dai_18": str(tiers[k]),
                     "leg1_dai_to_usdce_raw": str(leg1[k]),
                     "leg2_usdce_to_usdte_raw": str(leg2[k]),
                     "leg3_usdte_to_dai_raw": str(leg3[k]),
                     "final_dai": str(leg3[k] / 10**18),
                     "net_bps": str((leg3[k] - tiers[k]) / tiers[k] * 10000)})
out["cycle_quotes"] = rows
out["quote_note"] = "三条腿都在 pinned 块同一 Curve 池内分别 get_dy_underlying，前腿输出作为后腿输入；但 Curve view 不更新储备，同一池重复使用时储备影响未在 view 内传递（缺口，已在报告中标注）。"
out["finished_at_utc"] = now()
out["requests"] = reqs
out["request_count"] = len(reqs)
save("avax01_quotes.json", out)
print(json.dumps({"chain_id": out.get("chain_id"), "latest_block": out.get("latest_block"),
    "latest_block_time_utc": out.get("latest_block_time_utc"), "pinned_block": out.get("pinned_block"),
    "pool_code_bytes": out["static_raw"].get("pool_code"), "coins": out.get("coins"),
    "underlying": out.get("underlying_coins"), "balances": out.get("balances"), "A": out.get("A"),
    "fee": out.get("fee"), "token_meta": tmeta, "cycle_quotes": rows, "request_count": out["request_count"],
    "requests": reqs}, ensure_ascii=False, indent=1)[:12000])
