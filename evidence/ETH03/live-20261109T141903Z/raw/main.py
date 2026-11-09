import json, time, hashlib, datetime
import requests
from Crypto.Hash import keccak
BASE = r"D:\ds-arb-test\watch_market\evidence\ETH03\live-20261109T141903Z\raw"
PROXY = "http://127.0.0.1:7897"
RPC = "https://ethereum-rpc.publicnode.com"
s = requests.Session(); s.trust_env = False
s.proxies = {"http": PROXY, "https": PROXY}
s.headers.update({"User-Agent": "watch_market-readonly-research/1.0", "Content-Type": "application/json"})
now = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
reqs = []
def sel(sig):
    h = keccak.new(digest_bits=256); h.update(sig.encode()); return "0x" + h.hexdigest()[:8]
def encode(a): return a[2:].rjust(64, "0")
def save(n, o):
    json.dump(o, open(BASE + "\\" + n, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
def rpcbatch(calls, name, pinned="latest"):
    t0 = time.time()
    payload = [{"jsonrpc": "2.0", "id": k, "method": m, "params": p} for k, (m, p) in enumerate(calls)]
    r = s.post(RPC, json=payload, timeout=60)
    reqs.append({"name": name, "http_status": r.status_code, "at": now(), "n_calls": len(calls),
                 "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(),
                 "elapsed_s": round(time.time()-t0, 3)})
    d = r.json()
    if isinstance(d, dict): d = [d]
    return d
def get(url, name):
    t0 = time.time()
    r = s.get(url, timeout=40)
    reqs.append({"name": name, "url": url, "http_status": r.status_code, "at": now(), "bytes": len(r.content),
                 "sha256": hashlib.sha256(r.content).hexdigest(), "elapsed_s": round(time.time()-t0, 3)})
    return r
out = {"started_at_utc": now()}
# 1) chain identity
res = rpcbatch([("eth_chainId", []), ("eth_blockNumber", []), ("eth_getBlockByNumber", ["latest", False])], "chain_identity")
out["chain_id"] = int(res[0]["result"], 16)
out["latest_block"] = int(res[1]["result"], 16)
blk = res[2]["result"]
out["latest_block_time_utc"] = datetime.datetime.fromtimestamp(int(blk["timestamp"], 16), datetime.timezone.utc).isoformat()
out["pinned_block"] = out["latest_block"] - 5
pinned = hex(out["pinned_block"])
time.sleep(0.3)
# 2) Morpho API top Ethereum vaults
t0 = time.time()
q = {"query": "{ vaults(first: 5, orderBy: TotalAssetsUsd, orderDirection: Desc, where: {chainId_in: [1]}) { items { address name asset { address symbol } state { totalAssetsUsd } } } }"}
r = s.post("https://api.morpho.org/graphql", json=q, timeout=40)
reqs.append({"name": "morpho_vaults", "http_status": r.status_code, "at": now(), "bytes": len(r.content),
             "sha256": hashlib.sha256(r.content).hexdigest(), "elapsed_s": round(time.time()-t0, 3)})
morpho = []
if r.status_code == 200:
    try:
        items = (((r.json().get("data") or {}).get("vaults") or {}).get("items")) or []
        for it in items:
            morpho.append({"address": it.get("address"), "name": it.get("name"),
                           "asset": (it.get("asset") or {}).get("address"),
                           "totalAssetsUsd": (it.get("state") or {}).get("totalAssetsUsd")})
    except Exception as e:
        out["morpho_parse_error"] = repr(e)
out["morpho_top"] = morpho
time.sleep(0.3)
# 3) sDAI + Morpho vault on-chain reads
SDAI = "0x83F20F44975D03b1b09e64809B757c47f942BEeA"
POT = "0x197E90f9FAD81970bA7976f33CbD77088E5D7cf7"
DAI = "0x6B175474E89094C44Da98b954EedeAC495271d0F"
DEAD = "0x000000000000000000000000000000000000dEaD"
def vault_calls(vault):
    c = [("eth_getCode", [vault, pinned])]
    for f, args in [("asset()", []), ("totalAssets()", []), ("totalSupply()", []),
                    ("convertToAssets(uint256)", [10**18]), ("previewRedeem(uint256)", [10**18]),
                    ("maxRedeem(address)", [int(DEAD, 16)]), ("maxWithdraw(address)", [int(DEAD, 16)]),
                    ("symbol()", []), ("decimals()", [])]:
        c.append(("eth_call", [{"to": vault, "data": sel(f) + "".join(hex(x)[2:].rjust(64, "0") for x in args)}, pinned]))
    return c
idx = {}
calls = vault_calls(SDAI); idx["sdai"] = (0, len(calls))
calls += [("eth_call", [{"to": SDAI, "data": sel("pot()")}, pinned]),
          ("eth_call", [{"to": SDAI, "data": sel("asset()")}, pinned])]
calls += [("eth_call", [{"to": DAI, "data": sel("balanceOf(address)") + encode(POT)}, pinned])]
if morpho:
    mv = morpho[0]["address"]
    calls += vault_calls(mv); idx["morpho"] = (len(calls)-10, 10)
    calls += [("eth_call", [{"to": mv, "data": sel("withdrawQueueLength()")}, pinned])]
res = rpcbatch(calls, "vault_reads", pinned)
def dec_str(v):
    if not v or len(v) < 130: return None
    try:
        h = v[2:]; ln = int(h[64:128], 16)
        if ln > 100: return None
        return bytes.fromhex(h[128:128+ln*2]).decode("utf-8", "replace")
    except Exception: return None
def addr(v): return ("0x" + v[-40:]) if v and len(v) >= 66 else None
def num(v): return int(v, 16) if v and v != "0x" else None
def parse_vault(start, length):
    d = {}
    d["code_bytes"] = (len(res[start].get("result") or "0x")-2)//2
    labels = ["asset()", "totalAssets()", "totalSupply()", "convertToAssets(1e18)", "previewRedeem(1e18)",
              "maxRedeem(dead)", "maxWithdraw(dead)", "symbol", "decimals"]
    for i, lab in enumerate(labels, start=1):
        v = res[start+i].get("result")
        if lab in ("asset()",): d[lab] = addr(v)
        elif lab in ("symbol",): d[lab] = dec_str(v)
        elif lab == "decimals": d[lab] = num(v)
        else: d[lab] = num(v)
    return d
out["sdai"] = parse_vault(idx["sdai"][0], idx["sdai"][1])
# pot/DAI balance positions: after sdai vault calls (9 calls) come pot(), asset() dup, DAI.balanceOf(pot)
base = idx["sdai"][0] + idx["sdai"][1]
out["sdai"]["pot"] = addr(res[base].get("result"))
out["pot_DAI_balance"] = num(res[base+2].get("result"))
if morpho:
    out["morpho_vault"] = parse_vault(idx["morpho"][0], idx["morpho"][1])
    out["morpho_vault"]["name"] = morpho[0]["name"]
    out["morpho_vault"]["withdrawQueueLength"] = num(res[idx["morpho"][0]+idx["morpho"][1]].get("result"))
    out["morpho_vault_idle_asset"] = {"asset": out["morpho_vault"]["asset()"],
                                      "vault_asset_balance": out["morpho_vault"]["totalAssets()"]}
save("vaults.json", out)
time.sleep(0.3)
# 4) DexScreener discovery for secondary markets
sec = {}
for label, token in [("sdai", SDAI), ("morpho", morpho[0]["address"] if morpho else None)]:
    if not token: continue
    t0 = time.time()
    r = s.get(f"https://api.dexscreener.com/latest/dex/tokens/{token}", timeout=40)
    reqs.append({"name": f"dexscreener_{label}", "url": r.url, "http_status": r.status_code, "at": now(),
                 "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(),
                 "elapsed_s": round(time.time()-t0, 3)})
    pairs = []
    if r.status_code == 200:
        for p in (r.json().get("pairs") or []):
            if p.get("chainId") != "ethereum": continue
            pairs.append({"dexId": p.get("dexId"), "pair": p.get("pairAddress"),
                          "base": (p.get("baseToken") or {}).get("address"), "baseSymbol": (p.get("baseToken") or {}).get("symbol"),
                          "quote": (p.get("quoteToken") or {}).get("address"), "quoteSymbol": (p.get("quoteToken") or {}).get("symbol"),
                          "priceNative": p.get("priceNative"), "priceUsd": p.get("priceUsd"),
                          "liquidityUsd": (p.get("liquidity") or {}).get("usd")})
    pairs.sort(key=lambda x: -(x.get("liquidityUsd") or 0))
    sec[label] = pairs[:6]
    time.sleep(0.3)
out["secondary_pairs"] = sec
out["finished_at_utc"] = now()
out["requests"] = reqs
out["request_count"] = len(reqs)
save("eth03_summary.json", out)
print(json.dumps(out, ensure_ascii=False, indent=1)[:9000])
