import json, time, hashlib, datetime
import requests
from Crypto.Hash import keccak
BASE = r"D:\ds-arb-test\watch_market\evidence\N-AVAX\live-20261109T141903Z\raw"
PROXY = "http://127.0.0.1:7897"
RPC = "https://api.avax.network/ext/bc/C/rpc"
RPC2 = "https://avalanche-c-chain-rpc.publicnode.com"
s = requests.Session(); s.trust_env = False
s.proxies = {"http": PROXY, "https": PROXY}
s.headers.update({"User-Agent": "watch_market-readonly-research/1.0", "Content-Type": "application/json"})
now = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
reqs = []
def sel(sig):
    h = keccak.new(digest_bits=256); h.update(sig.encode()); return "0x" + h.hexdigest()[:8]
def save(n, o):
    json.dump(o, open(BASE + "\\" + n, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
def batch(calls, name, rpc=RPC, fallback=False):
    payload = [{"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls)]
    for rp in ([rpc] + ([RPC2] if fallback and rpc == RPC else [])):
        t0 = time.time()
        try:
            r = s.post(rp, json=payload, timeout=60)
            reqs.append({"name": name, "rpc": rp, "http_status": r.status_code, "at": now(), "n_calls": len(calls),
                         "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(),
                         "elapsed_s": round(time.time()-t0, 3)})
            d = r.json()
            if isinstance(d, dict): d = [d]
            if isinstance(d, list) and any("error" in x for x in d) and fallback and rp == RPC:
                continue
            return d
        except Exception as e:
            reqs.append({"name": name, "rpc": rp, "error": repr(e), "at": now()})
            continue
    return []
def get(url, name):
    t0 = time.time()
    try:
        r = s.get(url, timeout=40)
        reqs.append({"name": name, "url": url, "http_status": r.status_code, "at": now(),
                     "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(),
                     "elapsed_s": round(time.time()-t0, 3)})
        return r
    except Exception as e:
        reqs.append({"name": name, "url": url, "error": repr(e), "at": now()})
        return None

V21 = "0x8e42f2F4101563bF679975178e880FD87d3eFd4e"
prev = json.load(open(BASE + r"\avax_summary.json", encoding="utf-8"))
block = prev["latest_block"]
out = {"started_at_utc": now(), "latest_block_reference": block}
topic0 = "0x" + keccak.new(digest_bits=256, data=b"LBPairCreated(address,address,uint256,address,uint256)").hexdigest()
# 1) getLogs V2.1 over last 50k blocks (~27h at 2s), fallback once
fromb = max(0, block - 50000)
res = batch([("eth_getLogs", [{"address": V21, "fromBlock": hex(fromb), "toBlock": hex(block), "topics": [topic0]}])],
            "getlogs_v21_50k", fallback=True)
lg = res[0] if res else {}
out["getlogs_v21_50k"] = {"range": [fromb, block], "error": lg.get("error"), "count": len(lg.get("result") or [])}
events = lg.get("result") or []
out["getlogs_v21_events"] = [{"block": int(x["blockNumber"], 16), "tx": x.get("transactionHash"),
                              "topics": x.get("topics"), "data": x.get("data")} for x in events[:10]]
time.sleep(0.4)
# 2) block timestamps for first/last event block + factory implementation info
calls = [("eth_call", [{"to": V21, "data": sel("getLBPairImplementation()")}, "latest"])]
if events:
    for e in [events[0], events[-1]]:
        calls.append(("eth_getBlockByNumber", [e["blockNumber"], False]))
res = batch(calls, "impl_and_event_times", fallback=False)
impl = res[0].get("result")
out["lbpair_implementation"] = ("0x" + impl[-40:]) if impl and len(impl) >= 66 else None
if events and len(res) > 2:
    out["event_block_times_utc"] = [
        datetime.datetime.fromtimestamp(int(res[1].get("result", {}).get("timestamp", "0x0"), 16), datetime.timezone.utc).isoformat(),
        datetime.datetime.fromtimestamp(int(res[2].get("result", {}).get("timestamp", "0x0"), 16), datetime.timezone.utc).isoformat()]
time.sleep(0.4)
# 3) pair code (clone?) + impl code size + token symbols for newest live pairs
pairs = [p["pair"] for p in prev["newest_pairs"][:3]]
calls = [("eth_getCode", [pairs[0], "latest"]), ("eth_getCode", [out["lbpair_implementation"] or pairs[0], "latest"])]
tokens = ["0xb8d7710f7d8349a506b75dd184f05777c82dad0c", "0xb97ef9ef8734c71904d8002f8b6bc66dd9c48a6e",
          "0x8b1e2420e0d453a718d4b70e3a043263eab77851", "0xfd2c2a98009d0cbed715882036e43d26c4289053",
          "0x152b9d0fdc40c096757f570a51e494bd4b943e50"]
for t in tokens:
    calls.append(("eth_call", [{"to": t, "data": sel("symbol()")}, "latest"]))
    calls.append(("eth_call", [{"to": t, "data": sel("decimals()")}, "latest"]))
res = batch(calls, "pair_clone_and_tokens")
code0 = res[0].get("result") or "0x"
out["pair_clone_bytes"] = (len(code0)-2)//2
out["pair_clone_target"] = None
if "363d3d373d3d3d363d73" in code0:
    i = code0.find("363d3d373d3d3d363d73"); out["pair_clone_target"] = "0x" + code0[i+20:i+60]
out["impl_code_bytes"] = (len(res[1].get("result", "0x"))-2)//2 if res[1].get("result") else None
tmeta = {}
for k, t in enumerate(tokens):
    sv = res[2 + k*2].get("result"); dv = res[3 + k*2].get("result")
    sym = None
    if sv and len(sv) >= 130:
        try:
            ln = int(sv[66:130], 16)
            if ln < 100: sym = bytes.fromhex(sv[130:130+ln*2]).decode("utf-8", "replace")
        except Exception: pass
    tmeta[t] = {"symbol": sym, "decimals": int(dv, 16) if dv and dv != "0x" else None}
out["token_meta_more"] = tmeta
time.sleep(0.4)
# 4) avalanchego CHANGELOG (raw.githubusercontent, no key)
r = get("https://raw.githubusercontent.com/ava-labs/avalanchego/master/CHANGELOG.md", "avalanchego_changelog")
if r is not None and r.status_code == 200:
    txt = r.text
    open(BASE + r"\avalanchego_changelog_head.md", "w", encoding="utf-8").write(txt[:6000])
    import re
    vers = re.findall(r"^## \[?(v?1\.[0-9]+\.[0-9]+)\]?\s*[-–—]?\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", txt, re.M)
    out["avalanchego_recent_versions"] = vers[:10]
    out["changelog_head"] = txt[:800]
out["finished_at_utc"] = now()
out["requests"] = reqs
out["request_count"] = len(reqs)
save("avax_round2.json", out)
print(json.dumps({k: out.get(k) for k in ["getlogs_v21_50k", "getlogs_v21_events", "lbpair_implementation",
    "event_block_times_utc", "pair_clone_bytes", "pair_clone_target", "impl_code_bytes", "token_meta_more",
    "avalanchego_recent_versions", "changelog_head", "request_count", "requests"]}, ensure_ascii=False, indent=1)[:8000])
