import json, time, hashlib, datetime
import requests
from Crypto.Hash import keccak
BASE = r"D:\ds-arb-test\watch_market\evidence\N-BASE\live-20261109T141903Z\raw"
PROXY = "http://127.0.0.1:7897"
RPC = "https://mainnet.base.org"
s = requests.Session(); s.trust_env = False
s.proxies = {"http": PROXY, "https": PROXY}
s.headers.update({"User-Agent": "watch_market-readonly-research/1.0", "Content-Type": "application/json"})
now = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
def sel(sig):
    h = keccak.new(digest_bits=256); h.update(sig.encode()); return "0x" + h.hexdigest()[:8]
reqs = []
def batch(calls, name):
    t0 = time.time()
    payload = [{"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls)]
    r = s.post(RPC, json=payload, timeout=60)
    reqs.append({"name": name, "http_status": r.status_code, "at": now(), "n_calls": len(calls),
                 "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(),
                 "elapsed_s": round(time.time()-t0, 3)})
    d = r.json()
    if isinstance(d, dict): d = [d]
    return d
def decode_string(v):
    if not v or len(v) < 130: return None
    try:
        h = v[2:]
        ln = int(h[64:128], 16)
        if ln > 200: return None
        return bytes.fromhex(h[128:128+ln*2]).decode("utf-8", "replace")
    except Exception:
        return None
POOL = "0x7cc81e85c1fbb207c13dbb5cdb387c1953808e30"
tokens = ["0x4200000000000000000000000000000000000006", "0x9554b45fd068bc3fe780e5ae4cfcc9a7191c5a60",
          "0x2f84b9599b710447a9faa4f6242d6da0a3d5521f", "0x329105c15ac753c8d23a9105abe2c63578f6002a"]
calls = [("eth_getCode", [POOL, "latest"])]
tags = ["pool_clone_code"]
for t in tokens:
    calls.append(("eth_call", [{"to": t, "data": sel("symbol()")}, "latest"])); tags.append(f"symbol_{t}")
    calls.append(("eth_call", [{"to": t, "data": sel("name()")}, "latest"])); tags.append(f"name_{t}")
res = batch(calls, "final_verify")
out = {"at_utc": now(), "requests": reqs}
code = res[0].get("result") or "0x"
out["pool_clone_code"] = code
out["pool_clone_code_bytes"] = (len(code)-2)//2
if len(code) > 2 and "363d3d373d3d3d363d73" in code:
    idx = code.find("363d3d373d3d3d363d73")
    out["clone_target"] = "0x" + code[idx+20: idx+60]
out["tokens"] = {}
for i, tag in enumerate(tags[1:], start=1):
    kind, addr = tag.split("_", 1)
    v = res[i].get("result")
    out["tokens"].setdefault(addr, {})[kind] = decode_string(v)
out["finished_at_utc"] = now()
json.dump(out, open(BASE + r"\final_verify.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps({k: out[k] for k in ["at_utc", "finished_at_utc", "pool_clone_code_bytes", "clone_target", "tokens", "requests"]}, ensure_ascii=False, indent=1)[:4000])
