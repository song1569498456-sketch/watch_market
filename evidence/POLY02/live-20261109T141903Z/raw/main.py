import json, time, hashlib, datetime
import requests
from Crypto.Hash import keccak
BASE = r"D:\ds-arb-test\watch_market\evidence\POLY02\live-20261109T141903Z\raw"
PROXY = "http://127.0.0.1:7897"
RPC = "https://polygon-bor-rpc.publicnode.com"
s = requests.Session(); s.trust_env = False
s.proxies = {"http": PROXY, "https": PROXY}
s.headers.update({"User-Agent": "watch_market-readonly-research/1.0", "Content-Type": "application/json"})
now = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
reqs = []
def sel(sig):
    h = keccak.new(digest_bits=256); h.update(sig.encode()); return "0x" + h.hexdigest()[:8]
def topic(sig):
    h = keccak.new(digest_bits=256); h.update(sig.encode()); return "0x" + h.hexdigest()
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
POOL = "0x794a61358D6845594F94dc1DB02A252b5b4814aD"
ORACLE = "0xb023e699F5a33916Ea823A16485e259257cA8Bd1"
USDCn = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
WMATIC = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270"
IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
# 1) chain + pool identity + reserves list + oracle prices + reserve data
calls = [("eth_chainId", []), ("eth_blockNumber", []), ("eth_getBlockByNumber", ["latest", False]),
         ("eth_getCode", [POOL, "latest"]),
         ("eth_getStorageAt", [POOL, IMPL_SLOT, "latest"]),
         ("eth_call", [{"to": POOL, "data": sel("getReservesList()")}, "latest"]),
         ("eth_getCode", [ORACLE, "latest"]),
         ("eth_call", [{"to": ORACLE, "data": sel("getAssetPrice(address)") + enc(USDCn)}, "latest"]),
         ("eth_call", [{"to": ORACLE, "data": sel("getAssetPrice(address)") + enc(WMATIC)}, "latest"]),
         ("eth_call", [{"to": POOL, "data": sel("getReserveData(address)") + enc(USDCn)}, "latest"]),
         ("eth_call", [{"to": POOL, "data": sel("getReserveData(address)") + enc(WMATIC)}, "latest"])]
res = batch(calls, "pool_identity_and_reserves")
out["chain_id"] = int(res[0]["result"], 16)
out["latest_block"] = int(res[1]["result"], 16)
blk = res[2]["result"]
out["latest_block_time_utc"] = datetime.datetime.fromtimestamp(int(blk["timestamp"], 16), datetime.timezone.utc).isoformat()
out["pinned_block"] = out["latest_block"] - 5
out["pool_code_bytes"] = (len(res[3].get("result") or "0x")-2)//2
impl = res[4].get("result")
out["pool_impl_slot_value"] = impl
out["pool_impl"] = ("0x" + impl[-40:]) if impl and len(impl) >= 66 else None
rl = res[5].get("result")
def decode_array_addr(v):
    if not v or v == "0x": return []
    h = v[2:]; off = int(h[0:64], 16)*2; ln = int(h[off:off+64], 16)
    outl = []
    for k in range(ln):
        st = off + 64 + k*64
        outl.append("0x" + h[st:st+64][-40:])
    return outl
out["reserves_list"] = decode_array_addr(rl)
out["oracle_code_bytes"] = (len(res[6].get("result") or "0x")-2)//2
def num(v): return int(v, 16) if v and v != "0x" else None
out["oracle_prices"] = {"USDCn": num(res[7].get("result")), "WMATIC": num(res[8].get("result"))}
def decode_reserve(v):
    if not v or v == "0x": return None
    h = v[2:]
    words = [h[i*64:(i+1)*64] for i in range(len(h)//64)]
    if len(words) < 15: return {"raw_words": len(words)}
    cfg = int(words[0], 16)
    d = {"configuration": hex(cfg),
         "ltv_bps": cfg & 0xFFFF, "liquidation_threshold_bps": (cfg >> 16) & 0xFFFF,
         "liquidation_bonus_bps": (cfg >> 32) & 0xFFFF, "decimals": (cfg >> 48) & 0xFF,
         "active": bool((cfg >> 56) & 1), "frozen": bool((cfg >> 57) & 1),
         "borrowingEnabled": bool((cfg >> 58) & 1), "paused": bool((cfg >> 60) & 1),
         "lastUpdateTimestamp": int(words[6], 16), "id": int(words[7], 16),
         "aToken": "0x" + words[8][-40:], "stableDebtToken": "0x" + words[9][-40:],
         "variableDebtToken": "0x" + words[10][-40:], "interestRateStrategy": "0x" + words[11][-40:]}
    return d
out["reserve_USDCn"] = decode_reserve(res[9].get("result"))
out["reserve_WMATIC"] = decode_reserve(res[10].get("result"))
save("pool_identity.json", out)
time.sleep(0.3)
# 2) scan LiquidationCall events in window (start 5000 blocks, expand to 50000 if allowed)
TOPIC = topic("LiquidationCall(address,address,address,uint256,uint256,address,bool)")
out["liquidation_topic0"] = TOPIC
scans = []
events = []
for span in [5000, 50000]:
    frm = max(0, out["latest_block"] - span)
    res2 = batch([("eth_getLogs", [{"address": POOL, "fromBlock": hex(frm), "toBlock": hex(out["latest_block"]), "topics": [TOPIC]}])], f"getlogs_liq_{span}")
    lg = res2[0] if res2 else {}
    scans.append({"span_blocks": span, "range": [frm, out["latest_block"]], "error": lg.get("error"), "count": len(lg.get("result") or [])})
    if lg.get("result"):
        events = lg["result"]
        break
    time.sleep(0.3)
out["liquidation_scans"] = scans
decoded = []
for e in events[:10]:
    t = e.get("topics", []); data = e.get("data", "0x")
    if len(t) >= 4 and len(data) >= 2 + 64*3:
        h = data[2:]
        decoded.append({"block": int(e["blockNumber"], 16), "tx": e.get("transactionHash"),
                        "collateralAsset": "0x" + t[1][-40:], "debtAsset": "0x" + t[2][-40:], "user": "0x" + t[3][-40:],
                        "debtToCover": int(h[0:64], 16), "liquidatedCollateralAmount": int(h[64:128], 16),
                        "liquidator": "0x" + h[128:192][-40:] if len(h) >= 192 else None})
out["liquidations_decoded"] = decoded
if events:
    blocks = sorted({int(e["blockNumber"], 16) for e in events[:3]})
    res3 = batch([("eth_getBlockByNumber", [hex(b), False]) for b in blocks], "event_block_times")
    out["event_block_times"] = {str(b): (datetime.datetime.fromtimestamp(int(r.get("result", {}).get("timestamp", "0x0"), 16), datetime.timezone.utc).isoformat() if r.get("result") else None) for b, r in zip(blocks, res3)}
out["finished_at_utc"] = now()
out["requests"] = reqs
out["request_count"] = len(reqs)
save("poly02_summary.json", out)
print(json.dumps(out, ensure_ascii=False, indent=1)[:10000])
