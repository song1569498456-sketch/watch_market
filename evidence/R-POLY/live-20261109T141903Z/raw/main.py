import json, time, hashlib, datetime
import requests
from Crypto.Hash import keccak
BASE = r"D:\ds-arb-test\watch_market\evidence\R-POLY\live-20261109T141903Z\raw"
PROXY = "http://127.0.0.1:7897"
RPC = "https://polygon-bor-rpc.publicnode.com"
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
CTF = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
EXV2 = "0xE111180000d2663C0091e4f400237545B87B996B"
PMCT = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
NEGRISK = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"
UMA = "0x157Ce2d672854c848c9b79c49a8cc6cc89176a49"
AAVE = "0x794a61358D6845594F94dc1DB02A252b5b4814aD"
IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
calls = [("eth_chainId", []), ("eth_blockNumber", []), ("eth_getBlockByNumber", ["latest", False]),
         ("eth_getCode", [CTF, "latest"]), ("eth_getCode", [EXV2, "latest"]),
         ("eth_getCode", [PMCT, "latest"]), ("eth_getStorageAt", [PMCT, IMPL_SLOT, "latest"]),
         ("eth_getCode", [NEGRISK, "latest"]), ("eth_getCode", [UMA, "latest"]),
         ("eth_call", [{"to": AAVE, "data": sel("getReservesList()")}, "latest"]),
         ("eth_call", [{"to": PMCT, "data": sel("symbol()")}, "latest"]),
         ("eth_call", [{"to": PMCT, "data": sel("decimals()")}, "latest"]),
         ("eth_call", [{"to": PMCT, "data": sel("totalSupply()")}, "latest"]),
         ("eth_call", [{"to": PMCT, "data": sel("underlying()")}, "latest"])]
res = batch(calls, "identity")
out["chain_id"] = int(res[0]["result"], 16)
out["latest_block"] = int(res[1]["result"], 16)
blk = res[2]["result"]
out["latest_block_time_utc"] = datetime.datetime.fromtimestamp(int(blk["timestamp"], 16), datetime.timezone.utc).isoformat()
out["pinned_block"] = out["latest_block"] - 5
def code_bytes(r): return (len(r.get("result") or "0x")-2)//2
def addr(v): return ("0x" + v[-40:]) if v and len(v) >= 66 else None
def num(v): return int(v, 16) if v and v != "0x" else None
out["contracts"] = {"CTF": {"address": CTF, "code_bytes": code_bytes(res[3])},
                    "CTF_EXCHANGE_V2": {"address": EXV2, "code_bytes": code_bytes(res[4])},
                    "PMCT": {"address": PMCT, "code_bytes": code_bytes(res[5]), "impl_slot": res[6].get("result")},
                    "NEGRISK_ADAPTER": {"address": NEGRISK, "code_bytes": code_bytes(res[7])},
                    "UMA_CTF_ADAPTER": {"address": UMA, "code_bytes": code_bytes(res[8])}}
rl = res[9].get("result")
def decode_array_addr(v):
    if not v or v == "0x": return []
    h = v[2:]; off = int(h[0:64], 16)*2; ln = int(h[off:off+64], 16); o = []
    for k in range(ln):
        st = off + 64 + k*64
        o.append("0x" + h[st:st+64][-40:])
    return o
out["aave_polygon_reserves"] = decode_array_addr(rl)
def dec_str(v):
    if not v or len(v) < 130: return None
    try:
        h = v[2:]; ln = int(h[64:128], 16)
        if ln > 100: return None
        return bytes.fromhex(h[128:128+ln*2]).decode("utf-8", "replace")
    except Exception: return None
out["pmct"] = {"symbol": dec_str(res[10].get("result")), "decimals": num(res[11].get("result")),
               "totalSupply": str(num(res[12].get("result"))), "underlying": addr(res[13].get("result"))}
save("identity.json", out)
time.sleep(0.3)
# 2) Polymarket Gamma API: sample conditionId (public, no key)
gamma = {"ok": False}
t0 = time.time()
try:
    r = s.get("https://gamma-api.polymarket.com/markets?limit=3&active=true&closed=false&order=volume24hr&ascending=false", timeout=40)
    reqs.append({"name": "gamma_markets", "url": r.url, "http_status": r.status_code, "at": now(),
                 "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(),
                 "elapsed_s": round(time.time()-t0, 3)})
    if r.status_code == 200:
        data = r.json()
        items = []
        for m in (data if isinstance(data, list) else [])[:3]:
            items.append({"question": m.get("question"), "conditionId": m.get("conditionId"),
                          "slug": m.get("slug"), "closed": m.get("closed"),
                          "outcomes": m.get("outcomes"), "outcomePrices": m.get("outcomePrices"),
                          "clobTokenIds": m.get("clobTokenIds")})
        gamma = {"ok": True, "items": items}
except Exception as e:
    gamma = {"ok": False, "error": repr(e)}
out["gamma"] = gamma
time.sleep(0.3)
# 3) CTF payout state for sample conditionId + PMCT backing
cid = None
for it in (gamma.get("items") or []):
    if it.get("conditionId"):
        cid = it["conditionId"]; break
out["sample_condition_id"] = cid
calls = []
label = []
def add(to, data, lab):
    calls.append(("eth_call", [{"to": to, "data": data}, hex(out["pinned_block"])]))
    label.append(lab)
if cid:
    cidb = cid[2:] if cid.startswith("0x") else cid
    add(CTF, sel("payoutDenominator(bytes32)") + cidb.rjust(64, "0"), "payoutDenominator")
    add(CTF, sel("getOutcomeSlotCount(bytes32)") + cidb.rjust(64, "0"), "outcomeSlotCount")
    add(CTF, sel("payoutNumerators(bytes32,uint256)") + cidb.rjust(64, "0") + hex(0)[2:].rjust(64, "0"), "payoutNumerators[0]")
    add(CTF, sel("payoutNumerators(bytes32,uint256)") + cidb.rjust(64, "0") + hex(1)[2:].rjust(64, "0"), "payoutNumerators[1]")
if calls:
    res2 = batch(calls, "ctf_state")
    out["ctf_state"] = {lab: (num(rr.get("result")) if lab != "payoutDenominator" else (str(num(rr.get("result"))) if rr.get("result") else None)) for lab, rr in zip(label, res2)}
out["finished_at_utc"] = now()
out["requests"] = reqs
out["request_count"] = len(reqs)
save("rpoly_summary.json", out)
print(json.dumps(out, ensure_ascii=False, indent=1)[:10000])
