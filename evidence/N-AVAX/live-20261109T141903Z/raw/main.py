import json, time, hashlib, datetime
import requests
from Crypto.Hash import keccak
BASE = r"D:\ds-arb-test\watch_market\evidence\N-AVAX\live-20261109T141903Z\raw"
PROXY = "http://127.0.0.1:7897"
RPCS = ["https://api.avax.network/ext/bc/C/rpc", "https://avalanche-c-chain-rpc.publicnode.com"]
s = requests.Session(); s.trust_env = False
s.proxies = {"http": PROXY, "https": PROXY}
s.headers.update({"User-Agent": "watch_market-readonly-research/1.0", "Content-Type": "application/json"})
now = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
reqs = []
def sel(sig):
    h = keccak.new(digest_bits=256); h.update(sig.encode()); return "0x" + h.hexdigest()[:8]
def save(n, o):
    json.dump(o, open(BASE + "\\" + n, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
def batch(calls, name, rpc=RPCS[0], allow_fallback=False):
    payload = [{"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls)]
    for attempt_rpc in ([rpc] + ([RPCS[1]] if allow_fallback and rpc == RPCS[0] else [])):
        t0 = time.time()
        try:
            r = s.post(attempt_rpc, json=payload, timeout=60)
            reqs.append({"name": name, "rpc": attempt_rpc, "http_status": r.status_code, "at": now(),
                         "n_calls": len(calls), "bytes": len(r.content),
                         "sha256": hashlib.sha256(r.content).hexdigest(), "elapsed_s": round(time.time()-t0, 3)})
            d = r.json()
            if isinstance(d, dict): d = [d]
            if isinstance(d, list) and any("error" in x for x in d) and allow_fallback and attempt_rpc == RPCS[0]:
                continue
            return d
        except Exception as e:
            reqs.append({"name": name, "rpc": attempt_rpc, "error": repr(e), "at": now()})
            continue
    return []
def get(url, name):
    t0 = time.time()
    try:
        r = s.get(url, timeout=40)
        reqs.append({"name": name, "url": url, "http_status": r.status_code, "at": now(),
                     "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(),
                     "elapsed_s": round(time.time()-t0, 3)})
        return r
    except Exception as e:
        reqs.append({"name": name, "url": url, "error": repr(e), "at": now()})
        return None

V2 = "0x6E77932A92582f504FF6c4BdbCef7Da6c198aEEf"
V21 = "0x8e42f2F4101563bF679975178e880FD87d3eFd4e"
AAVE_POOL = "0x794a61358D6845594F94dc1DB02A252b5b4814aD"
out = {"started_at_utc": now()}
# 1 chain identity
res = batch([("eth_chainId", []), ("eth_blockNumber", []), ("eth_getBlockByNumber", ["latest", False])], "chain_identity")
m = {x.get("id"): x for x in res}
out["chain_id"] = int(m[0]["result"], 16) if m.get(0, {}).get("result") else None
block = int(m[1]["result"], 16) if m.get(1, {}).get("result") else None
blk = m[2].get("result") or {}
out["latest_block"] = block
out["latest_block_time_utc"] = datetime.datetime.fromtimestamp(int(blk["timestamp"], 16), datetime.timezone.utc).isoformat() if blk.get("timestamp") else None
out["base_fee_wei"] = blk.get("baseFeePerGas")
time.sleep(0.4)
# 2 factory + aave identity
calls = [("eth_getCode", [V2, "latest"]), ("eth_getCode", [V21, "latest"]), ("eth_getCode", [AAVE_POOL, "latest"]),
         ("eth_call", [{"to": V2, "data": sel("getNumberOfLBPairs()")}, "latest"]),
         ("eth_call", [{"to": V21, "data": sel("getNumberOfLBPairs()")}, "latest"]),
         ("eth_call", [{"to": AAVE_POOL, "data": sel("getReservesList()")}, "latest"])]
res = batch(calls, "factory_identity")
out["v2_code_bytes"] = (len(res[0].get("result", "0x"))-2)//2 if res[0].get("result") else None
out["v21_code_bytes"] = (len(res[1].get("result", "0x"))-2)//2 if res[1].get("result") else None
out["aave_pool_code_bytes"] = (len(res[2].get("result", "0x"))-2)//2 if res[2].get("result") else None
n2 = res[3].get("result"); n21 = res[4].get("result")
out["v2_pair_count"] = int(n2, 16) if n2 and n2 != "0x" else None
out["v21_pair_count"] = int(n21, 16) if n21 and n21 != "0x" else None
rl = res[5].get("result")
if rl and len(rl) >= 130:
    try:
        off = int(rl[2:66], 16); ln = int(rl[66:130], 16); out["aave_reserves_count"] = ln
    except Exception:
        out["aave_reserves_count"] = None
save("identity.json", out)
time.sleep(0.4)
# 3 newest pairs from both factories
calls = []; tags = []
for factory, cnt, tag in [(V2, out["v2_pair_count"], "v2"), (V21, out["v21_pair_count"], "v21")]:
    if cnt:
        for off in range(1, 7):
            i = cnt - off
            calls.append(("eth_call", [{"to": factory, "data": sel("getLBPairAtIndex(uint256)") + hex(i)[2:].rjust(64, "0")}, "latest"]))
            tags.append((tag, i))
res = batch(calls, "newest_pairs")
newest = []
for (tag, i), r in zip(tags, res):
    v = r.get("result")
    if v and len(v) >= 66:
        newest.append({"factory": tag, "index": i, "pair": "0x" + v[-40:]})
out["newest_pairs"] = newest
save("newest_pairs.json", out)
time.sleep(0.4)
# 4 pair metadata
calls = []; tags = []
for p in newest:
    for f in ["getTokenX()", "getTokenY()", "getBinStep()", "getFactory()", "getActiveId()", "getReserves()"]:
        calls.append(("eth_call", [{"to": p["pair"], "data": sel(f)}, "latest"])); tags.append(p)
res = batch(calls, "pair_metadata")
meta = [dict(p) for p in newest]
n = 6
for k, p in enumerate(newest):
    row = meta[k]
    for j, f in enumerate(["getTokenX()", "getTokenY()", "getBinStep()", "getFactory()", "getActiveId()", "getReserves()"]):
        v = res[k*n+j].get("result")
        if f in ("getTokenX()", "getTokenY()", "getFactory()") and v and len(v) >= 66:
            row[f] = "0x" + v[-40:]
        elif f == "getBinStep()" and v and v != "0x":
            row[f] = int(v, 16)
        elif f == "getActiveId()" and v and v != "0x":
            row[f] = int(v, 16) if int(v, 16) < 2**31 else int(v, 16) - 2**32
        elif f == "getReserves()" and v and v != "0x":
            row[f] = {"raw": v[:66], "raw2": v[66:130]}
        else:
            row[f] = v
out["pair_metadata"] = meta
save("pair_metadata.json", out)
time.sleep(0.4)
# 5 token symbols for first 2 pairs' tokens
tokens = []
for p in meta[:2]:
    if isinstance(p.get("getTokenX()"), str): tokens.append(p["getTokenX()"])
    if isinstance(p.get("getTokenY()"), str): tokens.append(p["getTokenY()"])
tokens = list(dict.fromkeys(tokens))[:6]
calls = []
for t in tokens:
    calls.append(("eth_call", [{"to": t, "data": sel("symbol()")}, "latest"]))
    calls.append(("eth_call", [{"to": t, "data": sel("decimals()")}, "latest"]))
res = batch(calls, "token_meta")
tmeta = {}
for i, t in enumerate(tokens):
    sv = res[i*2].get("result"); dv = res[i*2+1].get("result")
    sym = None
    if sv and len(sv) >= 130:
        try:
            ln = int(sv[66:130], 16)
            if ln < 100: sym = bytes.fromhex(sv[130:130+ln*2]).decode("utf-8", "replace")
        except Exception: pass
    tmeta[t] = {"symbol": sym, "decimals": int(dv, 16) if dv and dv != "0x" else None}
out["token_meta"] = tmeta
save("token_meta.json", out)
time.sleep(0.4)
# 6 getLogs attempt on V2 factory, recent blocks; fallback provider once
topic0 = "0x" + keccak.new(digest_bits=256, data=b"LBPairCreated(address,address,uint256,address,uint256)").hexdigest()
out["lbpair_created_topic0"] = topic0
from_block = max(0, (block or 1) - 5000)
res = batch([("eth_getLogs", [{"address": V2, "fromBlock": hex(from_block), "toBlock": hex(block or 1), "topics": [topic0]}])],
            "getlogs_5000", allow_fallback=True)
lg = res[0] if res else {}
out["getlogs_5000"] = {"error": lg.get("error"), "count": len(lg.get("result") or [])}
if lg.get("result"):
    out["getlogs_5000_events"] = [{"block": int(x["blockNumber"], 16), "tx": x.get("transactionHash"),
                                   "topics": x.get("topics"), "data": x.get("data")} for x in lg["result"][:5]]
save("getlogs.json", out)
time.sleep(0.4)
# 7 releases: avalanchego + joe-v2
rel = {}
for url, name in [("https://api.github.com/repos/ava-labs/avalanchego/releases?per_page=10", "avalanchego"),
                  ("https://api.github.com/repos/traderjoe-xyz/joe-v2/releases?per_page=10", "joev2")]:
    r = get(url, name)
    items = []
    if r is not None and r.status_code == 200:
        try:
            for x in r.json()[:10]:
                items.append({"tag": x.get("tag_name"), "published_at": x.get("published_at"), "prerelease": x.get("prerelease")})
        except Exception:
            pass
    rel[name] = items
    time.sleep(0.4)
out["releases"] = rel
out["finished_at_utc"] = now()
out["requests"] = reqs
out["request_count"] = len(reqs)
save("avax_summary.json", out)
print(json.dumps({"chain_id": out.get("chain_id"), "latest_block": out.get("latest_block"),
    "latest_block_time_utc": out.get("latest_block_time_utc"), "base_fee_wei": out.get("base_fee_wei"),
    "v2_code_bytes": out.get("v2_code_bytes"), "v21_code_bytes": out.get("v21_code_bytes"),
    "aave_pool_code_bytes": out.get("aave_pool_code_bytes"), "v2_pair_count": out.get("v2_pair_count"),
    "v21_pair_count": out.get("v21_pair_count"), "aave_reserves_count": out.get("aave_reserves_count"),
    "newest_pairs": out.get("newest_pairs"), "pair_metadata": out.get("pair_metadata"),
    "token_meta": out.get("token_meta"), "getlogs_5000": out.get("getlogs_5000"),
    "releases": out.get("releases"), "request_count": out.get("request_count"), "requests": reqs},
    ensure_ascii=False, indent=1)[:12000])
