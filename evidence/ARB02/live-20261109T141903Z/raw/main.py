import json, time, hashlib, datetime
import requests
from Crypto.Hash import keccak
BASE = r"D:\ds-arb-test\watch_market\evidence\ARB02\live-20261109T141903Z\raw"
PROXY = "http://127.0.0.1:7897"
RPC = "https://arb1.arbitrum.io/rpc"
RPC2 = "https://arbitrum-one-rpc.publicnode.com"
s = requests.Session(); s.trust_env = False
s.proxies = {"http": PROXY, "https": PROXY}
s.headers.update({"User-Agent": "watch_market-readonly-research/1.0", "Content-Type": "application/json"})
now = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
reqs = []
def k(sig):
    h = keccak.new(digest_bits=256); h.update(sig.encode()); return h.hexdigest()
def sel(sig):
    return "0x" + k(sig)[:8]
def save(n, o):
    json.dump(o, open(BASE + "\\" + n, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
def rpc(method, params, name, rpc_url=RPC):
    t0 = time.time()
    try:
        r = s.post(rpc_url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=60)
        reqs.append({"name": name, "method": method, "rpc": rpc_url, "http_status": r.status_code, "at": now(),
                     "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(),
                     "elapsed_s": round(time.time()-t0, 3)})
        return r.json()
    except Exception as e:
        reqs.append({"name": name, "method": method, "rpc": rpc_url, "error": repr(e), "at": now()})
        return {"error": repr(e)}
def batch(calls, name, rpc_url=RPC):
    t0 = time.time()
    payload = [{"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls)]
    try:
        r = s.post(rpc_url, json=payload, timeout=60)
        reqs.append({"name": name, "rpc": rpc_url, "http_status": r.status_code, "at": now(), "n_calls": len(calls),
                     "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(),
                     "elapsed_s": round(time.time()-t0, 3)})
        d = r.json()
        if isinstance(d, dict): d = [d]
        return d
    except Exception as e:
        reqs.append({"name": name, "rpc": rpc_url, "error": repr(e), "at": now()})
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

WETH = "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1".lower()
USDC = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831".lower()
USDT = "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9".lower()
WBTC = "0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f".lower()
FACTORY = "0x1F98431c8aD98523631AE4a59f267346ea31F984"
QUOTER_V2_CANDIDATES = ["0x61fFE014bA17989E743c5F6cB21bF9697530B21e", "0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6"]
out = {"started_at_utc": now()}
# 0) official SDK addresses source (Uniswap)
r = get("https://raw.githubusercontent.com/Uniswap/sdks/main/sdks/sdk-core/src/addresses.ts", "uniswap_sdk_addresses")
if r is not None and r.status_code == 200:
    open(BASE + r"\uniswap_addresses.ts.txt", "w", encoding="utf-8").write(r.text)
    import re
    out["sdk_arbitrum_lines"] = [ln.strip() for ln in r.text.splitlines() if "42161" in ln or "ARBITRUM" in ln][:10]
    out["sdk_quoter_lines"] = [ln.strip() for ln in r.text.splitlines() if "QUOTER" in ln.upper()][:12]
    for cand in QUOTER_V2_CANDIDATES:
        out.setdefault("sdk_contains_candidate", {})[cand] = (cand[2:].lower() in r.text.lower())
time.sleep(0.4)
# 1) chain identity
j = rpc("eth_chainId", [], "chain_id"); out["chain_id"] = int(j["result"], 16) if j.get("result") else None
j = rpc("eth_blockNumber", [], "block_number"); block = int(j["result"], 16) if j.get("result") else None
j = rpc("eth_getBlockByNumber", ["latest", False], "latest_block"); blk = j.get("result") or {}
out["latest_block"] = block
out["latest_block_time_utc"] = datetime.datetime.fromtimestamp(int(blk["timestamp"], 16), datetime.timezone.utc).isoformat() if blk.get("timestamp") else None
out["base_fee_wei"] = blk.get("baseFeePerGas")
out["pinned_block"] = block - 10 if block else None
time.sleep(0.4)
# 2) code presence: quoters, factory, tokens
addrs = QUOTER_V2_CANDIDATES + [FACTORY, WETH, USDC, USDT, WBTC]
j = rpc("eth_getCode", [QUOTER_V2_CANDIDATES[0], "latest"], "code_quoter_primary"); out["quoter_primary_code_bytes"] = (len(j.get("result", "0x"))-2)//2 if j.get("result") else None
res = batch([("eth_getCode", [QUOTER_V2_CANDIDATES[1], "latest"]), ("eth_getCode", [FACTORY, "latest"])] +
            [("eth_getCode", [t, "latest"]) for t in [WETH, USDC, USDT, WBTC]], "codes_and_pools")
codes = {}
for i, a in enumerate([QUOTER_V2_CANDIDATES[1], FACTORY, WETH, USDC, USDT, WBTC]):
    codes[a] = (len((res[i].get("result") or "0x"))-2)//2
out["code_bytes"] = codes
time.sleep(0.4)
# 3) factory.getPool for triangle pool legs (pinned block)
def enc_addr(a): return a[2:].rjust(64, "0")
def enc_uint(n): return hex(n)[2:].rjust(64, "0")
def getpool_data(a, b, fee):
    return sel("getPool(address,address,uint24)") + enc_addr(a) + enc_addr(b) + enc_uint(fee)
pairs = [
    ("WETH/USDC", WETH, USDC, 500), ("USDC/USDT", USDC, USDT, 100), ("USDT/WETH", USDT, WETH, 500),
    ("WETH/USDC_3k", WETH, USDC, 3000), ("USDC/WBTC", USDC, WBTC, 3000), ("WBTC/WETH", WBTC, WETH, 3000),
    ("USDC/USDT_1", USDC, USDT, 1), ("WETH/USDT_3k", WETH, USDT, 3000),
]
pinned = hex(out["pinned_block"]) if out.get("pinned_block") else "latest"
calls = [("eth_call", [{"to": FACTORY, "data": getpool_data(a, b, fee)}, pinned]) for _, a, b, fee in pairs]
res = batch(calls, "factory_getpool")
pools = {}
for (name, a, b, fee), rr in zip(pairs, res):
    v = rr.get("result")
    pools[name] = {"tokenA": a, "tokenB": b, "fee": fee,
                   "pool": ("0x" + v[-40:]) if v and len(v) >= 66 and int(v, 16) != 0 else None}
out["pools"] = pools
time.sleep(0.4)
# 4) token symbols/decimals
calls = []
for t in [WETH, USDC, USDT, WBTC]:
    calls.append(("eth_call", [{"to": t, "data": sel("symbol()")}, pinned]))
    calls.append(("eth_call", [{"to": t, "data": sel("decimals()")}, pinned]))
res = batch(calls, "token_meta")
tmeta = {}
for i, t in enumerate([WETH, USDC, USDT, WBTC]):
    sv = res[i*2].get("result"); dv = res[i*2+1].get("result")
    sym = None
    if sv and len(sv) >= 130:
        try:
            ln = int(sv[66:130], 16)
            if ln < 100: sym = bytes.fromhex(sv[130:130+ln*2]).decode("utf-8", "replace")
        except Exception: pass
    tmeta[t] = {"symbol": sym, "decimals": int(dv, 16) if dv and dv != "0x" else None}
out["token_meta"] = tmeta
time.sleep(0.4)
# 5) QuoterV2 quoteExactInput for closed triangles (pinned block)
def addr_bytes(a): return bytes.fromhex(a[2:])
def fee_bytes(f): return f.to_bytes(3, "big")
def path_bytes(tokens_fees):
    b = b""
    for i, (tok, fee) in enumerate(tokens_fees):
        if i == 0: b += addr_bytes(tok)
        b += fee_bytes(fee) + addr_bytes(tokens_fees[i+1][0]) if False else b""
    return b
def encode_path(tokens, fees):
    b = addr_bytes(tokens[0])
    for i, fee in enumerate(fees):
        b += fee_bytes(fee) + addr_bytes(tokens[i+1])
    return b
def encode_quote_path(path):
    data = bytes.fromhex(sel("quoteExactInput(bytes,uint256)")[2:])
    data += (0x40).to_bytes(32, "big")   # offset to bytes
    return data
def quote_data(path, amount):
    d = bytes.fromhex(sel("quoteExactInput(bytes,uint256)")[2:])
    d += (0x40).to_bytes(32, "big")
    d += amount.to_bytes(32, "big")
    d += len(path).to_bytes(32, "big")
    pad = (-len(path)) % 32
    d += path + b"\x00" * pad
    return "0x" + d.hex()
triangles = {
    "T1_WETH_USDC_USDT": {"tokens": [WETH, USDC, USDT, WETH], "fees": [500, 100, 500]},
    "T2_WETH_USDC_WBTC": {"tokens": [WETH, USDC, WBTC, WETH], "fees": [500, 3000, 3000]},
    "T3_USDC_USDT_WETH": {"tokens": [USDC, USDT, WETH, USDC], "fees": [100, 500, 500]},
}
WETH_RAW = 10**18; USDC_RAW = 10**6
amounts = {"T1_WETH_USDC_USDT": [WETH_RAW // 10, WETH_RAW, 10*WETH_RAW, 50*WETH_RAW],
           "T2_WETH_USDC_WBTC": [WETH_RAW // 10, WETH_RAW, 10*WETH_RAW, 50*WETH_RAW],
           "T3_USDC_USDT_WETH": [USDC_RAW, 10*USDC_RAW, 1000*USDC_RAW, 10000*USDC_RAW]}
calls = []; tags = []
quoter = QUOTER_V2_CANDIDATES[0]
for tname, tdef in triangles.items():
    path = encode_path(tdef["tokens"], tdef["fees"])
    tdef["path_hex"] = "0x" + path.hex()
    for amt in amounts[tname]:
        calls.append(("eth_call", [{"to": quoter, "data": quote_data(path, amt)}, pinned]))
        tags.append((tname, amt))
res = batch(calls, "quoter_quotes")
quotes = []
for (tname, amt), rr in zip(tags, res):
    v = rr.get("result")
    row = {"triangle": tname, "amount_in_raw": str(amt), "error": rr.get("error")}
    if v and v != "0x":
        words = [v[2 + i*64: 2 + (i+1)*64] for i in range(len(v)//64)]
        row["amount_out_raw"] = str(int(words[0], 16))
        row["amount_out_dec"] = str(int(words[0], 16) / 10**18) if tname != "T3_USDC_USDT_WETH" else str(int(words[0], 16) / 10**6)
        row["gas_estimate"] = int(words[-1], 16) if words else None
        row["status"] = "quoted"
    else:
        row["status"] = "error_or_revert"
    row["amount_in_dec"] = str(amt / (10**18 if tname != "T3_USDC_USDT_WETH" else 10**6))
    quotes.append(row)
out["quotes"] = quotes
save("arb02_summary.json", out)
print(json.dumps({"chain_id": out.get("chain_id"), "latest_block": out.get("latest_block"),
    "latest_block_time_utc": out.get("latest_block_time_utc"), "pinned_block": out.get("pinned_block"),
    "quoter_primary_code_bytes": out.get("quoter_primary_code_bytes"), "code_bytes": out.get("code_bytes"),
    "token_meta": out.get("token_meta"), "pools": out.get("pools"), "quotes": out.get("quotes"),
    "sdk_quoter_lines": out.get("sdk_quoter_lines"), "request_count": len(reqs), "requests": reqs},
    ensure_ascii=False, indent=1)[:14000])
