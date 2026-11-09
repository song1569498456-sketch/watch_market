import json, time, hashlib, datetime
import requests
BASE = r"D:\ds-arb-test\watch_market\evidence\BASE03\live-20261109T141903Z\raw"
PROXY = "http://127.0.0.1:7897"
RPC = "https://mainnet.base.org"
s = requests.Session(); s.trust_env = False
s.proxies = {"http": PROXY, "https": PROXY}
s.headers.update({"User-Agent": "watch_market-readonly-research/1.0", "Content-Type": "application/json"})
now = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
reqs = []
def save(n, o):
    json.dump(o, open(BASE + "\\" + n, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
def post(url, payload, name):
    t0 = time.time()
    try:
        r = s.post(url, json=payload, timeout=40)
        reqs.append({"name": name, "url": url, "http_status": r.status_code, "at": now(), "bytes": len(r.content),
                     "sha256": hashlib.sha256(r.content).hexdigest(), "elapsed_s": round(time.time()-t0, 3)})
        return r
    except Exception as e:
        reqs.append({"name": name, "url": url, "error": repr(e), "at": now()})
        return None
def get(url, name):
    t0 = time.time()
    try:
        r = s.get(url, timeout=40)
        reqs.append({"name": name, "url": url, "http_status": r.status_code, "at": now(), "bytes": len(r.content),
                     "sha256": hashlib.sha256(r.content).hexdigest(), "elapsed_s": round(time.time()-t0, 3)})
        return r
    except Exception as e:
        reqs.append({"name": name, "url": url, "error": repr(e), "at": now()})
        return None

out = {"started_at_utc": now()}
# 1) chain identity
r = post(RPC, [{"jsonrpc": "2.0", "id": 0, "method": "eth_chainId", "params": []},
               {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []},
               {"jsonrpc": "2.0", "id": 2, "method": "eth_getBlockByNumber", "params": ["latest", False]}], "chain_identity")
if r is not None and r.status_code == 200:
    d = {x.get("id"): x for x in r.json()}
    out["chain_id"] = int(d[0]["result"], 16)
    out["latest_block"] = int(d[1]["result"], 16)
    blk = d[2]["result"]
    out["latest_block_time_utc"] = datetime.datetime.fromtimestamp(int(blk["timestamp"], 16), datetime.timezone.utc).isoformat()
    out["pinned_block"] = out["latest_block"] - 5
time.sleep(0.4)
# 2) Morpho API: Base vaults (GraphQL, no key)
q = {"query": "{ vaults(first: 10, where: {chainId_in: [8453]}) { items { address name asset { address symbol } } } }"}
r = post("https://api.morpho.org/graphql", q, "morpho_vaults")
morpho = []
if r is not None and r.status_code == 200:
    try:
        j = r.json()
        items = (((j.get("data") or {}).get("vaults") or {}).get("items")) or []
        for it in items:
            morpho.append({"address": it.get("address"), "name": it.get("name"),
                           "asset": (it.get("asset") or {}).get("address"),
                           "assetSymbol": (it.get("asset") or {}).get("symbol")})
    except Exception as e:
        out["morpho_parse_error"] = repr(e)
    out["morpho_raw_head"] = r.text[:500]
out["morpho_vaults"] = morpho
time.sleep(0.4)
# 3) Beefy Base vaults + tvl (fallback/complement)
r = get("https://api.beefy.finance/vaults", "beefy_vaults")
beefy = []
if r is not None and r.status_code == 200:
    try:
        for v in r.json():
            if v.get("chain") == "base":
                beefy.append({"id": v.get("id"), "name": v.get("name"), "tokenAddress": (v.get("tokenAddress") or ""),
                              "want": v.get("want"), "earnContractAddress": v.get("earnContractAddress"),
                              "platform": v.get("platform")})
    except Exception as e:
        out["beefy_parse_error"] = repr(e)
out["beefy_base_count"] = len(beefy)
out["beefy_base_sample"] = beefy[:10]
time.sleep(0.4)
r = get("https://api.beefy.finance/tvl", "beefy_tvl")
tvl = {}
if r is not None and r.status_code == 200:
    try:
        j = r.json()
        base_tvl = j.get("base") or {}
        if isinstance(base_tvl, dict): tvl = base_tvl
        elif isinstance(base_tvl, list): tvl = {str(i): v for i, v in enumerate(base_tvl)}
    except Exception as e:
        out["tvl_parse_error"] = repr(e)
scored = []
for v in beefy:
    key = v["id"] if v["id"] in tvl else None
    if key is None:
        # tvl keys may be like "base-id"
        for k in tvl:
            if k.endswith(v["id"]): key = k; break
    if key: v = dict(v); v["tvl_usd"] = tvl[key]; scored.append(v)
scored.sort(key=lambda x: -(x.get("tvl_usd") or 0))
out["beefy_base_top_tvl"] = scored[:8]
out["finished_at_utc"] = now()
out["requests"] = reqs
out["request_count"] = len(reqs)
save("discover.json", out)
print(json.dumps(out, ensure_ascii=False, indent=1)[:9000])
