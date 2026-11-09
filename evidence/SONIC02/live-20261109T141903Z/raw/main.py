import json, time, hashlib, datetime
import requests
from Crypto.Hash import keccak
BASE = r"D:\ds-arb-test\watch_market\evidence\SONIC02\live-20261109T141903Z\raw"
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
STS = "0xE5DA20F15420aD15DE0fa650600aFc998bbE3955"
WS = "0x039e2fB66102314Ce7b64Ce5Ce3E5183bc94aD38"
IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
# 1) chain + stS/wS identity + rate + exit params
calls = [("eth_chainId", []), ("eth_blockNumber", []), ("eth_getBlockByNumber", ["latest", False]),
         ("eth_getCode", [STS, "latest"]), ("eth_getStorageAt", [STS, IMPL_SLOT, "latest"]),
         ("eth_getCode", [WS, "latest"])]
labels = ["symbol()", "decimals()", "getRate()", "convertToAssets(uint256)", "previewRedeem(uint256)",
          "totalAssets()", "totalSupply()", "withdrawalDelay()", "paused()", "underlying()", "asset()"]
args = {"convertToAssets(uint256)": [10**18], "previewRedeem(uint256)": [10**18]}
for lab in labels:
    data = sel(lab) + "".join(hex(x)[2:].rjust(64, "0") for x in args.get(lab, []))
    calls.append(("eth_call", [{"to": STS, "data": data}, "latest"]))
calls += [("eth_call", [{"to": WS, "data": sel("symbol()")}, "latest"]),
          ("eth_call", [{"to": WS, "data": sel("decimals()")}, "latest"]),
          ("eth_call", [{"to": WS, "data": sel("totalSupply()")}, "latest"])]
res = batch(calls, "sonic_identity")
out["chain_id"] = int(res[0]["result"], 16)
out["latest_block"] = int(res[1]["result"], 16)
blk = res[2]["result"]
out["latest_block_time_utc"] = datetime.datetime.fromtimestamp(int(blk["timestamp"], 16), datetime.timezone.utc).isoformat()
out["pinned_block"] = out["latest_block"] - 5
def code_bytes(r): return (len(r.get("result") or "0x")-2)//2
def num(v): return int(v, 16) if v and v != "0x" else None
def dec_str(v):
    if not v or len(v) < 130: return None
    try:
        h = v[2:]; ln = int(h[64:128], 16)
        if ln > 100: return None
        return bytes.fromhex(h[128:128+ln*2]).decode("utf-8", "replace")
    except Exception: return None
def addr(v): return ("0x" + v[-40:]) if v and len(v) >= 66 else None
out["sts"] = {"address": STS, "code_bytes": code_bytes(res[3]), "impl_slot": res[4].get("result")}
out["wS"] = {"address": WS, "code_bytes": code_bytes(res[5])}
for i, lab in enumerate(labels):
    rr = res[6+i]
    v = rr.get("result")
    val = None
    if v and v != "0x":
        if lab in ("symbol()",): val = dec_str(v)
        elif lab in ("underlying()", "asset()"): val = addr(v)
        else: val = str(num(v))
    out["sts"][lab] = val if val is not None else {"error": rr.get("error")}
k = 6 + len(labels)
out["wS"]["symbol"] = dec_str(res[k].get("result"))
out["wS"]["decimals"] = num(res[k+1].get("result"))
out["wS"]["totalSupply"] = str(num(res[k+2].get("result")))
save("identity.json", out)
time.sleep(0.3)
# 2) DEX discovery for stS on Sonic
t0 = time.time()
r = s.get(f"https://api.dexscreener.com/latest/dex/tokens/{STS}", timeout=40)
reqs.append({"name": "dexscreener_sts", "url": r.url, "http_status": r.status_code, "at": now(),
             "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(),
             "elapsed_s": round(time.time()-t0, 3)})
pairs = []
if r.status_code == 200:
    for p in (r.json().get("pairs") or []):
        if p.get("chainId") != "sonic": continue
        pairs.append({"pair": p.get("pairAddress"), "dexId": p.get("dexId"),
                      "baseSymbol": (p.get("baseToken") or {}).get("symbol"), "quoteSymbol": (p.get("quoteToken") or {}).get("symbol"),
                      "base": (p.get("baseToken") or {}).get("address"), "quote": (p.get("quoteToken") or {}).get("address"),
                      "priceNative": p.get("priceNative"), "priceUsd": p.get("priceUsd"),
                      "liquidityUsd": (p.get("liquidity") or {}).get("usd")})
pairs.sort(key=lambda x: -(x.get("liquidityUsd") or 0))
out["dexscreener_pairs"] = pairs[:6]
save("dexscreener.json", out)
time.sleep(0.3)
# 3) on-chain verify top pair + read state (try V2 getReserves and V3 slot0/fee)
if pairs:
    P = pairs[0]["pair"]
    pinned = hex(out["pinned_block"])
    calls2 = [("eth_getCode", [P, pinned]),
              ("eth_call", [{"to": P, "data": sel("token0()")}, pinned]),
              ("eth_call", [{"to": P, "data": sel("token1()")}, pinned]),
              ("eth_call", [{"to": P, "data": sel("getReserves()")}, pinned]),
              ("eth_call", [{"to": P, "data": sel("slot0()")}, pinned]),
              ("eth_call", [{"to": P, "data": sel("fee()")}, pinned]),
              ("eth_call", [{"to": P, "data": sel("factory()")}, pinned])]
    res2 = batch(calls2, "pair_state")
    st = {"pair": P, "code_bytes": code_bytes(res2[0])}
    st["token0"] = addr(res2[1].get("result")); st["token1"] = addr(res2[2].get("result"))
    v = res2[3].get("result")
    if v and v != "0x" and len(v) >= 130:
        st["reserve0"] = str(int(v[2:66], 16)); st["reserve1"] = str(int(v[66:130], 16))
    else:
        st["getReserves_error"] = res2[3].get("error")
    v = res2[4].get("result")
    if v and v != "0x" and len(v) >= 66:
        st["slot0_sqrtPriceX96"] = str(int(v[2:66], 16)); st["slot0_tick"] = int(v[66:130], 16) if len(v) >= 130 else None
    else:
        st["slot0_error"] = res2[4].get("error")
    st["fee"] = num(res2[5].get("result"))
    st["factory"] = addr(res2[6].get("result"))
    out["top_pair_state"] = st
out["finished_at_utc"] = now()
out["requests"] = reqs
out["request_count"] = len(reqs)
save("sonic_summary.json", out)
print(json.dumps(out, ensure_ascii=False, indent=1)[:10000])
