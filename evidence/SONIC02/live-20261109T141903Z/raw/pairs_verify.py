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
def sel(sig):
    h = keccak.new(digest_bits=256); h.update(sig.encode()); return "0x" + h.hexdigest()[:8]
prev = json.load(open(BASE + r"\sonic_summary.json", encoding="utf-8"))
pinned = hex(prev["pinned_block"])
PAIRS = {"shadow_sts_ws": "0xde861c8Fc9AB78fE00490C5a38813D26e2d09C95",
         "beets_sts_usdc": "0x713FB5036dC70012588d77a5B066f1Dd05c712d7"}
calls = []
tags = []
for name, p in PAIRS.items():
    calls.append(("eth_getCode", [p, pinned])); tags.append((name, "code"))
    for f in ["token0()", "token1()", "getReserves()", "fee()", "factory()"]:
        calls.append(("eth_call", [{"to": p, "data": sel(f)}, pinned])); tags.append((name, f))
t0 = time.time()
r = s.post(RPC, json=[{"jsonrpc": "2.0", "id": k, "method": m, "params": pp} for k, (m, pp) in enumerate(calls)], timeout=60)
res = r.json()
def num(v): return int(v, 16) if v and v != "0x" else None
def addr(v): return ("0x" + v[-40:]) if v and len(v) >= 66 else None
out = {"at_utc": now(), "pinned_block": prev["pinned_block"], "pairs": {},
       "req": {"http_status": r.status_code, "sha256": hashlib.sha256(r.content).hexdigest(),
               "elapsed_s": round(time.time()-t0, 3)}}
for (name, f), rr in zip(tags, res):
    d = out["pairs"].setdefault(name, {})
    v = rr.get("result")
    if f == "code": d["code_bytes"] = (len(v or "0x")-2)//2
    elif f in ("token0()", "token1()", "factory()"): d[f] = addr(v)
    elif f == "getReserves()":
        if v and v != "0x" and len(v) >= 130:
            d["reserve0"] = str(int(v[2:66], 16)); d["reserve1"] = str(int(v[66:130], 16))
        else: d["getReserves_error"] = rr.get("error")
    elif f == "fee()": d["fee"] = num(v)
out["requests"] = prev.get("requests", []) + [{"name": "verify_pairs", **out["req"]}]
out["request_count"] = len(out["requests"])
json.dump(out, open(BASE + r"\pairs_verify.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1)[:6000])
