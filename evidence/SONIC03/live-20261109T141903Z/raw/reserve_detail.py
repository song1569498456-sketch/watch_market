import json, time, hashlib, datetime
import requests
from Crypto.Hash import keccak
BASE = r"D:\ds-arb-test\watch_market\evidence\SONIC03\live-20261109T141903Z\raw"
PROXY = "http://127.0.0.1:7897"
RPC = "https://rpc.soniclabs.com"
s = requests.Session(); s.trust_env = False
s.proxies = {"http": PROXY, "https": PROXY}
s.headers.update({"User-Agent": "watch_market-readonly-research/1.0", "Content-Type": "application/json"})
now = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
def sel(sig):
    h = keccak.new(digest_bits=256); h.update(sig.encode()); return "0x" + h.hexdigest()[:8]
prev = json.load(open(BASE + r"\sonic03_summary.json", encoding="utf-8"))
pinned = hex(prev["pinned_block"])
POOL = "0x5362dBb1e601abF3a4c14c22ffEdA64042E5eAA3"
USDC = "0x29219dd400f2Bf60E5a23d13Be72B486D4038894"
WS = "0x039e2fB66102314Ce7b64Ce5Ce3E5183bc94aD38"
PROVIDER = prev.get("addresses_provider")
calls = [("eth_call", [{"to": POOL, "data": sel("getReserveData(address)") + USDC[2:].rjust(64, "0")}, pinned]),
         ("eth_call", [{"to": POOL, "data": sel("getReserveData(address)") + WS[2:].rjust(64, "0")}, pinned]),
         ("eth_call", [{"to": PROVIDER, "data": sel("getPriceOracle()")}, pinned])]
t0 = time.time()
r = s.post(RPC, json=[{"jsonrpc": "2.0", "id": k, "method": m, "params": p} for k, (m, p) in enumerate(calls)], timeout=60)
res = r.json()
out = {"at_utc": now(), "pinned_block": prev["pinned_block"],
       "req": {"http_status": r.status_code, "sha256": hashlib.sha256(r.content).hexdigest(), "elapsed_s": round(time.time()-t0, 3)}}
def words(v):
    h = v[2:]; return [h[i*64:(i+1)*64] for i in range(len(h)//64)]
def waddr(w): return "0x" + w[-40:]
def dec(v):
    w = words(v)
    cfg = int(w[0], 16)
    return {"words": len(w), "ltv_bps": cfg & 0xFFFF, "liq_threshold_bps": (cfg >> 16) & 0xFFFF,
            "liq_bonus_bps": (cfg >> 32) & 0xFFFF, "decimals": (cfg >> 48) & 0xFF,
            "active": bool((cfg >> 56) & 1), "frozen": bool((cfg >> 57) & 1),
            "borrowing_enabled": bool((cfg >> 58) & 1), "paused": bool((cfg >> 60) & 1),
            "variableBorrowRate_apr_pct": int(w[4], 16)/1e27*100,
            "aToken": waddr(w[8]), "stableDebtToken": waddr(w[9]), "variableDebtToken": waddr(w[10]),
            "interestRateStrategy": waddr(w[11])}
out["USDC_reserve"] = dec(res[0]["result"])
out["wS_reserve"] = dec(res[1]["result"])
oracle = "0x" + res[2]["result"][-40:] if res[2].get("result") else None
out["price_oracle"] = oracle
# second batch: oracle prices + aToken/vDebt totals
calls2 = [("eth_call", [{"to": oracle, "data": sel("getAssetPrice(address)") + USDC[2:].rjust(64, "0")}, pinned]),
          ("eth_call", [{"to": oracle, "data": sel("getAssetPrice(address)") + WS[2:].rjust(64, "0")}, pinned]),
          ("eth_call", [{"to": out["USDC_reserve"]["aToken"], "data": sel("totalSupply()")}, pinned]),
          ("eth_call", [{"to": out["USDC_reserve"]["variableDebtToken"], "data": sel("totalSupply()")}, pinned]),
          ("eth_call", [{"to": out["wS_reserve"]["aToken"], "data": sel("totalSupply()")}, pinned]),
          ("eth_call", [{"to": out["wS_reserve"]["variableDebtToken"], "data": sel("totalSupply()")}, pinned])]
t0 = time.time()
r2 = s.post(RPC, json=[{"jsonrpc": "2.0", "id": k, "method": m, "params": p} for k, (m, p) in enumerate(calls2)], timeout=60)
res2 = r2.json()
out["req2"] = {"http_status": r2.status_code, "sha256": hashlib.sha256(r2.content).hexdigest(), "elapsed_s": round(time.time()-t0, 3)}
def num(v): return int(v, 16) if v and v != "0x" else None
out["oracle_prices_8dec"] = {"USDC": num(res2[0].get("result")), "wS": num(res2[1].get("result"))}
out["totals"] = {"USDC_aToken": str(num(res2[2].get("result"))), "USDC_vDebt": str(num(res2[3].get("result"))),
                 "wS_aToken": str(num(res2[4].get("result"))), "wS_vDebt": str(num(res2[5].get("result")))}
out["requests"] = prev.get("requests", []) + [{"name": "reserve_detail", **out["req"]}, {"name": "oracle_totals", **out["req2"]}]
out["request_count"] = len(out["requests"])
json.dump(out, open(BASE + r"\reserve_detail.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
# merge into summary for record reuse
prev["reserve_detail"] = out
json.dump(prev, open(BASE + r"\sonic03_summary.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1)[:6000])
