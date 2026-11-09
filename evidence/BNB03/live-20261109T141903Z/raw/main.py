import json, time, hashlib, datetime
import requests
from Crypto.Hash import keccak
BASE = r"D:\ds-arb-test\watch_market\evidence\BNB03\live-20261109T141903Z\raw"
PROXY = "http://127.0.0.1:7897"
RPC = "https://bsc-dataseed.bnbchain.org"
s = requests.Session(); s.trust_env = False
s.proxies = {"http": PROXY, "https": PROXY}
s.headers.update({"User-Agent": "watch_market-readonly-research/1.0", "Content-Type": "application/json"})
now = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
reqs = []
def sel(sig):
    h = keccak.new(digest_bits=256); h.update(sig.encode()); return "0x" + h.hexdigest()[:8]
def save(n, o):
    json.dump(o, open(BASE + "\\" + n, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
out = {"started_at_utc": now()}
# 1) discovery via DexScreener (BSC stable pairs)
t0 = time.time()
r = s.get("https://api.dexscreener.com/latest/dex/search?q=USDC%20USDT", timeout=40)
reqs.append({"name": "dexscreener_usdc_usdt", "url": r.url, "http_status": r.status_code, "at": now(),
             "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(),
             "elapsed_s": round(time.time()-t0, 3)})
ds = []
if r.status_code == 200:
    for p in (r.json().get("pairs") or []):
        if p.get("chainId") != "bsc":
            continue
        ds.append({"pair": p.get("pairAddress"), "dexId": p.get("dexId"),
                   "base": (p.get("baseToken") or {}).get("address"), "baseSymbol": (p.get("baseToken") or {}).get("symbol"),
                   "quote": (p.get("quoteToken") or {}).get("address"), "quoteSymbol": (p.get("quoteToken") or {}).get("symbol"),
                   "priceUsd": p.get("priceUsd"), "priceNative": p.get("priceNative"),
                   "liquidityUsd": (p.get("liquidity") or {}).get("usd")})
ds.sort(key=lambda x: -(x.get("liquidityUsd") or 0))
out["dexscreener_bsc_stable_pairs"] = ds[:10]
time.sleep(0.4)
# 2) chain identity + token identity + V2 factory pair discovery (one batch)
USDC = "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d"
USDT = "0x55d398326f99059fF775485246999027B3197955"
DAI = "0x1AF3F329e8BE154074D8769D1FFa4eE058B1DBc3"
BUSD = "0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56"
V2F = "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"
def enc_addr(a): return a[2:].rjust(64, "0")
calls = [("eth_chainId", []), ("eth_blockNumber", []), ("eth_getBlockByNumber", ["latest", False]),
         ("eth_getCode", [V2F, "latest"])]
tokens = {"USDC": USDC, "USDT": USDT, "DAI": DAI, "BUSD": BUSD}
for n, a in tokens.items():
    calls.append(("eth_call", [{"to": a, "data": sel("symbol()")}, "latest"]))
    calls.append(("eth_call", [{"to": a, "data": sel("decimals()")}, "latest"]))
for a, b in [(USDC, USDT), (USDT, DAI), (DAI, USDC), (USDC, BUSD), (USDT, BUSD), (USDT, USDC), (DAI, USDT)]:
    calls.append(("eth_call", [{"to": V2F, "data": sel("getPair(address,address)") + enc_addr(a) + enc_addr(b)}, "latest"]))
t0 = time.time()
r = s.post(RPC, json=[{"jsonrpc": "2.0", "id": k, "method": m, "params": p} for k, (m, p) in enumerate(calls)], timeout=60)
reqs.append({"name": "identity_pairs", "http_status": r.status_code, "at": now(), "n_calls": len(calls),
             "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(),
             "elapsed_s": round(time.time()-t0, 3)})
res = r.json()
out["chain_id"] = int(res[0]["result"], 16)
out["latest_block"] = int(res[1]["result"], 16)
blk = res[2]["result"]
out["latest_block_time_utc"] = datetime.datetime.fromtimestamp(int(blk["timestamp"], 16), datetime.timezone.utc).isoformat()
out["pinned_block"] = out["latest_block"] - 5
out["pancake_v2_factory_code_bytes"] = (len(res[3].get("result") or "0x")-2)//2
def dec_str(v):
    if not v or len(v) < 130: return None
    try:
        h = v[2:]; ln = int(h[64:128], 16)
        if ln > 100: return None
        return bytes.fromhex(h[128:128+ln*2]).decode("utf-8", "replace")
    except Exception: return None
tmeta = {}; k = 4
for n, a in tokens.items():
    sv = res[k].get("result"); dv = res[k+1].get("result")
    tmeta[n] = {"address": a, "symbol": dec_str(sv), "decimals": int(dv, 16) if dv and dv != "0x" else None}
    k += 2
out["token_identity"] = tmeta
pair_keys = ["USDC/USDT", "USDT/DAI", "DAI/USDC", "USDC/BUSD", "USDT/BUSD", "USDT/USDC2", "DAI/USDT2"]
pairs = {}
for name, rr in zip(pair_keys, res[k:k+len(pair_keys)]):
    v = rr.get("result")
    pairs[name] = ("0x" + v[-40:]) if v and len(v) >= 66 and int(v, 16) != 0 else None
out["v2_pairs"] = pairs
save("discovery.json", out)
time.sleep(0.4)
# 3) read pair states for existing pairs (pinned block)
pinned = hex(out["pinned_block"])
exist = {n: a for n, a in pairs.items() if a}
calls = []; tags = []
for n, a in exist.items():
    calls.append(("eth_getCode", [a, pinned])); tags.append((n, "code"))
    for f in ["token0()", "token1()", "getReserves()", "factory()", "totalSupply()"]:
        calls.append(("eth_call", [{"to": a, "data": sel(f)}, pinned])); tags.append((n, f))
t0 = time.time()
r = s.post(RPC, json=[{"jsonrpc": "2.0", "id": k, "method": m, "params": p} for k, (m, p) in enumerate(calls)], timeout=60)
reqs.append({"name": "pair_states", "http_status": r.status_code, "at": now(), "n_calls": len(calls),
             "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(),
             "elapsed_s": round(time.time()-t0, 3)})
res = r.json()
states = {}
for (n, f), rr in zip(tags, res):
    v = rr.get("result")
    states.setdefault(n, {})
    if f == "code": states[n]["code_bytes"] = (len(v or "0x")-2)//2
    elif f in ("token0()", "token1()", "factory()"): states[n][f] = ("0x" + v[-40:]) if v and len(v) >= 66 else None
    elif f == "getReserves()":
        states[n]["reserves_raw"] = v
        if v and len(v) >= 130:
            states[n]["reserve0"] = int(v[2:66], 16); states[n]["reserve1"] = int(v[66:130], 16)
    elif f == "totalSupply()": states[n]["lp_total_supply"] = int(v, 16) if v and v != "0x" else None
out["pair_states"] = states
save("pair_states.json", out)
time.sleep(0.4)
# 4) compute closed loops from same pinned block reserves (Pancake V2 fee 0.25%: 9975/10000)
def q_v2(amount_in, r_in, r_out):
    if not amount_in or not r_in or not r_out: return 0
    ain = amount_in * 9975
    return (ain * r_out) // (r_in * 10000 + ain)
def pair_dir(states, name, token_in, token_out):
    st = states.get(name) or {}
    if st.get("token0()") == token_in and st.get("token1()") == token_out:
        return st.get("reserve0"), st.get("reserve1")
    if st.get("token0()") == token_out and st.get("token1()") == token_in:
        return st.get("reserve1"), st.get("reserve0")
    return None, None
loops = []
# loop A: USDC -> USDT -> DAI -> USDC using V2 pairs
for amt in [10**18, 10*10**18, 100*10**18, 1000*10**18]:
    a = amt
    r_in, r_out = pair_dir(states, "USDC/USDT", USDC, USDT)
    b = q_v2(a, r_in, r_out)
    r_in, r_out = pair_dir(states, "USDT/DAI", USDT, DAI)
    c = q_v2(b, r_in, r_out)
    r_in, r_out = pair_dir(states, "DAI/USDC", DAI, USDC)
    d = q_v2(c, r_in, r_out)
    loops.append({"loop": "USDC->USDT->DAI->USDC", "amount_in_usdc": a / 1e18, "out_usdc": d / 1e18,
                  "net_usdc": (d - a) / 1e18, "net_bps": (d - a) / a * 10000 if a else None})
# loop B: USDT -> USDC -> (USDC/USDT same pool forbidden); use USDT->BUSD->USDC if BUSD pools exist
r_in, r_out = pair_dir(states, "USDT/BUSD", USDT, BUSD); r_in2, r_out2 = pair_dir(states, "USDC/BUSD", USDC, BUSD)
if r_in and r_in2:
    for amt in [10**18, 10*10**18, 100*10**18]:
        b = q_v2(amt, r_in, r_out)
        d = q_v2(b, r_out2, r_in2)  # BUSD -> USDC direction: token_in BUSD => reserve BUSD, reserve USDC
        loops.append({"loop": "USDT->BUSD->USDC (not closed to USDT)", "amount_in_usdt": amt / 1e18, "out_usdc": d / 1e18})
out["loops"] = loops
out["fee_assumption"] = "PancakeSwap V2 0.25% (9975/10000)；协议常量，本轮未从链上读费率"
out["finished_at_utc"] = now()
out["requests"] = reqs
out["request_count"] = len(reqs)
save("bnb03_summary.json", out)
print(json.dumps({k: out.get(k) for k in ["chain_id", "latest_block", "latest_block_time_utc", "pinned_block",
    "pancake_v2_factory_code_bytes", "token_identity", "v2_pairs", "pair_states", "loops", "request_count"]},
    ensure_ascii=False, indent=1)[:12000])
