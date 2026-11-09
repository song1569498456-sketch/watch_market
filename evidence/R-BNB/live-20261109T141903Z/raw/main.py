import json, time, hashlib, datetime
import requests
from Crypto.Hash import keccak
BASE = r"D:\ds-arb-test\watch_market\evidence\R-BNB\live-20261109T141903Z\raw"
PROXY = "http://127.0.0.1:7897"
RPC = "https://bsc-dataseed.bnbchain.org"
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
REGISTRY = "0x9F7b01A536aFA00EF10310A162877fd792cD0666"
CORE = "0xfD36E2c2a6789Db23113685031d7F16329158384"
IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
# 1) chain + registry + core comptroller + markets
calls = [("eth_chainId", []), ("eth_blockNumber", []), ("eth_getBlockByNumber", ["latest", False]),
         ("eth_getCode", [REGISTRY, "latest"]), ("eth_getStorageAt", [REGISTRY, IMPL_SLOT, "latest"]),
         ("eth_call", [{"to": REGISTRY, "data": sel("getAllPools()")}, "latest"]),
         ("eth_getCode", [CORE, "latest"]),
         ("eth_call", [{"to": CORE, "data": sel("oracle()")}, "latest"]),
         ("eth_call", [{"to": CORE, "data": sel("getAllMarkets()")}, "latest"])]
res = batch(calls, "identity_and_markets")
out["chain_id"] = int(res[0]["result"], 16)
out["latest_block"] = int(res[1]["result"], 16)
blk = res[2]["result"]
out["latest_block_time_utc"] = datetime.datetime.fromtimestamp(int(blk["timestamp"], 16), datetime.timezone.utc).isoformat()
out["pinned_block"] = out["latest_block"] - 5
def addr(v): return ("0x" + v[-40:]) if v and len(v) >= 66 else None
def num(v): return int(v, 16) if v and v != "0x" else None
def decode_array_addr(v):
    if not v or v == "0x": return []
    h = v[2:]; off = int(h[0:64], 16)*2; ln = int(h[off:off+64], 16); res2 = []
    for k in range(ln):
        st = off + 64 + k*64
        res2.append("0x" + h[st:st+64][-40:])
    return res2
out["registry_code_bytes"] = (len(res[3].get("result") or "0x")-2)//2
impl = res[4].get("result")
out["registry_impl"] = ("0x" + impl[-40:]) if impl and len(impl) >= 66 else None
out["all_pools"] = decode_array_addr(res[5].get("result"))
out["core_comptroller_code_bytes"] = (len(res[6].get("result") or "0x")-2)//2
out["core_oracle"] = addr(res[7].get("result"))
out["core_markets"] = decode_array_addr(res[8].get("result"))
save("identity.json", out)
time.sleep(0.3)
pinned = hex(out["pinned_block"])
markets = out["core_markets"][:15]
ORACLE = out["core_oracle"]
# 2) per-market: markets(vToken) -> (listed, collateralFactor, comped); underlying(); oracle price; cash; borrows
def calls_for(chunk):
    c = []
    for vt in chunk:
        c.append(("eth_call", [{"to": CORE, "data": sel("markets(address)") + enc(vt)}, pinned]))
        c.append(("eth_call", [{"to": vt, "data": sel("underlying()")}, pinned]))
        c.append(("eth_call", [{"to": vt, "data": sel("getCash()")}, pinned]))
        c.append(("eth_call", [{"to": vt, "data": sel("totalBorrows()")}, pinned]))
        c.append(("eth_call", [{"to": ORACLE, "data": sel("getUnderlyingPrice(address)") + enc(vt)}, pinned]))
    return c
rows = {}
start = 0
chunks = [markets[i:i+4] for i in range(0, min(len(markets), 16), 4)]
for chunk in chunks:
    if not chunk: continue
    res2 = batch(calls_for(chunk), f"market_params_{start}")
    start += 1
    n_calls = len(chunk)*5
    if len(res2) < n_calls:
        res2 = res2 + [{} for _ in range(n_calls - len(res2))]
    for idx, vt in enumerate(chunk):
        base_i = idx*5
        m = res2[base_i].get("result")
        row = {"vToken": vt}
        if m and len(m) >= 66:
            words = [m[2+i*64:2+(i+1)*64] for i in range(len(m)//64)]
            row["isListed"] = bool(int(words[0], 16))
            row["collateralFactorMantissa"] = int(words[1], 16) if len(words) > 1 else None
            row["cf_pct"] = (int(words[1], 16)/1e18*100) if len(words) > 1 else None
        row["underlying"] = addr(res2[base_i+1].get("result"))
        row["cash"] = str(num(res2[base_i+2].get("result")))
        row["totalBorrows"] = str(num(res2[base_i+3].get("result")))
        row["oracle_price_1e18"] = str(num(res2[base_i+4].get("result")))
        rows[vt] = row
    time.sleep(0.3)
out["core_market_rows"] = rows
save("markets.json", out)
time.sleep(0.3)
# 3) DEX depth for a couple of collateral assets: Pancake V2 pairs BUSD/USDT, BUSD/USDC
V2F = "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"
BUSD = "0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56"
USDT = "0x55d398326f99059fF775485246999027B3197955"
USDC = "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d"
res3 = batch([("eth_call", [{"to": V2F, "data": sel("getPair(address,address)") + enc(BUSD) + enc(USDT)}, pinned]),
              ("eth_call", [{"to": V2F, "data": sel("getPair(address,address)") + enc(BUSD) + enc(USDC)}, pinned])], "busd_pairs")
bp1 = addr(res3[0].get("result")); bp2 = addr(res3[1].get("result"))
out["busd_pairs"] = {"BUSD/USDT": bp1, "BUSD/USDC": bp2}
if bp1:
    res4 = batch([("eth_call", [{"to": bp1, "data": sel("getReserves()")}, pinned])], "busd_pair_reserves")
    v = res4[0].get("result")
    if v and len(v) >= 130:
        out["busd_usdt_reserves"] = {"reserve0": str(int(v[2:66], 16)), "reserve1": str(int(v[66:130], 16))}
out["finished_at_utc"] = now()
out["requests"] = reqs
out["request_count"] = len(reqs)
save("rbnb_summary.json", out)
print(json.dumps(out, ensure_ascii=False, indent=1)[:11000])
