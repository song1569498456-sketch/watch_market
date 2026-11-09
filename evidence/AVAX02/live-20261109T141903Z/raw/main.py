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
def decode_str(v):
    if not v or len(v) < 130: return None
    try:
        h = v[2:]; ln = int(h[64:128], 16)
        if ln > 100: return None
        return bytes.fromhex(h[128:128+ln*2]).decode("utf-8", "replace")
    except Exception:
        return None

SAVAX = "0x2b2C81e08f1Af8835a78Bb2A90AE924ACE0eA4bE"
GGAX = "0xA25EaF2906FA1a3a13EdAc9B9657108Af7B703e3"
WAVAX = "0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7"
LFJ_V21_FACTORY = "0x8e42f2F4101563bF679975178e880FD87d3eFd4e"
out = {"started_at_utc": now()}
# 0) discovery: DexScreener sAVAX pairs
r = get("https://api.dexscreener.com/latest/dex/search?q=sAVAX", "dexscreener_savax")
ds_pairs = []
if r is not None and r.status_code == 200:
    try:
        for p in (r.json().get("pairs") or []):
            if p.get("chainId") != "avalanche":
                continue
            ds_pairs.append({"dexId": p.get("dexId"), "pairAddress": p.get("pairAddress"),
                             "base": (p.get("baseToken") or {}).get("address"),
                             "baseSymbol": (p.get("baseToken") or {}).get("symbol"),
                             "quote": (p.get("quoteToken") or {}).get("address"),
                             "quoteSymbol": (p.get("quoteToken") or {}).get("symbol"),
                             "priceNative": p.get("priceNative"), "priceUsd": p.get("priceUsd"),
                             "liquidityUsd": (p.get("liquidity") or {}).get("usd"),
                             "pairCreatedAt": p.get("pairCreatedAt")})
    except Exception as e:
        out["ds_parse_error"] = repr(e)
out["dexscreener_savax_pairs"] = ds_pairs[:10]
save("discovery.json", out)
time.sleep(0.4)
# 1) chain identity
res = batch([("eth_chainId", []), ("eth_blockNumber", []), ("eth_getBlockByNumber", ["latest", False])], "chain_identity")
m = {x.get("id"): x for x in res}
out["chain_id"] = int(m[0]["result"], 16) if m.get(0, {}).get("result") else None
block = int(m[1]["result"], 16) if m.get(1, {}).get("result") else None
blk = m[2].get("result") or {}
out["latest_block"] = block
out["latest_block_time_utc"] = datetime.datetime.fromtimestamp(int(blk["timestamp"], 16), datetime.timezone.utc).isoformat() if blk.get("timestamp") else None
out["base_fee_wei"] = blk.get("baseFeePerGas")
pinned = hex(block - 5) if block else "latest"
out["pinned_block"] = block - 5 if block else None
time.sleep(0.4)
# 2) code + symbol/decimals for sAVAX, ggAVAX, WAVAX
tokens = {"sAVAX": SAVAX, "ggAVAX": GGAX, "WAVAX": WAVAX}
calls = []; tags = []
for name, t in tokens.items():
    calls.append(("eth_getCode", [t, pinned])); tags.append((name, "code"))
    calls.append(("eth_call", [{"to": t, "data": sel("symbol()")}, pinned])); tags.append((name, "symbol"))
    calls.append(("eth_call", [{"to": t, "data": sel("decimals()")}, pinned])); tags.append((name, "decimals"))
res = batch(calls, "token_codes")
tinfo = {}
for (name, kind), rr in zip(tags, res):
    v = rr.get("result")
    tinfo.setdefault(name, {})
    if kind == "code": tinfo[name]["code_bytes"] = (len(v or "0x")-2)//2
    elif kind == "symbol": tinfo[name]["symbol"] = decode_str(v)
    else: tinfo[name]["decimals"] = int(v, 16) if v and v != "0x" else None
out["tokens"] = tinfo
# 3) sAVAX conversion + totals + exit-function probes
entry = {"sAVAX_balance": None}
calls = []
for f, args in [("totalSupply()", []), ("totalPooledAvax()", []), ("getPooledAvaxByShares(uint256)", [10**18]),
                ("getSharesByPooledAvax(uint256)", [10**18]), ("exchangeRate()", []),
                ("withdraw(uint256)", [10**18]), ("redeem(uint256)", [10**18])]:
    data = sel(f) + "".join(hex(a)[2:].rjust(64, "0") for a in args)
    calls.append(("eth_call", [{"to": SAVAX, "data": data}, pinned]))
res = batch(calls, "savax_state")
def num(rr):
    v = rr.get("result")
    return int(v, 16) if v and v != "0x" else None
out["savax_state"] = {"totalSupply": num(res[0]), "totalPooledAvax": num(res[1]),
                      "avax_per_1_savax_raw": num(res[2]), "shares_per_1_avax_raw": num(res[3]),
                      "exchangeRate_result": num(res[4]),
                      "withdraw_probe": (res[5].get("result") if res[5].get("result") else res[5].get("error")),
                      "redeem_probe": (res[6].get("result") if res[6].get("result") else res[6].get("error"))}
if out["savax_state"]["totalSupply"] and out["savax_state"]["totalPooledAvax"]:
    out["savax_state"]["avax_per_share_ratio"] = out["savax_state"]["totalPooledAvax"] / out["savax_state"]["totalSupply"]
save("savax.json", out)
time.sleep(0.4)
# 4) ggAVAX ERC4626 conversion + restricted exit probes
calls = []
for f, args in [("totalAssets()", []), ("totalSupply()", []), ("convertToAssets(uint256)", [10**18]),
                ("previewRedeem(uint256)", [10**18]), ("withdrawAVAX(uint256)", [10**18]),
                ("redeemAVAX(uint256)", [10**18])]:
    data = sel(f) + "".join(hex(a)[2:].rjust(64, "0") for a in args)
    calls.append(("eth_call", [{"to": GGAX, "from": "0x0000000000000000000000000000000000000001", "data": data}, pinned]))
res = batch(calls, "ggavax_state")
out["ggavax_state"] = {"totalAssets": num(res[0]), "totalSupply": num(res[1]),
                       "assets_per_1_ggavax_raw": num(res[2]), "previewRedeem_raw": num(res[3]),
                       "withdrawAVAX_probe": (res[4].get("result") if res[4].get("result") else res[4].get("error")),
                       "redeemAVAX_probe": (res[5].get("result") if res[5].get("result") else res[5].get("error"))}
if out["ggavax_state"]["totalAssets"] and out["ggavax_state"]["totalSupply"]:
    out["ggavax_state"]["avax_per_share_ratio"] = out["ggavax_state"]["totalAssets"] / out["ggavax_state"]["totalSupply"]
save("ggavax.json", out)
time.sleep(0.4)
# 5) LFJ V2.1 pairs for sAVAX/WAVAX and ggAVAX/WAVAX across common binSteps (factory getLBPairInformation)
def enc_addr(a): return a[2:].rjust(64, "0")
def enc_uint(n): return hex(n)[2:].rjust(64, "0")
calls = []; tags = []
for tok, name in [(SAVAX, "sAVAX"), (GGAX, "ggAVAX")]:
    for bs in [1, 5, 10, 20, 25, 50, 100]:
        data = sel("getLBPairInformation(address,address,uint256)") + enc_addr(tok) + enc_addr(WAVAX) + enc_uint(bs)
        calls.append(("eth_call", [{"to": LFJ_V21_FACTORY, "data": data}, pinned])); tags.append((name, bs))
res = batch(calls, "lfj_pair_info")
lfj = {}
for (name, bs), rr in zip(tags, res):
    v = rr.get("result")
    if v and len(v) >= 66:
        words = [v[2+i*64:2+(i+1)*64] for i in range(len(v)//64)]
        pair = "0x" + words[0][-40:]
        if int(words[0], 16) != 0:
            lfj.setdefault(name, []).append({"binStep": bs, "pair": pair,
                                             "createdByOwner": int(words[1], 16) if len(words) > 1 else None,
                                             "ignoredForRouting": int(words[2], 16) if len(words) > 2 else None})
out["lfj_pairs"] = lfj
save("lfj_pairs.json", out)
time.sleep(0.4)
# 6) LB pair state for found sAVAX pair (activeId/binStep/reserves)
pair = (lfj.get("sAVAX") or [{}])[0].get("pair") if lfj.get("sAVAX") else None
out["lb_pair"] = pair
if pair:
    calls = [("eth_call", [{"to": pair, "data": sel("getTokenX()")}, pinned]),
             ("eth_call", [{"to": pair, "data": sel("getTokenY()")}, pinned]),
             ("eth_call", [{"to": pair, "data": sel("getBinStep()")}, pinned]),
             ("eth_call", [{"to": pair, "data": sel("getActiveId()")}, pinned]),
             ("eth_call", [{"to": pair, "data": sel("getReserves()")}, pinned])]
    res = batch(calls, "lb_pair_state")
    def word(i, off=2): return res[i].get("result", "0x")[off:off+64]
    st = {"tokenX": "0x" + word(0)[-40:], "tokenY": "0x" + word(1)[-40:],
          "binStep": int(word(2), 16) if res[2].get("result") not in (None, "0x") else None,
          "activeId": int(word(3), 16) if res[3].get("result") not in (None, "0x") else None,
          "reserves_raw": res[4].get("result")}
    # LB price formula: price(tokenX in tokenY) = (1 + binStep/1e4)^(activeId - 2^23) * 10^(decX-decY)
    if st["binStep"] and st["activeId"] is not None:
        ratio = (1 + st["binStep"]/1e4) ** (st["activeId"] - 2**23)
        decX = tinfo["sAVAX"]["decimals"] or 18
        decY = 18
        st["price_savax_in_avax_spot"] = ratio * (10 ** (decX - decY))
    out["lb_pair_state"] = st
save("lb_pair_state.json", out)
out["finished_at_utc"] = now()
out["requests"] = reqs
out["request_count"] = len(reqs)
save("avax02_summary.json", out)
print(json.dumps(out, ensure_ascii=False, indent=1)[:12000])
