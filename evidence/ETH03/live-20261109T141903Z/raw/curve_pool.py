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
def sel(sig):
    h = keccak.new(digest_bits=256); h.update(sig.encode()); return "0x" + h.hexdigest()[:8]
prev = json.load(open(BASE + r"\eth03_summary.json", encoding="utf-8"))
POOL = "0xcE6431D21E3fb1036CE9973a3312368ED96F5CE7"
pinned = hex(prev["pinned_block"])
calls = [("eth_getCode", [POOL, pinned]),
         ("eth_call", [{"to": POOL, "data": sel("coins(uint256)") + hex(0)[2:].rjust(64, "0")}, pinned]),
         ("eth_call", [{"to": POOL, "data": sel("coins(uint256)") + hex(1)[2:].rjust(64, "0")}, pinned]),
         ("eth_call", [{"to": POOL, "data": sel("balances(uint256)") + hex(0)[2:].rjust(64, "0")}, pinned]),
         ("eth_call", [{"to": POOL, "data": sel("balances(uint256)") + hex(1)[2:].rjust(64, "0")}, pinned]),
         ("eth_call", [{"to": POOL, "data": sel("fee()")}, pinned]),
         ("eth_call", [{"to": POOL, "data": sel("A()")}, pinned]),
         ("eth_call", [{"to": POOL, "data": sel("get_dy(int128,int128,uint256)") + hex(0)[2:].rjust(64, "0") + hex(1)[2:].rjust(64, "0") + hex(10**18)[2:].rjust(64, "0")}, pinned]),
         ("eth_call", [{"to": POOL, "data": sel("get_dy(int128,int128,uint256)") + hex(1)[2:].rjust(64, "0") + hex(0)[2:].rjust(64, "0") + hex(10**18)[2:].rjust(64, "0")}, pinned])]
t0 = time.time()
r = s.post(RPC, json=[{"jsonrpc": "2.0", "id": k, "method": m, "params": p} for k, (m, p) in enumerate(calls)], timeout=60)
res = r.json()
out = {"at_utc": now(), "pinned_block": prev["pinned_block"], "pool": POOL,
       "req": {"http_status": r.status_code, "sha256": hashlib.sha256(r.content).hexdigest(),
               "elapsed_s": round(time.time()-t0, 3)}}
def addr(v): return ("0x" + v[-40:]) if v and len(v) >= 66 else None
def num(v): return int(v, 16) if v and v != "0x" else None
out["pool_code_bytes"] = (len(res[0].get("result") or "0x")-2)//2
c0 = addr(res[1].get("result")); c1 = addr(res[2].get("result"))
out["coins"] = [c0, c1]
out["balances"] = [str(num(res[3].get("result"))), str(num(res[4].get("result")))]
out["fee"] = num(res[5].get("result")); out["A"] = num(res[6].get("result"))
out["get_dy_0_to_1_1e18"] = str(num(res[7].get("result")))
out["get_dy_1_to_0_1e18"] = str(num(res[8].get("result")))
# token metadata for the 2 coins
calls2 = []
for t in [c0, c1]:
    calls2.append(("eth_call", [{"to": t, "data": sel("symbol()")}, pinned]))
    calls2.append(("eth_call", [{"to": t, "data": sel("decimals()")}, pinned]))
t0 = time.time()
r2 = s.post(RPC, json=[{"jsonrpc": "2.0", "id": k, "method": m, "params": p} for k, (m, p) in enumerate(calls2)], timeout=60)
res2 = r2.json()
out["req2"] = {"http_status": r2.status_code, "sha256": hashlib.sha256(r2.content).hexdigest(),
               "elapsed_s": round(time.time()-t0, 3)}
def dec_str(v):
    if not v or len(v) < 130: return None
    try:
        h = v[2:]; ln = int(h[64:128], 16)
        if ln > 100: return None
        return bytes.fromhex(h[128:128+ln*2]).decode("utf-8", "replace")
    except Exception: return None
meta = {}
for i, t in enumerate([c0, c1]):
    meta[t] = {"symbol": dec_str(res2[i*2].get("result")), "decimals": num(res2[i*2+1].get("result"))}
out["coin_meta"] = meta
# implied interpretation: if coin0=sDAI(18), coin1=FRAX(18): 1 sDAI -> X FRAX
out["requests"] = prev.get("requests", []) + [{"name": "curve_pool", **out["req"]}, {"name": "curve_pool_tokens", **out["req2"]}]
out["request_count"] = len(out["requests"])
json.dump(out, open(BASE + r"\curve_pool.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1)[:4000])
