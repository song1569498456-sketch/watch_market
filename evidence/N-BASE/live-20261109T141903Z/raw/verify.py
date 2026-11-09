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
reqs = []
def sel(sig):
    h = keccak.new(digest_bits=256); h.update(sig.encode()); return "0x" + h.hexdigest()[:8]
def save(n, o):
    json.dump(o, open(BASE + "\\" + n, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
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

FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"
prev = json.load(open(BASE + r"\nbase_summary.json", encoding="utf-8"))
block = prev["latest_block"]
out = {"started_at_utc": now(), "latest_block_reference": block}
pools = [p for p in prev["newest_pools_by_index"] if p["index"] in (29930, 29929)]
meta = {m["index"]: m for m in prev["newest_pool_metadata"] if m["index"] in (29930, 29929)}
offsets = [43200, 21600, 10800, 5400, 2700, 1350]
calls = []
tags = []
impl = "0xa4e46b4f701c62e14df11b48dce76a7d793cd6d7"
calls.append(("eth_getCode", [impl, "latest"])); tags.append(("impl_code", impl))
for p in pools:
    for off in offsets:
        calls.append(("eth_getCode", [p["pool"], hex(block - off)])); tags.append((f"probe_{p['index']}_{off}", p["pool"]))
    calls.append(("eth_call", [{"to": FACTORY, "data": sel("getFee(address)") + p["pool"][2:].rjust(64, "0")}, "latest"])); tags.append((f"getFee_{p['index']}", p["pool"]))
    calls.append(("eth_call", [{"to": FACTORY, "data": sel("isPool(address)") + p["pool"][2:].rjust(64, "0")}, "latest"])); tags.append((f"isPool_{p['index']}", p["pool"]))
    calls.append(("eth_call", [{"to": FACTORY, "data": sel("stableFee()")}, "latest"])); tags.append((f"stableFee_{p['index']}", FACTORY))
    calls.append(("eth_call", [{"to": FACTORY, "data": sel("volatileFee()")}, "latest"])); tags.append((f"volatileFee_{p['index']}", FACTORY))
    for tok in [meta[p["index"]]["token0()"], meta[p["index"]]["token1()"]]:
        calls.append(("eth_call", [{"to": tok, "data": sel("symbol()")}, "latest"])); tags.append((f"symbol_{tok}", tok))
        calls.append(("eth_call", [{"to": tok, "data": sel("decimals()")}, "latest"])); tags.append((f"decimals_{tok}", tok))
res = batch(calls, "verify_batch1")
resmap = {i: r for i, r in enumerate(res)}
out["impl_code_bytes"] = (len(resmap[0].get("result", "0x"))-2)//2 if resmap[0].get("result") else None
probe = {}
for i, (tag, addr) in enumerate(tags):
    r = resmap.get(i, {})
    if tag.startswith("probe_"):
        _, idx, off = tag.split("_")
        code = r.get("result")
        probe.setdefault(idx, {})[off] = (len(code)-2)//2 if code else 0
    elif tag.startswith("symbol_") or tag.startswith("decimals_"):
        v = r.get("result")
        if v and len(v) >= 130:
            try:
                ln = int(v[130:194], 16)
                txt = bytes.fromhex(v[194:194+ln*2]).decode("utf-8", "replace") if ln < 100 else None
                out.setdefault("token_meta", {})[addr] = out.get("token_meta", {}).get(addr, {})
                out["token_meta"][addr][tag.split("_")[0]] = txt if tag.startswith("symbol") else int(v, 16)
            except Exception:
                pass
        elif tag.startswith("decimals"):
            out.setdefault("token_meta", {})[addr] = out.get("token_meta", {}).get(addr, {})
            out["token_meta"][addr]["decimals"] = int(v, 16) if v and v != "0x" else None
    else:
        out.setdefault("factory_calls", {})[tag] = r.get("result")
out["code_presence_by_offset"] = probe
save("verify_batch1.json", out)
time.sleep(0.4)

# refine creation window: find boundary offsets where code appears, then narrow
refined = {}
for idx, pmap in probe.items():
    present = sorted(int(o) for o, b in pmap.items() if b and b > 0)
    absent = sorted(int(o) for o, b in pmap.items() if not b)
    lo = max(absent) if absent else None  # code absent at lo => created after block-lo
    hi = min(present) if present else None  # code present at hi => created at/ before block-hi
    refined[idx] = {"oldest_present_offset": hi, "newest_absent_offset": lo}
out["creation_window_initial"] = refined
# second batch: bisect within [lo, hi] for each pool (5 probes each) + block timestamps at boundaries
calls2 = []; tags2 = []
for idx, w in refined.items():
    lo, hi = w["newest_absent_offset"], w["oldest_present_offset"]
    pool = [p for p in pools if str(p["index"]) == idx][0]["pool"]
    if lo is not None and hi is not None and lo - hi > 600:
        for k in range(1, 6):
            mid = hi + (lo - hi) * k // 6
            calls2.append(("eth_getCode", [pool, hex(block - mid)])); tags2.append((f"rbis_{idx}_{mid}", pool))
    if hi is not None:
        calls2.append(("eth_getBlockByNumber", [hex(block - hi), False])); tags2.append((f"ts_{idx}_{hi}", pool))
res2 = batch(calls2, "verify_batch2")
probe2 = {}
for i, (tag, _) in enumerate(tags2):
    r = res2[i]
    if tag.startswith("rbis_"):
        _, idx, mid = tag.split("_")
        code = r.get("result")
        probe2.setdefault(idx, {})[mid] = (len(code)-2)//2 if code else 0
    elif tag.startswith("ts_"):
        _, idx, off = tag.split("_")
        b = r.get("result")
        out.setdefault("block_timestamps", {})[f"{idx}_{off}"] = (
            datetime.datetime.fromtimestamp(int(b["timestamp"], 16), datetime.timezone.utc).isoformat() if b else None)
out["bisect_probes"] = probe2
for idx, pmap in probe2.items():
    present = sorted(int(o) for o, b in pmap.items() if b and b > 0)
    absent = sorted(int(o) for o, b in pmap.items() if not b)
    out.setdefault("creation_window_refined", {})[idx] = {"oldest_present_offset": min(present) if present else refined[idx]["oldest_present_offset"],
                                                          "newest_absent_offset": max(absent) if absent else refined[idx]["newest_absent_offset"]}
out["finished_at_utc"] = now()
out["requests"] = reqs
save("verify_summary.json", out)
print(json.dumps(out, ensure_ascii=False, indent=1)[:8000])
