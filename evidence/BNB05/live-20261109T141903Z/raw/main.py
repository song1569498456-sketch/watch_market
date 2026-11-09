import json, time, hashlib, datetime
import requests
from Crypto.Hash import keccak
BASE = r"D:\ds-arb-test\watch_market\evidence\BNB05\live-20261109T141903Z\raw"
PROXY = "http://127.0.0.1:7897"
RPC = "https://bsc-dataseed.bnbchain.org"
s = requests.Session(); s.trust_env = False
s.proxies = {"http": PROXY, "https": PROXY}
s.headers.update({"User-Agent": "watch_market-readonly-research/1.0", "Content-Type": "application/json"})
now = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
def sel(sig):
    h = keccak.new(digest_bits=256); h.update(sig.encode()); return "0x" + h.hexdigest()[:8]
def enc(a): return a[2:].rjust(64, "0")
reqs = []
out = {"started_at_utc": now()}
# 0) discovery: XVS liquidity pools
t0 = time.time()
r = s.get("https://api.dexscreener.com/latest/dex/search?q=XVS", timeout=40)
reqs.append({"name": "dexscreener_xvs", "url": r.url, "http_status": r.status_code, "at": now(),
             "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(),
             "elapsed_s": round(time.time()-t0, 3)})
ds = []
if r.status_code == 200:
    for p in (r.json().get("pairs") or []):
        if p.get("chainId") != "bsc" or (p.get("baseToken") or {}).get("symbol") != "XVS" and (p.get("quoteToken") or {}).get("symbol") != "XVS":
            continue
        ds.append({"pair": p.get("pairAddress"), "dexId": p.get("dexId"),
                   "baseSymbol": (p.get("baseToken") or {}).get("symbol"), "quoteSymbol": (p.get("quoteToken") or {}).get("symbol"),
                   "base": (p.get("baseToken") or {}).get("address"), "quote": (p.get("quoteToken") or {}).get("address"),
                   "priceUsd": p.get("priceUsd"), "liquidityUsd": (p.get("liquidity") or {}).get("usd")})
ds.sort(key=lambda x: -(x.get("liquidityUsd") or 0))
out["dexscreener_xvs_pairs"] = ds[:8]
time.sleep(0.4)
# 1) chain + contracts + public claim probes
XVS = "0xcF6BB5389c92Bdda8a3747Ddb454cB7a64626C63"
COMPTROLLER = "0xfD36E2c2a6789Db23113685031d7F16329158384"
VUSDT = "0xfD5840Cd36d94D7229439859C0112a4185BC0255"
WBNB = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
V2F = "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"
FRESH = "0x000000000000000000000000000000000000dEaD"
calls = [("eth_chainId", []), ("eth_blockNumber", []), ("eth_getBlockByNumber", ["latest", False]),
         ("eth_getCode", [COMPTROLLER, "latest"]), ("eth_getCode", [XVS, "latest"]),
         ("eth_call", [{"to": XVS, "data": sel("symbol()")}, "latest"]),
         ("eth_call", [{"to": XVS, "data": sel("decimals()")}, "latest"]),
         ("eth_call", [{"to": XVS, "data": sel("totalSupply()")}, "latest"]),
         ("eth_call", [{"to": COMPTROLLER, "data": sel("admin()")}, "latest"]),
         ("eth_call", [{"to": COMPTROLLER, "data": sel("implementation()")}, "latest"]),
         # public claim probe from fresh address (0 accrued expected)
         ("eth_call", [{"to": COMPTROLLER, "from": FRESH, "data": sel("claimVenus(address)") + enc(FRESH)}, "latest"]),
         ("eth_call", [{"to": COMPTROLLER, "from": FRESH, "data": sel("claimVenus(address,address[])") + enc(FRESH) + enc("0x40") + enc("0x0")}, "latest"]),
         # accrued rewards for fresh address
         ("eth_call", [{"to": COMPTROLLER, "data": sel("venusSupplierAccrued(address,address)") + enc(FRESH) + enc(VUSDT)}, "latest"]),
         ("eth_call", [{"to": COMPTROLLER, "data": sel("venusBorrowerAccrued(address,address)") + enc(FRESH) + enc(VUSDT)}, "latest"]),
         # XVS/WBNB Pancake V2 pair
         ("eth_call", [{"to": V2F, "data": sel("getPair(address,address)") + enc(XVS) + enc(WBNB)}, "latest"])]
t0 = time.time()
r = s.post(RPC, json=[{"jsonrpc": "2.0", "id": k, "method": m, "params": p} for k, (m, p) in enumerate(calls)], timeout=60)
reqs.append({"name": "venus_probe", "http_status": r.status_code, "at": now(), "n_calls": len(calls),
             "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(),
             "elapsed_s": round(time.time()-t0, 3)})
res = r.json()
out["chain_id"] = int(res[0]["result"], 16)
out["latest_block"] = int(res[1]["result"], 16)
blk = res[2]["result"]
out["latest_block_time_utc"] = datetime.datetime.fromtimestamp(int(blk["timestamp"], 16), datetime.timezone.utc).isoformat()
out["pinned_block"] = out["latest_block"] - 5
def dec_str(v):
    if not v or len(v) < 130: return None
    try:
        h = v[2:]; ln = int(h[64:128], 16)
        if ln > 100: return None
        return bytes.fromhex(h[128:128+ln*2]).decode("utf-8", "replace")
    except Exception: return None
def addr(v): return ("0x" + v[-40:]) if v and len(v) >= 66 else None
def num(v): return int(v, 16) if v and v != "0x" else None
out["comptroller_code_bytes"] = (len(res[3].get("result") or "0x")-2)//2
out["xvs_code_bytes"] = (len(res[4].get("result") or "0x")-2)//2
out["xvs"] = {"symbol": dec_str(res[5].get("result")), "decimals": num(res[6].get("result")),
              "totalSupply": num(res[7].get("result"))}
out["comptroller_admin"] = addr(res[8].get("result"))
out["comptroller_implementation"] = addr(res[9].get("result"))
out["claimVenus_single_probe"] = res[10].get("result") if res[10].get("result") else res[10].get("error")
out["claimVenus_array_probe"] = res[11].get("result") if res[11].get("result") else res[11].get("error")
out["fresh_supplier_accrued"] = num(res[12].get("result"))
out["fresh_borrower_accrued"] = num(res[13].get("result"))
pair = addr(res[14].get("result"))
out["xvs_wbnb_pair"] = pair if pair and int(pair, 16) != 0 else None
json.dump(out, open(BASE + r"\venus_probe.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
time.sleep(0.4)
# 2) read XVS/WBNB V2 pair state (sell liquidity) if exists
pinned = hex(out["pinned_block"])
if out["xvs_wbnb_pair"]:
    p = out["xvs_wbnb_pair"]
    calls = [("eth_call", [{"to": p, "data": sel("token0()")}, pinned]),
             ("eth_call", [{"to": p, "data": sel("token1()")}, pinned]),
             ("eth_call", [{"to": p, "data": sel("getReserves()")}, pinned]),
             ("eth_call", [{"to": p, "data": sel("factory()")}, pinned]),
             ("eth_code", [p, pinned])]
    t0 = time.time()
    r = s.post(RPC, json=[{"jsonrpc": "2.0", "id": k, "method": "eth_getCode" if m == "eth_code" else m, "params": pp} for k, (m, pp) in enumerate(calls)], timeout=60)
    reqs.append({"name": "xvs_pair_state", "http_status": r.status_code, "at": now(), "n_calls": len(calls),
                 "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(),
                 "elapsed_s": round(time.time()-t0, 3)})
    res = r.json()
    st = {"pair": p, "token0": addr(res[0].get("result")), "token1": addr(res[1].get("result")),
          "factory": addr(res[3].get("result")), "code_bytes": (len(res[4].get("result") or "0x")-2)//2}
    v = res[2].get("result")
    if v and len(v) >= 130:
        st["reserve0"] = int(v[2:66], 16); st["reserve1"] = int(v[66:130], 16)
    out["xvs_wbnb_pair_state"] = st
out["finished_at_utc"] = now()
out["requests"] = reqs
out["request_count"] = len(reqs)
json.dump(out, open(BASE + r"\bnb05_summary.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1)[:8000])
