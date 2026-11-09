import json, time, hashlib, datetime, re
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
        reqs.append({"name": name, "url": url, "http_status": r.status_code, "at": now(), "bytes": len(r.content),
                     "sha256": hashlib.sha256(r.content).hexdigest(), "elapsed_s": round(time.time()-t0, 3)})
        return r
    except Exception as e:
        reqs.append({"name": name, "url": url, "error": repr(e), "at": now()})
        return None

V21 = "0x8e42f2F4101563bF679975178e880FD87d3eFd4e"
prev = json.load(open(BASE + r"\avax_summary.json", encoding="utf-8"))
block = prev["latest_block"]
topic0 = "0x" + keccak.new(digest_bits=256, data=b"LBPairCreated(address,address,uint256,address,uint256)").hexdigest()
out = {"started_at_utc": now(), "latest_block_reference": block}
# 1) 7-day event window attempt: 302400 blocks at 2s
fromb = max(0, block - 302400)
res = batch([("eth_getLogs", [{"address": V21, "fromBlock": hex(fromb), "toBlock": hex(block), "topics": [topic0]}])],
            "getlogs_v21_7d", fallback=True)
lg = res[0] if res else {}
ev = lg.get("result") or []
out["getlogs_v21_7d"] = {"range": [fromb, block], "error": lg.get("error"), "count": len(ev)}
out["events_7d"] = [{"block": int(x["blockNumber"], 16), "tx": x.get("transactionHash"),
                     "topics": x.get("topics"), "data": x.get("data")} for x in ev[:20]]
# event decoding: topics[1]=tokenX, [2]=tokenY, [3]=binStep, data[0:32]=pair, [32:64]=pid
decoded = []
for e in ev[:20]:
    t = e.get("topics", [])
    if len(t) >= 4 and len(e.get("data", "0x")) >= 2 + 128:
        decoded.append({"block": int(e["blockNumber"], 16),
                        "tokenX": "0x" + t[1][-40:], "tokenY": "0x" + t[2][-40:],
                        "binStep": int(t[3], 16), "pair": "0x" + e["data"][2:66][-40:],
                        "pid": int(e["data"][66:130], 16),
                        "tx": e.get("transactionHash")})
out["events_7d_decoded"] = decoded
if ev:
    # block timestamps for first and last event
    calls = [("eth_getBlockByNumber", [ev[0]["blockNumber"], False]), ("eth_getBlockByNumber", [ev[-1]["blockNumber"], False])]
    res = batch(calls, "event_block_times")
    out["event_block_times_utc"] = [datetime.datetime.fromtimestamp(int(r.get("result", {}).get("timestamp", "0x0"), 16), datetime.timezone.utc).isoformat()
                                    for r in res if r.get("result")]
time.sleep(0.4)
# 2) avalanchego releases feed (atom, no key)
r = get("https://github.com/ava-labs/avalanchego/releases.atom", "avalanchego_atom")
if r is not None and r.status_code == 200:
    txt = r.text
    titles = re.findall(r"<title>([^<]+)</title>", txt)[:12]
    dates = re.findall(r"<updated>([^<]+)</updated>", txt)[:12]
    out["avalanchego_atom_titles"] = titles
    out["avalanchego_atom_updated"] = dates
    open(BASE + r"\avalanchego_releases.atom.xml", "w", encoding="utf-8").write(txt[:20000])
time.sleep(0.4)
# 3) joe-v2 releases atom too
r = get("https://github.com/traderjoe-xyz/joe-v2/releases.atom", "joev2_atom")
if r is not None and r.status_code == 200:
    txt = r.text
    out["joev2_atom_titles"] = re.findall(r"<title>([^<]+)</title>", txt)[:12]
    out["joev2_atom_updated"] = re.findall(r"<updated>([^<]+)</updated>", txt)[:12]
out["finished_at_utc"] = now()
out["requests"] = reqs
out["request_count"] = len(reqs)
json.dump(out, open(BASE + r"\avax_round3.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1)[:7000])
