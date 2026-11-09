import json, time, re, hashlib, base64, datetime, struct
from decimal import Decimal, getcontext
import requests
getcontext().prec = 60
BASE = r"D:\ds-arb-test\watch_market\evidence\SOL01\live-20261109T141903Z\raw"
PROXY = "http://127.0.0.1:7897"
RPC = "https://api.mainnet-beta.solana.com"
s = requests.Session(); s.trust_env = False
s.proxies = {"http": PROXY, "https": PROXY}
s.headers.update({"User-Agent": "watch_market-readonly-research/1.0"})
now = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
reqs = []
def get(url, name):
    t0 = time.time()
    try:
        r = s.get(url, timeout=30)
        reqs.append({"url": url, "name": name, "http_status": r.status_code, "at": now(),
                     "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(),
                     "elapsed_s": round(time.time()-t0, 3)})
        return r
    except Exception as e:
        reqs.append({"url": url, "name": name, "error": repr(e), "at": now()})
        return None

def save(name, obj):
    json.dump(obj, open(BASE + "\\" + name, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

out = {"started_at_utc": now()}
AMM_V4 = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
AMM_POOL = "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2"
ORCA_PROG = "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc"
ORCA_POOL = "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE"
WSOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# 1) official Raydium AMM v4 pool layout source (try 2 paths max)
layout_txt = None
for path in ["src/raydium/liquidity/layout.ts", "src/raydium/liquidity/layout.ts".replace("liquidity", "amm")]:
    r = get("https://raw.githubusercontent.com/raydium-io/raydium-sdk-V2/master/" + path, "raydium_amm_layout_" + path.split("/")[-2])
    if r is not None and r.status_code == 200 and "struct" in r.text:
        layout_txt = r.text
        out["layout_url"] = str(r.url)
        open(BASE + r"\raydium_amm_layout.ts.txt", "w", encoding="utf-8").write(r.text)
        break
    time.sleep(0.4)
SIZES = {"u8": 1, "bool": 1, "u16": 2, "i16": 2, "u32": 4, "i32": 4, "f32": 4, "u64": 8, "i64": 8,
         "u128": 16, "i128": 16, "publicKey": 32, "f64": 8}
fields = []
if layout_txt:
    m = re.search(r"export const LIQUIDITY_STATE_LAYOUT_V4[^=]*=\s*struct\(\[(.*?)\]\)", layout_txt, re.S)
    if m:
        body = m.group(1)
        for fm in re.finditer(r"(\w+)\(\s*['\"](\w+)['\"]\s*\)", body):
            typ, name = fm.group(1), fm.group(2)
            fields.append((name, SIZES.get(typ, 8), typ))
out["layout_fields"] = [(n, sz) for n, sz, t in fields]
off = 0; offs = {}
for n, sz, t in fields:
    offs[n] = off; off += sz
out["layout_total"] = off
out["offsets_of_interest"] = {k: offs.get(k) for k in ["status", "swapFeeNumerator", "swapFeeDenominator", "baseVault", "quoteVault", "baseMint", "quoteMint", "poolOpenTime", "state", "baseDecimal", "quoteDecimal"]}

# 2) RPC: read both pool states + vault balances + mints in ONE getMultipleAccounts (same slot)
base64v = None; amm_data = None; orca_data = None; mint_info = {}
if fields:
    # first read AMM pool state to get vault addresses (1 request)
    t0 = time.time()
    r = s.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": "getAccountInfo",
                          "params": [AMM_POOL, {"encoding": "base64", "commitment": "finalized"}]}, timeout=30)
    j = r.json()
    reqs.append({"url": RPC, "name": "rpc_amm_pool_state", "http_status": r.status_code, "at": now(),
                 "sha256": hashlib.sha256(r.content).hexdigest(), "elapsed_s": round(time.time()-t0, 3)})
    amm_data = base64.b64decode(j["result"]["value"]["data"][0])
    slot0 = j["result"]["context"]["slot"]
    out["amm_state_read"] = {"slot": slot0, "bytes": len(amm_data), "owner": j["result"]["value"]["owner"]}
    def u64(n): return struct.unpack("<Q", amm_data[offs[n]:offs[n]+8])[0]
    # base58 pubkeys
    B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    def b58(b):
        n = int.from_bytes(b, "big"); o = ""
        while n:
            n, rr = divmod(n, 58); o = B58[rr] + o
        pad = 0
        for x in b:
            if x == 0: pad += 1
            else: break
        return "1" * pad + o
    pk = lambda n: b58(amm_data[offs[n]:offs[n]+32])
    info = {"status": u64("status"), "state": u64("state"), "poolOpenTime": u64("poolOpenTime"),
            "swapFeeNumerator": u64("swapFeeNumerator"), "swapFeeDenominator": u64("swapFeeDenominator"),
            "baseDecimal": u64("baseDecimal"), "quoteDecimal": u64("quoteDecimal"),
            "baseVault": pk("baseVault"), "quoteVault": pk("quoteVault"),
            "baseMint": pk("baseMint"), "quoteMint": pk("quoteMint")}
    out["amm_state"] = info
    time.sleep(0.5)
    # 3) same-slot read: AMM pool, both AMM vaults, Orca pool, and both mints
    addrs = [AMM_POOL, info["baseVault"], info["quoteVault"], ORCA_POOL, WSOL, USDC]
    t0 = time.time()
    r = s.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": "getMultipleAccounts",
                          "params": [addrs, {"encoding": "base64", "commitment": "finalized"}]}, timeout=30)
    j = r.json(); reqs.append({"url": RPC, "name": "rpc_same_slot_state", "http_status": r.status_code, "at": now(),
                               "sha256": hashlib.sha256(r.content).hexdigest(), "elapsed_s": round(time.time()-t0, 3)})
    vals = j["result"]["value"]; slot = j["result"]["context"]["slot"]
    out["same_slot_read"] = {"slot": slot, "accounts": addrs}
    # decode vault balances (SPL token account: amount u64 at 64)
    def tok_amount(v):
        d = base64.b64decode(v["data"][0]); return {"mint": b58(d[0:32]), "owner_authority": b58(d[32:64]),
                                                    "amount": struct.unpack("<Q", d[64:72])[0], "bytes": len(d)}
    out["amm_vaults"] = {"base": tok_amount(vals[1]), "quote": tok_amount(vals[2])}
    mint_info = {"WSOL": {"owner": vals[4]["owner"], "decimals": base64.b64decode(vals[4]["data"][0])[44]},
                 "USDC": {"owner": vals[5]["owner"], "decimals": base64.b64decode(vals[5]["data"][0])[44]}}
    out["mints"] = mint_info
    orca_data = base64.b64decode(vals[3]["data"][0])
    # Orca Whirlpool layout (known offsets)
    o = {"whirlpools_config": b58(orca_data[8:40]), "tick_spacing": struct.unpack("<H", orca_data[41:43])[0],
         "fee_rate": struct.unpack("<H", orca_data[45:47])[0], "protocol_fee_rate": struct.unpack("<H", orca_data[47:49])[0],
         "liquidity": int.from_bytes(orca_data[49:65], "little"), "sqrt_price": int.from_bytes(orca_data[65:81], "little"),
         "tick_current": struct.unpack("<i", orca_data[81:85])[0],
         "mint_a": b58(orca_data[101:133]), "vault_a": b58(orca_data[133:165]),
         "mint_b": b58(orca_data[181:213]), "vault_b": b58(orca_data[213:245])}
    out["orca_state"] = {k: (str(v) if isinstance(v, int) and v > 2**53 else v) for k, v in o.items()}
    out["orca_state_bytes"] = len(orca_data)
    out["orca_owner"] = vals[3]["owner"]
    # sanity: same mints / token program
    out["identity_check"] = {
        "amm_baseMint_is_WSOL": info["baseMint"] == WSOL, "amm_quoteMint_is_USDC": info["quoteMint"] == USDC,
        "orca_mint_a_is_WSOL": o["mint_a"] == WSOL, "orca_mint_b_is_USDC": o["mint_b"] == USDC,
        "orca_mints_token_program": mint_info, "orca_owner_is_whirlpool_prog": vals[3]["owner"] == ORCA_PROG}
    out["data"] = {"amm": info, "orca": o, "vaults": out["amm_vaults"],
                   "slot": slot, "read_at_utc": now()}
save("state_read.json", out)
print(json.dumps({k: out.get(k) for k in ["layout_url", "layout_total", "offsets_of_interest", "amm_state_read",
    "amm_state", "same_slot_read", "amm_vaults", "mints", "orca_state", "orca_owner", "identity_check", "requests"]},
    ensure_ascii=False, indent=1)[:9000])
