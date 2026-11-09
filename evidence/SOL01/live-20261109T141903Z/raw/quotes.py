import json, time, re, hashlib, base64, datetime, struct, math
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

def rpc_call(method, params, name):
    t0 = time.time()
    r = s.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=30)
    j = r.json()
    reqs.append({"url": RPC, "method": method, "name": name, "http_status": r.status_code, "at": now(),
                 "sha256": hashlib.sha256(r.content).hexdigest(), "elapsed_s": round(time.time()-t0, 3)})
    return j

def save(name, obj):
    json.dump(obj, open(BASE + "\\" + name, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

W = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
def b58(b):
    n = int.from_bytes(b, "big"); o = ""
    while n:
        n, r = divmod(n, 58); o = W[r] + o
    pad = 0
    for x in b:
        if x == 0: pad += 1
        else: break
    return "1" * pad + o

AMM_POOL = "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2"
ORCA_PROG = "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc"
ORCA_POOL = "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE"
WSOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
WSOL_B = bytes([int(x) for x in []]) if False else None
out = {"started_at_utc": now()}

# optional layout source (best effort, max 2 tries)
layout_url = None
for url in ["https://raw.githubusercontent.com/raydium-io/raydium-sdk/master/src/liquidity/layout.ts",
            "https://raw.githubusercontent.com/raydium-io/raydium-sdk-V2/master/src/raydium/liquidity/layout.ts"]:
    r = get(url, "raydium_amm_layout")
    if r is not None and r.status_code == 200 and "LIQUIDITY_STATE_LAYOUT_V4" in r.text:
        layout_url = url
        open(BASE + r"\raydium_amm_layout.ts.txt", "w", encoding="utf-8").write(r.text)
        break
    time.sleep(0.4)
out["layout_url"] = layout_url

# read AMM pool state
j = rpc_call("getAccountInfo", [AMM_POOL, {"encoding": "base64", "commitment": "finalized"}], "amm_pool_state")
v = j["result"]["value"]; amm = base64.b64decode(v["data"][0]); slot0 = j["result"]["context"]["slot"]
out["amm_state_read"] = {"slot": slot0, "bytes": len(amm), "owner": v["owner"]}
time.sleep(0.5)

# locate mints dynamically in account data, derive vault candidates
def find_all(hay, needle):
    res = []; i = 0
    while True:
        i = hay.find(needle, i)
        if i < 0: break
        res.append(i); i += 1
    return res
# decode mint pubkeys from known base58 constants via base58 decode (implement decode)
def b58d(strr):
    n = 0
    for c in strr: n = n*58 + W.index(c)
    b = n.to_bytes((n.bit_length()+7)//8, "big") if n else b""
    pad = 0
    for c in strr:
        if c == "1": pad += 1
        else: break
    return b"\x00"*pad + b
wsol_b, usdc_b = b58d(WSOL), b58d(USDC)
wsol_offs, usdc_offs = find_all(amm, wsol_b), find_all(amm, usdc_b)
out["mint_offsets"] = {"wsol": wsol_offs, "usdc": usdc_offs}
base_mint_off = wsol_offs[0] if wsol_offs else None
quote_mint_off = usdc_offs[0] if usdc_offs else None
base_vault = quote_vault = None
if base_mint_off is not None and quote_mint_off is not None and quote_mint_off == base_mint_off + 32:
    base_vault_off, quote_vault_off = base_mint_off - 64, base_mint_off - 32
    base_vault = b58(amm[base_vault_off:base_vault_off+32])
    quote_vault = b58(amm[quote_vault_off:quote_vault_off+32])
out["derived_vaults"] = {"base_vault": base_vault, "quote_vault": quote_vault}

# find swap fee numerator/denominator: known small pair 25/10000 in u64 LE
fee_offs = None
for off in range(0, len(amm)-16):
    a = struct.unpack("<Q", amm[off:off+8])[0]; b = struct.unpack("<Q", amm[off+8:off+16])[0]
    if a in (25, 30, 0) and b == 10000:
        fee_offs = off; break
out["fee_candidate"] = None
if fee_offs:
    out["fee_candidate"] = {"offset": fee_offs,
                            "swapFeeNumerator": struct.unpack("<Q", amm[fee_offs:fee_offs+8])[0],
                            "swapFeeDenominator": struct.unpack("<Q", amm[fee_offs+8:fee_offs+16])[0]}
# status (u64 at 0) and poolOpenTime: try offset 224 u64 sanity (unix time plausible)
def plausible_time(x): return 1_500_000_000 < x < 2_100_000_000
open_candidates = [off for off in range(0, len(amm)-8, 8) if plausible_time(struct.unpack("<Q", amm[off:off+8])[0])]
out["amm_raw"] = {"status_u64_at_0": struct.unpack("<Q", amm[0:8])[0],
                  "state_u64_at_48": struct.unpack("<Q", amm[48:56])[0],
                  "poolOpenTime_candidates": open_candidates}
time.sleep(0.5)

# same-slot read: both vaults + Orca pool + 2 mints
addrs = [base_vault, quote_vault, ORCA_POOL, WSOL, USDC]
j = rpc_call("getMultipleAccounts", [addrs, {"encoding": "base64", "commitment": "finalized"}], "same_slot_state")
vals = j["result"]["value"]; slot = j["result"]["context"]["slot"]
out["same_slot_read"] = {"slot": slot, "accounts": addrs, "at_utc": now()}
def tok(v):
    d = base64.b64decode(v["data"][0])
    return {"mint": b58(d[0:32]), "amount": struct.unpack("<Q", d[64:72])[0], "bytes": len(d)}
out["vaults"] = {"base": tok(vals[0]), "quote": tok(vals[1])}
out["mints"] = {"WSOL": {"owner": vals[3]["owner"], "decimals": base64.b64decode(vals[3]["data"][0])[44]},
                "USDC": {"owner": vals[4]["owner"], "decimals": base64.b64decode(vals[4]["data"][0])[44]}}
orca = base64.b64decode(vals[2]["data"][0])
orc = {"tick_spacing": struct.unpack("<H", orca[41:43])[0], "fee_rate": struct.unpack("<H", orca[45:47])[0],
       "protocol_fee_rate": struct.unpack("<H", orca[47:49])[0],
       "liquidity": int.from_bytes(orca[49:65], "little"), "sqrt_price": int.from_bytes(orca[65:81], "little"),
       "tick_current": struct.unpack("<i", orca[81:85])[0],
       "mint_a": b58(orca[101:133]), "vault_a": b58(orca[133:165]),
       "mint_b": b58(orca[181:213]), "vault_b": b58(orca[213:245])}
out["orca_state"] = {k: (str(x) if isinstance(x, int) and x > 2**53 else x) for k, x in orc.items()}
out["orca_owner"] = vals[2]["owner"]
out["identity_check"] = {
    "vault_mints_match": out["vaults"]["base"]["mint"] == WSOL and out["vaults"]["quote"]["mint"] == USDC,
    "orca_owner_ok": vals[2]["owner"] == ORCA_PROG,
    "orca_mints_ok": orc["mint_a"] == WSOL and orc["mint_b"] == USDC,
    "token_programs": {"WSOL": out["mints"]["WSOL"]["owner"], "USDC": out["mints"]["USDC"]["owner"]},
    "both_token_programs_equal": out["mints"]["WSOL"]["owner"] == out["mints"]["USDC"]["owner"]}
time.sleep(0.4)
# blocktime for slot reference
j = rpc_call("getBlockTime", [max(0, slot-2)], "blocktime")
bt = j.get("result")
out["slot_blocktime_utc"] = datetime.datetime.fromtimestamp(bt, datetime.timezone.utc).isoformat() if isinstance(bt, int) else None

# ---------- compute quotes ----------
def amm_quote(amount_in_raw, direction):
    base_res = out["vaults"]["base"]["amount"]; quote_res = out["vaults"]["quote"]["amount"]
    num = out["fee_candidate"]["swapFeeNumerator"]; den = out["fee_candidate"]["swapFeeDenominator"]
    net = amount_in_raw * (den - num) // den
    if direction == "base_to_quote":
        out_raw = quote_res * net // (base_res + net)
    else:
        out_raw = base_res * net // (quote_res + net)
    return net, out_raw

L = Decimal(orc["liquidity"]); S = Decimal(orc["sqrt_price"]); TWO64 = Decimal(2) ** 64
sqrtP = S / TWO64
fee_ppm = orc["fee_rate"]
def orca_quote(amount_in_raw, direction):
    a_in = amount_in_raw * (1_000_000 - fee_ppm) // 1_000_000
    if direction == "a_to_b":
        inv_new = Decimal(1) / sqrtP + Decimal(a_in) / L
        sqrtP_new = Decimal(1) / inv_new
        out_raw = int((L * (sqrtP - sqrtP_new)).to_integral_value(rounding="ROUND_FLOOR"))
    else:
        sqrtP_new = sqrtP + Decimal(a_in) / L
        out_raw = int((L * ((Decimal(1) / sqrtP) - (Decimal(1) / sqrtP_new))).to_integral_value(rounding="ROUND_FLOOR"))
    # tick check
    new_tick = math.floor(2 * math.log(float(sqrtP_new)) / math.log(1.0001)) if sqrtP_new > 0 else None
    crossed = None if new_tick is None else abs(new_tick - orc["tick_current"]) >= orc["tick_spacing"]
    return a_in, out_raw, new_tick, crossed
out["fees"] = {"orca_fee_ppm": fee_ppm, "amm_v4_fee_num_den": [out["fee_candidate"]["swapFeeNumerator"], out["fee_candidate"]["swapFeeDenominator"]]}

tiers_sol = [Decimal("0.1"), Decimal("1"), Decimal("10"), Decimal("25")]
LAMP = Decimal(10) ** 9; USDC1 = Decimal(10) ** 6
table = []
TX_FEE_LAMPORTS = 3 * 5000
for amt in tiers_sol:
    in_lamports = int(amt * LAMP)
    row = {"amount_in_sol": str(amt)}
    # direction 1: SOL -> USDC on Orca, then USDC -> SOL on Raydium AMM
    o_in, o_out, o_tick, o_crossed = orca_quote(in_lamports, "a_to_b")
    a_in2, a_out2 = amm_quote(o_out, "quote_to_base")
    row["d1_orca_then_amm"] = {"orca_out_usdc_raw": o_out, "orca_out_usdc": str(Decimal(o_out) / USDC1),
                               "orca_new_tick": o_tick, "orca_crossed_tick_range": o_crossed,
                               "amm_out_lamports": a_out2, "amm_out_sol": str(Decimal(a_out2) / LAMP),
                               "gross_net_sol": str((Decimal(a_out2) - in_lamports) / LAMP),
                               "net_after_tx_fee_sol": str((Decimal(a_out2) - in_lamports - TX_FEE_LAMPORTS) / LAMP)}
    # direction 2: SOL -> USDC on Raydium AMM, then USDC -> SOL on Orca
    a_in, a_out = amm_quote(in_lamports, "base_to_quote")
    o_in2, o_out2, o_tick2, o_crossed2 = orca_quote(a_out, "b_to_a")
    row["d2_amm_then_orca"] = {"amm_out_usdc_raw": a_out, "amm_out_usdc": str(Decimal(a_out) / USDC1),
                               "orca_out_lamports": o_out2, "orca_out_sol": str(Decimal(o_out2) / LAMP),
                               "orca_new_tick": o_tick2, "orca_crossed_tick_range": o_crossed2,
                               "gross_net_sol": str((Decimal(o_out2) - in_lamports) / LAMP),
                               "net_after_tx_fee_sol": str((Decimal(o_out2) - in_lamports - TX_FEE_LAMPORTS) / LAMP)}
    table.append(row)
out["quote_table"] = table
# spot implied prices (raw units adjusted by decimals)
base_res = Decimal(out["vaults"]["base"]["amount"]); quote_res = Decimal(out["vaults"]["quote"]["amount"])
amm_price = (quote_res / Decimal(10)**6) / (base_res / Decimal(10)**9)
orca_price = (sqrtP * sqrtP) * Decimal(10)**9 / Decimal(10)**6
out["spot_prices"] = {"raydium_amm_v4_usdc_per_sol": str(amm_price.quantize(Decimal("0.000001"))),
                      "orca_whirlpool_usdc_per_sol": str(orca_price.quantize(Decimal("0.000001"))),
                      "spread_bps_orca_minus_raydium": str(((orca_price - amm_price) / amm_price * 10000).quantize(Decimal("0.01")))}
out["finished_at_utc"] = now()
out["requests"] = reqs
save("state_and_quotes.json", out)
print(json.dumps({k: out.get(k) for k in ["started_at_utc", "finished_at_utc", "layout_url", "amm_state_read",
    "mint_offsets", "derived_vaults", "fee_candidate", "amm_raw", "same_slot_read", "vaults", "mints", "orca_state",
    "orca_owner", "identity_check", "slot_blocktime_utc", "fees", "spot_prices", "quote_table", "requests"]},
    ensure_ascii=False, indent=1)[:12000])
