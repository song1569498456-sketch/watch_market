import json, time, hashlib, datetime
import requests
from Crypto.Hash import keccak
BASE = r"D:\ds-arb-test\watch_market\evidence\BASE05\live-20261109T141903Z\raw"
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
out = {"started_at_utc": now()}
# 1) discovery: Aerodrome pools via DexScreener search
t0 = time.time()
r = s.get("https://api.dexscreener.com/latest/dex/search?q=AERO%20USDC", timeout=40)
reqs.append({"name": "dexscreener_aero_usdc", "url": r.url, "http_status": r.status_code, "at": now(),
             "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(),
             "elapsed_s": round(time.time()-t0, 3)})
ds = []
if r.status_code == 200:
    for p in (r.json().get("pairs") or []):
        if p.get("chainId") != "base" or p.get("dexId") != "aerodrome":
            continue
        ds.append({"pair": p.get("pairAddress"), "base": (p.get("baseToken") or {}).get("address"),
                   "baseSymbol": (p.get("baseToken") or {}).get("symbol"),
                   "quote": (p.get("quoteToken") or {}).get("address"),
                   "quoteSymbol": (p.get("quoteToken") or {}).get("symbol"),
                   "priceUsd": p.get("priceUsd"), "priceNative": p.get("priceNative"),
                   "liquidityUsd": (p.get("liquidity") or {}).get("usd")})
ds.sort(key=lambda x: -(x.get("liquidityUsd") or 0))
out["dexscreener_aerodrome_pairs"] = ds[:8]
time.sleep(0.4)
# 2) chain identity
t0 = time.time()
r = s.post(RPC, json=[{"jsonrpc": "2.0", "id": 0, "method": "eth_chainId", "params": []},
                      {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []},
                      {"jsonrpc": "2.0", "id": 2, "method": "eth_getBlockByNumber", "params": ["latest", False]}], timeout=40)
reqs.append({"name": "chain_identity", "http_status": r.status_code, "at": now(),
             "sha256": hashlib.sha256(r.content).hexdigest(), "elapsed_s": round(time.time()-t0, 3)})
d = {x.get("id"): x for x in r.json()}
out["chain_id"] = int(d[0]["result"], 16)
out["latest_block"] = int(d[1]["result"], 16)
blk = d[2]["result"]; out["latest_block_time_utc"] = datetime.datetime.fromtimestamp(int(blk["timestamp"], 16), datetime.timezone.utc).isoformat()
out["pinned_block"] = out["latest_block"] - 5
pinned = hex(out["pinned_block"])
time.sleep(0.4)
# pick pool: highest-liquidity AERO/USDC aerodrome pair
POOL = (ds[0]["pair"] if ds else None)
out["pool"] = POOL
AERO = "0x940181a94a35a4569e4529a3cdfb74e38fd98631"
calls = []; tags = []
if POOL:
    calls.append(("eth_getCode", [POOL, pinned])); tags.append(("code",))
    for f in ["token0()", "token1()", "stable()", "totalSupply()", "getReserves()", "factory()", "gauge()", "fee()", "isPaused()"]:
        calls.append(("eth_call", [{"to": POOL, "data": sel(f)}, pinned])); tags.append((f,))
time.sleep(0.4)
r = s.post(RPC, json=[{"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls)], timeout=60)
reqs.append({"name": "pool_state", "http_status": r.status_code, "at": now(), "n_calls": len(calls),
             "sha256": hashlib.sha256(r.content).hexdigest()})
res = r.json()
pool = {}
for (tag,), rr in zip(tags, res):
    v = rr.get("result")
    if tag == "code": pool["code_bytes"] = (len(v or "0x")-2)//2
    elif tag in ("token0()", "token1()", "factory()", "gauge()"):
        pool[tag] = ("0x" + v[-40:]) if v and len(v) >= 66 else None
    elif tag == "getReserves()":
        pool["reserves_raw"] = v
    elif tag in ("totalSupply()", "fee()"):
        pool[tag] = int(v, 16) if v and v != "0x" else None
    elif tag == "stable()":
        pool[tag] = bool(int(v, 16)) if v and v != "0x" else None
    elif tag == "isPaused()":
        pool[tag] = (v if v else rr.get("error"))
out["pool_state_raw"] = pool
time.sleep(0.4)
# token metadata + gauge state (if any)
tokens = [t for t in [pool.get("token0()"), pool.get("token1()")] if t]
gauge = pool.get("gauge()") if pool.get("gauge()") and int(pool["gauge()"], 16) != 0 else None
out["gauge"] = gauge
calls = []; tags = []
for t in tokens:
    calls.append(("eth_call", [{"to": t, "data": sel("symbol()")}, pinned])); tags.append(("symbol", t))
    calls.append(("eth_call", [{"to": t, "data": sel("decimals()")}, pinned])); tags.append(("decimals", t))
if gauge:
    calls.append(("eth_getCode", [gauge, pinned])); tags.append(("gcode",))
    for f in ["isAlive()", "rewardRate()", "totalSupply()", "rewardToken()", "periodFinish()"]:
        calls.append(("eth_call", [{"to": gauge, "data": sel(f)}, pinned])); tags.append((f,))
time.sleep(0.4)
r = s.post(RPC, json=[{"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls)], timeout=60)
reqs.append({"name": "token_gauge_state", "http_status": r.status_code, "at": now(), "n_calls": len(calls),
             "sha256": hashlib.sha256(r.content).hexdigest()})
res = r.json()
tmeta = {}; gstate = {}
def dec_str(v):
    if not v or len(v) < 130: return None
    try:
        h = v[2:]; ln = int(h[64:128], 16)
        if ln > 100: return None
        return bytes.fromhex(h[128:128+ln*2]).decode("utf-8", "replace")
    except Exception: return None
for (tag, *rest), rr in zip(tags, res):
    v = rr.get("result")
    if tag == "symbol": tmeta.setdefault(rest[0], {})["symbol"] = dec_str(v)
    elif tag == "decimals": tmeta.setdefault(rest[0], {})["decimals"] = int(v, 16) if v and v != "0x" else None
    elif tag == "gcode": gstate["code_bytes"] = (len(v or "0x")-2)//2
    elif tag in ("isAlive()",): gstate[tag] = bool(int(v, 16)) if v and v != "0x" else None
    elif tag in ("rewardRate()", "totalSupply()", "periodFinish()"): gstate[tag] = int(v, 16) if v and v != "0x" else None
    elif tag == "rewardToken()": gstate[tag] = ("0x" + v[-40:]) if v and len(v) >= 66 else None
out["token_meta"] = tmeta; out["gauge_state"] = gstate
save("state.json", out)
time.sleep(0.4)

# 3) compute same-block mint/burn roundtrip and separate columns
res_rows = []
if pool.get("reserves_raw") and len(pool["reserves_raw"]) >= 130 and pool.get("totalSupply()"):
    r0 = int(pool["reserves_raw"][2:66], 16); r1 = int(pool["reserves_raw"][66:130], 16)
    S = pool["totalSupply()"]
    t0_, t1_ = pool.get("token0()"), pool.get("token1()")
    dec0 = tmeta.get(t0_, {}).get("decimals") or 18
    dec1 = tmeta.get(t1_, {}).get("decimals") or 18
    out["reserves_human"] = {"token0": r0 / 10**dec0, "token1": r1 / 10**dec1,
                             "token0_contract": t0_, "token1_contract": t1_}
    out["lp_total_supply_human"] = S / 10**18
    # deposit tiers: proportional amounts for 1/10/100 token0-equivalent
    for amt0_h in [1, 10, 100]:
        a0 = int(amt0_h * 10**dec0)
        a1 = a0 * r1 // r0
        minted = min(a0 * S // r0, a1 * S // r1)
        # burn same LP immediately, same block state
        b0 = minted * r0 // S; b1 = minted * r1 // S
        # net in token0-equivalent units using pool reserve ratio
        net0 = b0 / 10**dec0 - a0 / 10**dec0
        net1 = b1 / 10**dec1 - a1 / 10**dec1
        net_value_token0 = net0 + net1 * (r0 / 10**dec0) / (r1 / 10**dec1) if r1 else None
        res_rows.append({"deposit_token0": amt0_h, "deposit_token1": a1 / 10**dec1,
                         "lp_minted_18": minted / 10**18, "burn_token0": b0 / 10**dec0,
                         "burn_token1": b1 / 10**dec1, "net_token0": net0, "net_token1": net1,
                         "net_value_in_token0": net_value_token0})
out["mint_burn_roundtrip"] = res_rows
out["columns"] = {
    "lp_share_value_change": "由池储备/总份额变化决定；本轮为同块静态快照，无价格变化",
    "pool_fees_claimable": "PoolFees 与核心储备分离（上一轮源码），本轮未读池费累计；不计入净额",
    "gauge_emissions": {"rewardRate_raw": gstate.get("rewardRate()"),
                        "gauge_totalSupply_raw": gstate.get("totalSupply()"),
                        "note": "AERO 排放是外部奖励，单独列示；LP 入 Gauge 后会让渡池费权利（上一轮源码），不与池费双计"},
    "deposit_withdraw_fees": {"pool_fee_swap": pool.get("fee()"), "note": "Aerodrome Pool mint/burn 不收取 swap fee；fee() 是 swap 费，不机械当存取费"}}
out["finished_at_utc"] = now()
out["requests"] = reqs
out["request_count"] = len(reqs)
save("base05_summary.json", out)
print(json.dumps(out, ensure_ascii=False, indent=1)[:12000])
