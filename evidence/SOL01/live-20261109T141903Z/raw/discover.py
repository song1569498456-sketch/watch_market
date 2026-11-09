import json, time, datetime, hashlib
import requests
BASE = r"D:\ds-arb-test\watch_market\evidence\SOL01\live-20261109T141903Z\raw"
PROXY = "http://127.0.0.1:7897"
s = requests.Session(); s.trust_env = False
s.proxies = {"http": PROXY, "https": PROXY}
s.headers.update({"User-Agent": "watch_market-readonly-research/1.0"})
now = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
reqs = []
def get(url, name):
    t0 = time.time()
    try:
        r = s.get(url, timeout=30)
        reqs.append({"url": url, "name": name, "http_status": r.status_code, "at": now(),
                     "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(),
                     "elapsed_s": round(time.time()-t0, 3)})
        return r
    except Exception as e:
        reqs.append({"url": url, "name": name, "error": repr(e), "at": now()})
        return None

out = {"started_at_utc": now()}
# Raydium: standard (CPMM) pools by tvl
r = get("https://api-v3.raydium.io/pools/info/list?poolType=standard&poolSortField=liquidity&sortType=desc&pageSize=100&page=1", "raydium_standard")
ray = []
if r and r.status_code == 200:
    try:
        d = r.json()
        arr = (d.get("data") or {}).get("data") or []
        for p in arr:
            ray.append({"id": p.get("id"), "type": p.get("type"), "programId": p.get("programId"),
                        "mintA": (p.get("mintA") or {}).get("address"), "mintB": (p.get("mintB") or {}).get("address"),
                        "symbolA": (p.get("mintA") or {}).get("symbol"), "symbolB": (p.get("mintB") or {}).get("symbol"),
                        "tvl": p.get("tvl"), "feeRate": p.get("feeRate"), "day_volume": (p.get("day") or {}).get("volume")})
    except Exception as e:
        out["ray_parse_error"] = repr(e)
out["ray_standard"] = ray[:100]
json.dump({"retrieved_at_utc": now(), "pools": ray}, open(BASE + r"\raydium_standard.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
time.sleep(0.4)

r = get("https://api.orca.so/v2/solana/pools?limit=100", "orca_pools100")
orca = []
if r and r.status_code == 200:
    try:
        d = r.json()
        arr = d.get("data", d if isinstance(d, list) else [])
        for p in arr:
            orca.append({k: p.get(k) for k in ["address", "tokenMintA", "tokenMintB", "feeRate", "tickSpacing",
                                               "liquidity", "sqrtPrice", "tickCurrentIndex", "tokenA", "tokenB"]})
    except Exception as e:
        out["orca_parse_error"] = repr(e)
json.dump({"retrieved_at_utc": now(), "pools": orca}, open(BASE + r"\orca_pools100.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
out["orca_count"] = len(orca)

# intersect mint pairs
orca_pairs = {}
for p in orca:
    a, b = p.get("tokenMintA"), p.get("tokenMintB")
    if a and b:
        orca_pairs[frozenset([a, b])] = p
matches = []
for p in ray:
    a, b = p.get("mintA"), p.get("mintB")
    if not a or not b: continue
    o = orca_pairs.get(frozenset([a, b]))
    if o:
        matches.append({"raydium_pool": p, "orca_pool": o,
                        "ray_tvl": p.get("tvl"), "orca_liquidity": o.get("liquidity")})
matches.sort(key=lambda x: -(x["ray_tvl"] or 0))
out["common_pairs_with_raydium_standard"] = matches[:10]
out["finished_at_utc"] = now()
out["requests"] = reqs
json.dump(out, open(BASE + r"\pair_discovery.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps({k: out[k] for k in ["common_pairs_with_raydium_standard", "ray_standard", "orca_count", "requests", "started_at_utc", "finished_at_utc"] if k in out}, ensure_ascii=False, indent=1)[:9000])
