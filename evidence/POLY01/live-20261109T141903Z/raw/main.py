import json, time, hashlib, datetime
import requests
from Crypto.Hash import keccak
BASE = r"D:\ds-arb-test\watch_market\evidence\POLY01\live-20261109T141903Z\raw"
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
USDCn = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
USDCe = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
USDT = "0xc2132D05D31c914a87C6611C10748AEb04B58e8F"
V3F = "0x1F98431c8aD98523631AE4a59f267346ea31F984"
QUOTER = "0x61fFE014bA17989E743c5F6cB21bF9697530B21e"
# 1) chain + token identity + quoter code + pool discovery
calls = [("eth_chainId", []), ("eth_blockNumber", []), ("eth_getBlockByNumber", ["latest", False]),
         ("eth_getCode", [QUOTER, "latest"]),
         ("eth_call", [{"to": QUOTER, "data": sel("factory()")}, "latest"]),
         ("eth_call", [{"to": QUOTER, "data": sel("WETH9()")}, "latest"])]
for t in [USDCn, USDCe, USDT]:
    calls.append(("eth_call", [{"to": t, "data": sel("symbol()")}, "latest"]))
    calls.append(("eth_call", [{"to": t, "data": sel("decimals()")}, "latest"]))
pairs = [(USDCn, USDCe, f) for f in [100, 500, 3000]] + [(USDCn, USDT, f) for f in [100, 500]] + [(USDT, USDCe, f) for f in [100, 500]]
for a, b, f in pairs:
    pool_data = sel("getPool(address,address,uint24)") + enc(a) + enc(b) + hex(f)[2:].rjust(64, "0")
    calls.append(("eth_call", [{"to": V3F, "data": pool_data}, "latest"]))
res = batch(calls, "identity_and_pools")
out["chain_id"] = int(res[0]["result"], 16)
out["latest_block"] = int(res[1]["result"], 16)
blk = res[2]["result"]
out["latest_block_time_utc"] = datetime.datetime.fromtimestamp(int(blk["timestamp"], 16), datetime.timezone.utc).isoformat()
out["pinned_block"] = out["latest_block"] - 5
pinned = hex(out["pinned_block"])
def dec_str(v):
    if not v or len(v) < 130: return None
    try:
        h = v[2:]; ln = int(h[64:128], 16)
        if ln > 100: return None
        return bytes.fromhex(h[128:128+ln*2]).decode("utf-8", "replace")
    except Exception: return None
def addr(v): return ("0x" + v[-40:]) if v and len(v) >= 66 else None
def num(v): return int(v, 16) if v and v != "0x" else None
out["quoter"] = {"address": QUOTER, "code_bytes": (len(res[3].get("result") or "0x")-2)//2,
                 "factory()": addr(res[4].get("result")), "WETH9()": addr(res[5].get("result"))}
tmeta = {}
for i, t in enumerate([USDCn, USDCe, USDT]):
    tmeta[t] = {"symbol": dec_str(res[6+i*2].get("result")), "decimals": num(res[7+i*2].get("result"))}
out["token_meta"] = tmeta
pool_map = {}
k = 12
for (a, b, f), rr in zip(pairs, res[12:]):
    pool_map[f"{a}/{b}/{f}"] = addr(rr.get("result"))
out["v3_pools"] = pool_map
save("identity.json", out)
time.sleep(0.3)
# 2) QuoterV2 closed-loop quotes (USDCn -> USDT -> USDCe -> USDCn and reverse) at pinned block
def fee_bytes(f): return f.to_bytes(3, "big")
def path_bytes(tokens, fees):
    b = bytes.fromhex(tokens[0][2:])
    for i, f in enumerate(fees):
        b += fee_bytes(f) + bytes.fromhex(tokens[i+1][2:])
    return b
def quote_data(path, amount):
    d = bytes.fromhex(sel("quoteExactInput(bytes,uint256)")[2:])
    d += (0x40).to_bytes(32, "big") + amount.to_bytes(32, "big") + len(path).to_bytes(32, "big")
    d += path + b"\x00" * ((-len(path)) % 32)
    return "0x" + d.hex()
# choose fee tiers for hops: prefer 100 then 500 if pool exists
def pick_fee(a, b):
    for f in [100, 500, 3000]:
        if pool_map.get(f"{a}/{b}/{f}") or pool_map.get(f"{b}/{a}/{f}"):
            return f
    return None
f1 = pick_fee(USDCn, USDT); f2 = pick_fee(USDT, USDCe); f3 = pick_fee(USDCe, USDCn)
out["chosen_fees"] = {"USDCn_USDT": f1, "USDT_USDCe": f2, "USDCe_USDCn": f3}
quotes = []
if f1 and f2 and f3:
    for direction in ["forward", "reverse"]:
        tokens = [USDCn, USDT, USDCe, USDCn] if direction == "forward" else [USDCn, USDCe, USDT, USDCn]
        fees = [f1, f2, f3] if direction == "forward" else [f3, f2, f1]
        path = path_bytes(tokens, fees)
        calls = [("eth_call", [{"to": QUOTER, "data": quote_data(path, amt)}, pinned]) for amt in [10**6, 10*10**6, 100*10**6, 1000*10**6]]
        res2 = batch(calls, f"quote_{direction}")
        for amt, rr in zip([10**6, 10*10**6, 100*10**6, 1000*10**6], res2):
            v = rr.get("result")
            row = {"loop": f"USDCn->{ 'USDT->USDCe' if direction=='forward' else 'USDCe->USDT' }->USDCn",
                   "amount_in_usdcn": amt/1e6, "fees": [f1, f2, f3] if direction == "forward" else [f3, f2, f1]}
            if v and v != "0x" and len(v) >= 66:
                out_raw = int(v[2:66], 16)
                row.update({"amount_out_usdcn": out_raw/1e6, "net_bps": (out_raw-amt)/amt*10000})
            else:
                row.update({"error": rr.get("error")})
            quotes.append(row)
out["quotes"] = quotes
out["fee_assumption"] = "Uniswap V3 各池 fee 由 getPool 存在的档位决定（100/500/3000），quoter 报价已含费率与价格冲击"
out["finished_at_utc"] = now()
out["requests"] = reqs
out["request_count"] = len(reqs)
save("quotes.json", out)
print(json.dumps(out, ensure_ascii=False, indent=1)[:9000])
