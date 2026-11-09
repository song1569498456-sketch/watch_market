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
def sel(sig):
    h = keccak.new(digest_bits=256); h.update(sig.encode()); return "0x" + h.hexdigest()[:8]
prev = json.load(open(BASE + r"\discovery.json", encoding="utf-8"))
pinned = hex(prev["pinned_block"])
USDC, USDT, DAI, BUSD = ("0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d", "0x55d398326f99059fF775485246999027B3197955",
                        "0x1AF3F329e8BE154074D8769D1FFa4eE058B1DBc3", "0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56")
V2F = "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"
PK = {"USDC/USDT": prev["v2_pairs"]["USDC/USDT"], "USDT/DAI": prev["v2_pairs"]["USDT/DAI"],
      "DAI/USDC": prev["v2_pairs"]["DAI/USDC"], "USDC/BUSD": prev["v2_pairs"]["USDC/BUSD"],
      "USDT/BUSD": prev["v2_pairs"]["USDT/BUSD"]}
reqs = []
def batch(calls, name):
    t0 = time.time()
    r = s.post(RPC, json=[{"jsonrpc": "2.0", "id": k, "method": m, "params": p} for k, (m, p) in enumerate(calls)], timeout=60)
    reqs.append({"name": name, "http_status": r.status_code, "at": now(), "n_calls": len(calls),
                 "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(),
                 "elapsed_s": round(time.time()-t0, 3)})
    d = r.json()
    if isinstance(d, dict): d = [d]
    return d
# read one pair at a time (small batches) to avoid RPC batch limits
out = {"started_at_utc": now(), "pinned_block": prev["pinned_block"], "pairs": {}}
for name, addr in PK.items():
    if not addr: continue
    calls = [("eth_getCode", [addr, pinned]),
             ("eth_call", [{"to": addr, "data": sel("token0()")}, pinned]),
             ("eth_call", [{"to": addr, "data": sel("token1()")}, pinned]),
             ("eth_call", [{"to": addr, "data": sel("getReserves()")}, pinned]),
             ("eth_call", [{"to": addr, "data": sel("factory()")}, pinned]),
             ("eth_call", [{"to": addr, "data": sel("totalSupply()")}, pinned])]
    res = batch(calls, f"pair_{name.replace('/', '_')}")
    d = {"address": addr}
    d["code_bytes"] = (len(res[0].get("result") or "0x")-2)//2
    def a(i): 
        v = res[i].get("result")
        return ("0x" + v[-40:]) if v and len(v) >= 66 else None
    d["token0"] = a(1); d["token1"] = a(2); d["factory"] = a(4)
    v = res[3].get("result")
    if v and len(v) >= 130:
        d["reserve0"] = int(v[2:66], 16); d["reserve1"] = int(v[66:130], 16)
        d["reserves_raw"] = v
    tv = res[5].get("result")
    d["lp_total_supply"] = int(tv, 16) if tv and tv != "0x" else None
    out["pairs"][name] = d
    time.sleep(0.3)
save_pairs = out["pairs"]
# compute loops (Pancake V2 fee 0.25% -> 9975/10000)
def dirs(st, t_in, t_out):
    if st.get("token0") == t_in and st.get("token1") == t_out: return st.get("reserve0"), st.get("reserve1")
    if st.get("token0") == t_out and st.get("token1") == t_in: return st.get("reserve1"), st.get("reserve0")
    return None, None
def q(amount, r_in, r_out):
    if not amount or not r_in or not r_out: return 0
    ain = amount * 9975
    return (ain * r_out) // (r_in * 10000 + ain)
loops = []
for amt in [10**18, 10*10**18, 100*10**18, 1000*10**18]:
    p1 = save_pairs.get("USDC/USDT", {}); r1i, r1o = dirs(p1, USDC, USDT); b = q(amt, r1i, r1o)
    p2 = save_pairs.get("USDT/DAI", {}); r2i, r2o = dirs(p2, USDT, DAI); c = q(b, r2i, r2o)
    p3 = save_pairs.get("DAI/USDC", {}); r3i, r3o = dirs(p3, DAI, USDC); d = q(c, r3i, r3o)
    loops.append({"loop": "USDC->USDT->DAI->USDC", "amount_in_usdc": amt/1e18, "leg1_usdt": b/1e18,
                  "leg2_dai": c/1e18, "leg3_usdc": d/1e18, "net_usdc": (d-amt)/1e18,
                  "net_bps": ((d-amt)/amt*10000) if amt else None})
    # reverse loop: USDC->DAI->USDT->USDC
    r3i2, r3o2 = dirs(p3, USDC, DAI); e = q(amt, r3i2, r3o2)
    r2i2, r2o2 = dirs(p2, DAI, USDT); f = q(e, r2i2, r2o2)
    r1i2, r1o2 = dirs(p1, USDT, USDC); g = q(f, r1i2, r1o2)
    loops.append({"loop": "USDC->DAI->USDT->USDC", "amount_in_usdc": amt/1e18, "leg1_dai": e/1e18,
                  "leg2_usdt": f/1e18, "leg3_usdc": g/1e18, "net_usdc": (g-amt)/1e18,
                  "net_bps": ((g-amt)/amt*10000) if amt else None})
out["loops"] = loops
out["fee_assumption"] = "PancakeSwap V2 0.25%（9975/10000）；协议常量，本轮未链上读费率"
out["finished_at_utc"] = now()
out["requests"] = prev.get("requests", []) + reqs
out["request_count"] = len(out["requests"])
json.dump(out, open(BASE + r"\loops.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps({"pairs": save_pairs, "loops": loops, "requests": reqs}, ensure_ascii=False, indent=1)[:9000])
