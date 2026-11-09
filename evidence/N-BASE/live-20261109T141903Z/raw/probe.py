import json, time, hashlib, datetime, struct
import requests
BASE = r"D:\ds-arb-test\watch_market\evidence\N-BASE\live-20261109T141903Z\raw"
PROXY = "http://127.0.0.1:7897"
RPC = "https://mainnet.base.org"
s = requests.Session(); s.trust_env = False
s.proxies = {"http": PROXY, "https": PROXY}
s.headers.update({"User-Agent": "watch_market-readonly-research/1.0", "Content-Type": "application/json"})
now = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
reqs = []
def save(name, obj):
    json.dump(obj, open(BASE + "\\" + name, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
def batch(calls, name):
    t0 = time.time()
    payload = [{"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls)]
    try:
        r = s.post(RPC, json=payload, timeout=60)
        reqs.append({"name": name, "http_status": r.status_code, "at": now(), "methods": [m for m, _ in calls],
                     "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(),
                     "elapsed_s": round(time.time()-t0, 3)})
        return r.json()
    except Exception as e:
        reqs.append({"name": name, "error": repr(e), "at": now()})
        return None
res = batch([("eth_chainId", []), ("eth_blockNumber", []),
             ("eth_getBlockByNumber", ["latest", False])], "chain_identity")
ids = {x.get("id"): x for x in res} if isinstance(res, list) else {}
chain_id = int(ids.get(0, {}).get("result", "0x0"), 16) if ids.get(0, {}).get("result") else None
block_hex = ids.get(1, {}).get("result")
block = int(block_hex, 16) if block_hex else None
blk = ids.get(2, {}).get("result") or {}
out = {"started_at_utc": now(), "chain_id": chain_id, "chain_id_hex": hex(chain_id) if chain_id else None,
       "latest_block": block, "latest_block_time_utc": datetime.datetime.fromtimestamp(int(blk["timestamp"], 16), datetime.timezone.utc).isoformat() if blk.get("timestamp") else None,
       "base_fee_wei": blk.get("baseFeePerGas"), "gas_used": blk.get("gasUsed")}
time.sleep(0.4)

FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"
REGISTRY = "0x5C3F18F06CC09CA1910767A34a20F771039E37C0"
# batch: codes + allPoolsLength (selector 0x... compute keccak? use known selector via eth_call with function sig bytes)
# sel(keccak("allPoolsLength()")[:4]) - compute with pycryptodome if available else use hardcoded known value
try:
    from Crypto.Hash import keccak as _k
    def sel(sig):
        h = _k.new(digest_bits=256); h.update(sig.encode()); return "0x" + h.hexdigest()[:8]
    have_keccak = True
except Exception:
    have_keccak = False
    def sel(sig):
        known = {"allPoolsLength()": "0x584f5fa1", "allPools(uint256)": "0x41d1de97",
                 "isPool(address)": "0xbab0b4ae", "token0()": "0x0dfe1681", "token1()": "0xd21220a7",
                 "stable()": "0x22be3de1", "factory()": "0xc45a0155"}
        return known.get(sig, "0x")
out["selector_source"] = "pycryptodome_keccak" if have_keccak else "hardcoded_known"
res = batch([("eth_getCode", [FACTORY, "latest"]), ("eth_getCode", [REGISTRY, "latest"]),
             ("eth_call", [{"to": FACTORY, "data": sel("allPoolsLength()")}, "latest"])], "factory_identity")
r = {x.get("id"): x for x in res} if isinstance(res, list) else {}
fac_code = r.get(0, {}).get("result"); reg_code = r.get(1, {}).get("result")
out["factory_code_bytes"] = (len(fac_code)-2)//2 if fac_code else None
out["factory_code_head"] = fac_code[:80] if fac_code else None
out["registry_code_bytes"] = (len(reg_code)-2)//2 if reg_code else None
out["registry_code_head"] = reg_code[:80] if reg_code else None
len_res = r.get(2, {}).get("result")
out["all_pools_length_raw"] = len_res
out["all_pools_length"] = int(len_res, 16) if len_res and len_res != "0x" else None
save("identity.json", out)
time.sleep(0.4)

# --- identify PoolCreated topic0 from recent logs (no topic filter, small range) ---
PROBE_RANGE = 300
res = batch([("eth_getLogs", [{"address": FACTORY, "fromBlock": hex((block or 1) - PROBE_RANGE),
                               "toBlock": hex(block or 1)}])], "factory_logs_probe")
j = res[0] if isinstance(res, list) else {}
logs = j.get("result") or []
out["probe_logs_count"] = len(logs)
out["probe_logs_error"] = j.get("error")
topic_shapes = {}
for lg in logs:
    key = (len(lg.get("topics", [])), len(lg.get("data", "0x"))//2 - 1)
    topic_shapes.setdefault(str(key), 0)
    topic_shapes[str(key)] += 1
out["probe_log_topic_shapes"] = topic_shapes
# choose shape with 4 topics & data 64 bytes (pool, uint256) as PoolCreated candidate
candidate = None
for lg in logs:
    if len(lg.get("topics", [])) == 4 and (len(lg.get("data", "0x"))//2 - 1) == 64:
        candidate = lg["topics"][0]; break
out["poolcreated_topic_candidate"] = candidate
save("logs_probe.json", {"range": PROBE_RANGE, "logs": logs[:20], "shape": topic_shapes})
time.sleep(0.4)

# --- range capability test ---
range_test = {}
if candidate:
    for span in [2000, 10000]:
        res = batch([("eth_getLogs", [{"address": FACTORY, "fromBlock": hex(max(0, block-span)),
                                       "toBlock": hex(block), "topics": [candidate]}])], f"range_test_{span}")
        jj = res[0] if isinstance(res, list) else {}
        range_test[span] = {"count": len(jj.get("result") or []), "error": jj.get("error")}
        time.sleep(0.4)
        if jj.get("error"):
            break
out["range_test"] = range_test
save("range_test.json", out)
print(json.dumps(out, ensure_ascii=False, indent=1)[:5000])
