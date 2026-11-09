import json, time, hashlib, datetime
import requests
from Crypto.Hash import keccak
BASE = r"D:\ds-arb-test\watch_market\evidence\ETH05\live-20261109T141903Z\raw"
PROXY = "http://127.0.0.1:7897"
RPC = "https://ethereum-rpc.publicnode.com"
s = requests.Session(); s.trust_env = False
s.proxies = {"http": PROXY, "https": PROXY}
s.headers.update({"User-Agent": "watch_market-readonly-research/1.0", "Content-Type": "application/json"})
now = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
reqs = []
def sel(sig):
    h = keccak.new(digest_bits=256); h.update(sig.encode()); return "0x" + h.hexdigest()[:8]
def save(n, o):
    json.dump(o, open(BASE + "\\" + n, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
def batch(calls, name, pinned="latest"):
    t0 = time.time()
    r = s.post(RPC, json=[{"jsonrpc": "2.0", "id": k, "method": m, "params": p} for k, (m, p) in enumerate(calls)], timeout=60)
    reqs.append({"name": name, "http_status": r.status_code, "at": now(), "n_calls": len(calls),
                 "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(),
                 "elapsed_s": round(time.time()-t0, 3)})
    d = r.json()
    if isinstance(d, dict): d = [d]
    return d
out = {"started_at_utc": now()}
# 1) chain identity
res = batch([("eth_chainId", []), ("eth_blockNumber", []), ("eth_getBlockByNumber", ["latest", False])], "chain_identity")
out["chain_id"] = int(res[0]["result"], 16)
out["latest_block"] = int(res[1]["result"], 16)
blk = res[2]["result"]
out["latest_block_time_utc"] = datetime.datetime.fromtimestamp(int(blk["timestamp"], 16), datetime.timezone.utc).isoformat()
out["pinned_block"] = out["latest_block"] - 5
pinned = hex(out["pinned_block"])
time.sleep(0.3)
# 2) Lido WithdrawalQueue reads (proxy address from ETH01 verified)
QUEUE = "0x889edC2eDab5f40e902b864aD4d7AdE8E412F9B1"
res = batch([("eth_getCode", [QUEUE, pinned]),
             ("eth_call", [{"to": QUEUE, "data": sel("getLastRequestId()")}, pinned]),
             ("eth_call", [{"to": QUEUE, "data": sel("getLastFinalizedRequestId()")}, pinned]),
             ("eth_call", [{"to": QUEUE, "data": sel("unfinalizedStETH()")}, pinned]),
             ("eth_call", [{"to": QUEUE, "data": sel("isPaused()")}, pinned]),
             ("eth_call", [{"to": QUEUE, "data": sel("getWithdrawalStatus(uint256[])") + hex(0x20)[2:].rjust(64, "0") + hex(2)[2:].rjust(64, "0") + hex(1)[2:].rjust(64, "0") + hex(2)[2:].rjust(64, "0")}, pinned])],
            "lido_queue", pinned)
out["queue_code_bytes"] = (len(res[0].get("result") or "0x")-2)//2
def num(v): return int(v, 16) if v and v != "0x" else None
out["last_request_id"] = num(res[1].get("result"))
out["last_finalized_request_id"] = num(res[2].get("result"))
out["unfinalized_stETH_wei"] = num(res[3].get("result"))
out["unfinalized_stETH"] = (num(res[3].get("result")) / 1e18) if num(res[3].get("result")) is not None else None
out["isPaused"] = bool(num(res[4].get("result"))) if num(res[4].get("result")) is not None else None
# decode getWithdrawalStatus tuple of arrays
raw = res[5].get("result")
status = {}
if raw and raw != "0x":
    h = raw[2:]
    out["status_raw"] = raw[:400]
    try:
        words = [h[i*64:(i+1)*64] for i in range(len(h)//64)]
        offsets = [int(w, 16) for w in words[:7]]
        def arr(off, kind):
            base = off*2
            if base + 64 > len(h): return []
            ln = int(h[base:base+64], 16)
            items = []
            for k in range(ln):
                start = base + 64 + k*64
                if start + 64 > len(h): break
                w = h[start:start+64]
                if kind == "bool": items.append(bool(int(w, 16)))
                elif kind == "addr": items.append("0x" + w[-40:])
                else: items.append(int(w, 16))
            return items
        status = {"offsets": offsets,
                  "isFinalized": arr(offsets[0], "bool"), "isClaimed": arr(offsets[1], "bool"),
                  "amountOfStETH": arr(offsets[2], "num"), "amountOfShares": arr(offsets[3], "num"),
                  "owner": arr(offsets[4], "addr"), "timestamp": arr(offsets[5], "num"),
                  "claimableEther": arr(offsets[6], "num")}
    except Exception as e:
        status = {"decode_error": repr(e)}
out["status_requests"] = {"ids": [1, 2], "decoded": status}
# ownerOf for latest finalized + latest unfinalized request
ids = []
if out.get("last_finalized_request_id"):
    ids.append(out["last_finalized_request_id"])
if out.get("last_request_id"):
    ids.append(out["last_request_id"])
res2 = batch([("eth_call", [{"to": QUEUE, "data": sel("ownerOf(uint256)") + hex(i)[2:].rjust(64, "0")}, pinned]) for i in ids],
             "lido_ownerOf", pinned)
out["ownerOf"] = {str(i): (("0x" + r["result"][-40:]) if r.get("result") and len(r["result"]) >= 66 else r.get("error")) for i, r in zip(ids, res2)}
save("lido_queue.json", out)
time.sleep(0.3)
# 3) NFT secondary market discovery for unstETH (ERC721) — DexScreener (likely none)
t0 = time.time()
r = s.get(f"https://api.dexscreener.com/latest/dex/tokens/{QUEUE}", timeout=40)
reqs.append({"name": "dexscreener_unsteth", "url": r.url, "http_status": r.status_code, "at": now(),
             "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(),
             "elapsed_s": round(time.time()-t0, 3)})
pairs = []
if r.status_code == 200:
    for p in (r.json().get("pairs") or []):
        if p.get("chainId") == "ethereum":
            pairs.append({"pair": p.get("pairAddress"), "dexId": p.get("dexId"), "liquidityUsd": (p.get("liquidity") or {}).get("usd")})
out["unsteth_dexscreener_pairs"] = pairs
time.sleep(0.3)
# 4) second mechanism: Uniswap V3 NonfungiblePositionManager identity (NFT position burn/collect)
NPM = "0xC36442b4a4522E871399CD717aBDD847Ab11FE88"
res = batch([("eth_getCode", [NPM, pinned]),
             ("eth_call", [{"to": NPM, "data": sel("factory()")}, pinned]),
             ("eth_call", [{"to": NPM, "data": sel("WETH9()")}, pinned]),
             ("eth_call", [{"to": NPM, "data": sel("name()")}, pinned]),
             ("eth_call", [{"to": NPM, "data": sel("symbol()")}, pinned])], "npm_identity", pinned)
def dec_str(v):
    if not v or len(v) < 130: return None
    try:
        h = v[2:]; ln = int(h[64:128], 16)
        if ln > 100: return None
        return bytes.fromhex(h[128:128+ln*2]).decode("utf-8", "replace")
    except Exception: return None
def addr(v): return ("0x" + v[-40:]) if v and len(v) >= 66 else None
out["npm"] = {"code_bytes": (len(res[0].get("result") or "0x")-2)//2,
              "factory()": addr(res[1].get("result")), "WETH9()": addr(res[2].get("result")),
              "name": dec_str(res[3].get("result")), "symbol": dec_str(res[4].get("result"))}
out["finished_at_utc"] = now()
out["requests"] = reqs
out["request_count"] = len(reqs)
save("eth05_summary.json", out)
print(json.dumps(out, ensure_ascii=False, indent=1)[:9000])
