import json, time, hashlib, datetime
import requests
from Crypto.Hash import keccak
BASE = r"D:\ds-arb-test\watch_market\evidence\N-BASE\live-20261109T141903Z\raw"
PROXY = "http://127.0.0.1:7897"
RPC = "https://mainnet.base.org"
s = requests.Session(); s.trust_env = False
s.proxies = {"http": PROXY, "https": PROXY}
s.headers.update({"User-Agent": "watch_market-readonly-research/1.0", "Content-Type": "application/json"})
now = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
reqs = []
def sel(sig):
    h = keccak.new(digest_bits=256); h.update(sig.encode()); return "0x" + h.hexdigest()[:8]
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
        data = r.json()
        if isinstance(data, dict): data = [data]
        return data
    except Exception as e:
        reqs.append({"name": name, "error": repr(e), "at": now()})
        return []
def http(url, name):
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

FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"
REGISTRY = "0x5C3F18F06CC09CA1910767A34a20F771039E37C0"
EIP1967_IMPL = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
out = {"started_at_utc": now()}
# chain identity refresh
res = batch([("eth_chainId", []), ("eth_blockNumber", []),
             ("eth_getBlockByNumber", ["latest", False])], "chain_identity")
m = {x.get("id"): x for x in res}
chain_id = int(m[0]["result"], 16); block = int(m[1]["result"], 16)
blk = m[2]["result"]
out.update({"chain_id": chain_id, "latest_block": block,
            "latest_block_time_utc": datetime.datetime.fromtimestamp(int(blk["timestamp"], 16), datetime.timezone.utc).isoformat(),
            "base_fee_wei": blk.get("baseFeePerGas")})
time.sleep(0.4)
# factory length, proxy impl slot, newest allPools indices
LEN = int(batch([("eth_call", [{"to": FACTORY, "data": sel("allPoolsLength()")}, "latest"])], "pools_length")[0]["result"], 16)
out["all_pools_length"] = LEN
idx = list(range(LEN-1, max(LEN-21, 0), -1))[:20]
calls = [("eth_getStorageAt", [FACTORY, EIP1967_IMPL, "latest"]),
         ("eth_call", [{"to": FACTORY, "data": sel("implementation()")}, "latest"])]
calls += [("eth_call", [{"to": FACTORY, "data": sel("allPools(uint256)") + hex(i)[2:].rjust(64, "0")}, "latest"]) for i in idx]
time.sleep(0.4)
res = batch(calls, "factory_proxy_and_newest_pools")
out["factory_impl_slot"] = res[0].get("result")
out["factory_implementation_call"] = res[1].get("result")
newest = []
for k, i in enumerate(idx):
    v = res[2 + k].get("result")
    if v and len(v) >= 66:
        newest.append({"index": i, "pool": "0x" + v[-40:]})
out["newest_pools_by_index"] = newest
save("factory_proxy_newest.json", out)
time.sleep(0.4)
# pool metadata for newest pools
calls = []
for p in newest:
    for f in ["token0()", "token1()", "stable()", "factory()", "fee()"]:
        calls.append(("eth_call", [{"to": p["pool"], "data": sel(f)}, "latest"]))
res = batch(calls, "newest_pool_metadata")
meta = []
n = 5
for k, p in enumerate(newest):
    row = dict(p)
    for j, f in enumerate(["token0()", "token1()", "stable()", "factory()", "fee()"]):
        v = res[k*n + j].get("result")
        row[f] = ("0x" + v[-40:]) if f in ("token0()", "token1()", "factory()") and v and len(v) >= 66 else v
    meta.append(row)
out["newest_pool_metadata"] = meta
save("newest_pool_metadata.json", out)
time.sleep(0.4)
# code presence + creation info via Blockscout for first 3 newest pools
pool_list = [p["pool"] for p in newest[:5]]
res = batch([("eth_getCode", [a, "latest"]) for a in pool_list], "newest_pool_code")
out["newest_pool_code_bytes"] = [(len(r.get("result", "0x"))-2)//2 if r.get("result") else None for r in res]
out["factory_impl_address"] = ("0x" + out["factory_impl_slot"][-40:]) if out.get("factory_impl_slot") and out["factory_impl_slot"] != "0x" + "00"*32 else None
save("newest_pool_code.json", out)
time.sleep(0.4)
# Blockscout public explorer API (no key) for creation info
bc = {}
for p in newest[:3]:
    r = http(f"https://base.blockscout.com/api/v2/addresses/{p['pool']}", f"blockscout_{p['index']}")
    if r is not None and r.status_code == 200:
        try:
            j = r.json()
            bc[p["pool"]] = {"creation_transaction_hash": j.get("creation_transaction_hash"),
                             "creation_status": j.get("creation_status"),
                             "creator_address_hash": j.get("creator_address_hash"),
                             "is_contract": j.get("is_contract"), "coin_balance": j.get("coin_balance"),
                             "name": j.get("name")}
        except Exception as e:
            bc[p["pool"]] = {"parse_error": repr(e)}
    else:
        bc[p["pool"]] = {"http_status": getattr(r, "status_code", None), "error": "not ok"}
    time.sleep(0.4)
out["blockscout_creation"] = bc
# base/base releases (GitHub API, no key) for 30-day rule window
r = http("https://api.github.com/repos/base/base/releases?per_page=10", "base_releases")
rel = []
if r is not None and r.status_code == 200:
    try:
        for x in r.json()[:10]:
            rel.append({"tag_name": x.get("tag_name"), "published_at": x.get("published_at"),
                        "name": x.get("name"), "prerelease": x.get("prerelease")})
    except Exception as e:
        out["rel_parse_error"] = repr(e)
out["base_releases"] = rel
out["finished_at_utc"] = now()
out["requests"] = reqs
out["request_count"] = len(reqs)
save("nbase_summary.json", out)
print(json.dumps({k: out.get(k) for k in ["started_at_utc", "finished_at_utc", "chain_id", "latest_block", "latest_block_time_utc",
    "base_fee_wei", "all_pools_length", "factory_impl_slot", "factory_implementation_call", "factory_impl_address",
    "newest_pools_by_index", "newest_pool_metadata", "newest_pool_code_bytes", "blockscout_creation", "base_releases",
    "request_count", "requests"]}, ensure_ascii=False, indent=1)[:14000])
