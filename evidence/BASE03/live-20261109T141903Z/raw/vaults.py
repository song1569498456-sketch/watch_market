import json, time, hashlib, datetime
import requests
from Crypto.Hash import keccak
BASE = r"D:\ds-arb-test\watch_market\evidence\BASE03\live-20261109T141903Z\raw"
PROXY = "http://127.0.0.1:7897"
RPC = "https://mainnet.base.org"
s = requests.Session(); s.trust_env = False
s.proxies = {"http": PROXY, "https": PROXY}
s.headers.update({"User-Agent": "watch_market-readonly-research/1.0", "Content-Type": "application/json"})
now = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
reqs = []
def sel(sig):
    h = keccak.new(digest_bits=256); h.update(sig.encode()); return "0x" + h.hexdigest()[:8]
def save(n, o):
    json.dump(o, open(BASE + "\\" + n, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
prev = json.load(open(BASE + r"\discover.json", encoding="utf-8"))
out = {"started_at_utc": now(), "chain_id": prev.get("chain_id"), "latest_block": prev.get("latest_block"),
       "latest_block_time_utc": prev.get("latest_block_time_utc"), "pinned_block": prev.get("pinned_block")}
pinned = hex(out["pinned_block"])
# 1) Morpho API: top Base vaults by totalAssetsUsd (try orderBy)
q = {"query": "{ vaults(first: 8, orderBy: TotalAssetsUsd, orderDirection: Desc, where: {chainId_in: [8453]}) { items { address name asset { address symbol } state { totalAssetsUsd } } } }"}
t0 = time.time()
r = s.post("https://api.morpho.org/graphql", json=q, timeout=40)
reqs.append({"name": "morpho_top", "http_status": r.status_code, "at": now(), "bytes": len(r.content),
             "sha256": hashlib.sha256(r.content).hexdigest(), "elapsed_s": round(time.time()-t0, 3)})
top = []
if r.status_code == 200:
    try:
        j = r.json()
        items = (((j.get("data") or {}).get("vaults") or {}).get("items")) or []
        for it in items:
            top.append({"address": it.get("address"), "name": it.get("name"),
                        "asset": (it.get("asset") or {}).get("address"),
                        "assetSymbol": (it.get("asset") or {}).get("symbol"),
                        "totalAssetsUsd": ((it.get("state") or {}).get("totalAssetsUsd"))})
    except Exception as e:
        out["parse_error"] = repr(e)
if not top:
    out["morpho_error_head"] = r.text[:400]
    # fallback: previous unordered list filtered to plausible MetaMorpho names
    for v in prev.get("morpho_vaults", []):
        if v.get("name") in ("Allez USDC", "morpho MetaMorpho", "dForce USDC"):
            top.append(v)
out["morpho_top"] = top
time.sleep(0.4)
# 2) on-chain vault state for top 2 (or selected)
vaults = top[:2]
calls = []; tags = []
HOLDER = "0x000000000000000000000000000000000000dEaD"
for i, v in enumerate(vaults):
    a = v["address"]
    calls.append(("eth_getCode", [a, pinned])); tags.append((i, "code"))
    for f, args in [("asset()", []), ("totalAssets()", []), ("totalSupply()", []),
                    ("convertToAssets(uint256)", [10**18]), ("previewRedeem(uint256)", [10**18]),
                    ("maxRedeem(address)", [int(HOLDER, 16)]), ("maxWithdraw(address)", [int(HOLDER, 16)]),
                    ("symbol()", []), ("decimals()", []), ("owner()", [])]:
        data = sel(f) + "".join(hex(x)[2:].rjust(64, "0") for x in args)
        calls.append(("eth_call", [{"to": a, "data": data}, pinned])); tags.append((i, f))
res = []
t0 = time.time()
r = s.post(RPC, json=[{"jsonrpc": "2.0", "id": k, "method": m, "params": p} for k, (m, p) in enumerate(calls)], timeout=60)
reqs.append({"name": "vault_state", "http_status": r.status_code, "at": now(), "n_calls": len(calls),
             "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(), "elapsed_s": round(time.time()-t0, 3)})
res = r.json()
def dec_str(v):
    if not v or len(v) < 130: return None
    try:
        h = v[2:]; ln = int(h[64:128], 16)
        if ln > 100: return None
        return bytes.fromhex(h[128:128+ln*2]).decode("utf-8", "replace")
    except Exception: return None
state = [dict(v) for v in vaults]
for (i, f), rr in zip(tags, res):
    v = rr.get("result")
    if f == "code": state[i]["code_bytes"] = (len(v or "0x")-2)//2
    elif f in ("asset()", "owner()"): state[i][f] = ("0x" + v[-40:]) if v and len(v) >= 66 else None
    elif f in ("symbol()",): state[i]["symbol"] = dec_str(v)
    elif f == "decimals()": state[i]["decimals"] = int(v, 16) if v and v != "0x" else None
    elif v and v != "0x": state[i][f] = int(v, 16)
out["vaults"] = state
for st in state:
    if st.get("totalAssets()") and st.get("totalSupply()"):
        st["assets_per_share"] = st["totalAssets()"] / st["totalSupply()"] if st["totalSupply()"] else None
save("vault_state.json", out)
time.sleep(0.4)
# 3) secondary market existence: DexScreener token search for each vault share
sec = {}
for st in state:
    a = st.get("address")
    t0 = time.time()
    try:
        rr = s.get(f"https://api.dexscreener.com/latest/dex/tokens/{a}", timeout=40)
        reqs.append({"name": f"dexscreener_token_{a}", "url": rr.url, "http_status": rr.status_code, "at": now(),
                     "bytes": len(rr.content), "sha256": hashlib.sha256(rr.content).hexdigest(),
                     "elapsed_s": round(time.time()-t0, 3)})
        pairs = []
        if rr.status_code == 200:
            j = rr.json()
            for p in (j.get("pairs") or []):
                if p.get("chainId") == "base":
                    pairs.append({"dexId": p.get("dexId"), "pairAddress": p.get("pairAddress"),
                                  "priceNative": p.get("priceNative"), "priceUsd": p.get("priceUsd"),
                                  "liquidityUsd": (p.get("liquidity") or {}).get("usd"),
                                  "base": (p.get("baseToken") or {}).get("address"),
                                  "quote": (p.get("quoteToken") or {}).get("address")})
        sec[a] = pairs
    except Exception as e:
        sec[a] = {"error": repr(e)}
    time.sleep(0.4)
out["secondary_pairs"] = sec
out["finished_at_utc"] = now()
out["requests"] = prev.get("requests", []) + reqs
out["request_count"] = len(out["requests"])
save("summary.json", out)
print(json.dumps({k: out.get(k) for k in ["chain_id", "latest_block", "pinned_block", "morpho_top", "vaults", "secondary_pairs", "request_count"]}, ensure_ascii=False, indent=1)[:9000])
