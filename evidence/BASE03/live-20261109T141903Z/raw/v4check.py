import json, time, hashlib, datetime
import requests
from Crypto.Hash import keccak
BASE = r"D:\ds-arb-test\watch_market\evidence\BASE03\live-20261109T141903Z\raw"
PROXY = "http://127.0.0.1:7897"
RPC = "https://mainnet.base.org"
s = requests.Session(); s.trust_env = False
s.proxies = {"http": PROXY, "https": PROXY}
s.headers.update({"User-Agent": "watch_market-readonly-research/1.0", "Content-Type": "application/json"})
now = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
def sel(sig):
    h = keccak.new(digest_bits=256); h.update(sig.encode()); return "0x" + h.hexdigest()[:8]
prev = json.load(open(BASE + r"\summary.json", encoding="utf-8"))
pinned = hex(prev["pinned_block"])
POOL_ID = "0x96bdb8024ebfbc799c2c61deb7f2d3e4e9c5268a11fc62da1681b9e21515accc"
STATEVIEW = "0x7ffe42c4a5deea5b0fec41c94c136cf115597227"
POOLMANAGER = "0x498581fF718922c3f8e6A244956aF099B2652b2b"
calls = [("eth_getCode", [STATEVIEW, pinned]), ("eth_getCode", [POOLMANAGER, pinned]),
         ("eth_call", [{"to": STATEVIEW, "data": sel("getSlot0(bytes32)") + POOL_ID[2:]}, pinned]),
         ("eth_call", [{"to": STATEVIEW, "data": sel("getLiquidity(bytes32)") + POOL_ID[2:]}, pinned])]
t0 = time.time()
r = s.post(RPC, json=[{"jsonrpc": "2.0", "id": k, "method": m, "params": p} for k, (m, p) in enumerate(calls)], timeout=60)
res = r.json()
out = {"at_utc": now(), "pinned_block": prev["pinned_block"], "pool_id": POOL_ID,
       "stateview": STATEVIEW, "poolmanager": POOLMANAGER,
       "stateview_code_bytes": (len(res[0].get("result") or "0x")-2)//2,
       "poolmanager_code_bytes": (len(res[1].get("result") or "0x")-2)//2,
       "req_meta": {"http_status": r.status_code, "sha256": hashlib.sha256(r.content).hexdigest(),
                    "elapsed_s": round(time.time()-t0, 3)}}
slot0 = res[2].get("result"); liq = res[3].get("result")
if slot0 and slot0 != "0x" and len(slot0) >= 2 + 64*4:
    h = slot0[2:]
    out["slot0"] = {"sqrtPriceX96": str(int(h[0:64], 16)),
                    "tick_raw": int(h[64:128], 16),
                    "protocolFee": int(h[128:192], 16),
                    "lpFee": int(h[192:256], 16)}
    raw = int(h[64:128], 16)
    out["slot0"]["tick"] = raw - 2**256 if raw > 2**255 else raw
if liq and liq != "0x":
    out["liquidity"] = str(int(liq, 16))
# price derivation: pool = sparkUSDC (18 dec) / native ETH (18 dec); price USD unknown without ETH price
out["note"] = "V4 pool 报价为 native ETH 计价；本行只做链上池存在性/价格验证，未取得 USDC 计价的买入报价"
json.dump(out, open(BASE + r"\v4_pool_check.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1)[:3000])
