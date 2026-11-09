import json, time, hashlib, base64, datetime, struct, math
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
prev = json.load(open(BASE + r"\state_and_quotes.json", encoding="utf-8"))
reqs = []
def rpc(method, params, name):
    t0 = time.time()
    r = s.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=30)
    reqs.append({"url": RPC, "method": method, "name": name, "http_status": r.status_code, "at": now(),
                 "sha256": hashlib.sha256(r.content).hexdigest(), "elapsed_s": round(time.time()-t0, 3)})
    return r.json()

AMM_POOL = "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2"
ORCA_POOL = "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE"
AMM_V4 = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
out = {"refreshed_at_utc": now(), "previous_slot": prev["same_slot_read"]["slot"]}
j = rpc("getMultipleAccounts", [[prev["derived_vaults"]["base_vault"], prev["derived_vaults"]["quote_vault"], ORCA_POOL],
                                {"encoding": "base64", "commitment": "finalized"}], "refresh_state")
vals = j["result"]["value"]; slot = j["result"]["context"]["slot"]
def tok(v):
    d = base64.b64decode(v["data"][0]); return {"mint": b58(d[0:32]), "amount": struct.unpack("<Q", d[64:72])[0]}
vaults = {"base": tok(vals[0]), "quote": tok(vals[1])}
orca = base64.b64decode(vals[2]["data"][0])
o = {"tick_spacing": struct.unpack("<H", orca[41:43])[0], "fee_rate": struct.unpack("<H", orca[45:47])[0],
     "liquidity": int.from_bytes(orca[49:65], "little"), "sqrt_price": int.from_bytes(orca[65:81], "little"),
     "tick_current": struct.unpack("<i", orca[81:85])[0]}
out.update({"slot": slot, "vaults": vaults, "orca": o, "orca_owner": vals[2]["owner"]})
time.sleep(0.5)
j = rpc("getAccountInfo", [AMM_POOL, {"encoding": "base64", "commitment": "finalized"}], "amm_state")
amm = base64.b64decode(j["result"]["value"]["data"][0])
def u(off, size=8): return int.from_bytes(amm[off:off+size], "little")
def pk(off): return b58(amm[off:off+32])
fields = {"status": u(0), "baseDecimal": u(32), "quoteDecimal": u(40), "state": u(48),
          "tradeFeeNumerator": u(144), "tradeFeeDenominator": u(152),
          "swapFeeNumerator": u(176), "swapFeeDenominator": u(184),
          "poolOpenTime": u(224), "lpReserve": u(720),
          "baseVault": pk(336), "quoteVault": pk(368), "baseMint": pk(400), "quoteMint": pk(432), "lpMint": pk(464)}
out["amm_fields"] = fields
out["amm_state_slot"] = j["result"]["context"]["slot"]
bt = rpc("getBlockTime", [max(0, slot-2)], "refresh_blocktime").get("result")
out["blocktime_utc"] = datetime.datetime.fromtimestamp(bt, datetime.timezone.utc).isoformat() if isinstance(bt, int) else None

# recompute quotes (same model as quotes.py, validated: no tick crossing flag)
L = Decimal(o["liquidity"]); S = Decimal(o["sqrt_price"]); sqrtP = S / (Decimal(2) ** 64)
fee_ppm = o["fee_rate"]
def orca_q(a, direction):
    ai = a * (1_000_000 - fee_ppm) // 1_000_000
    if direction == "a_to_b":
        inv = Decimal(1) / sqrtP + Decimal(ai) / L; sp2 = Decimal(1) / inv
        return int((L * (sqrtP - sp2)).to_integral_value(rounding="ROUND_FLOOR"))
    sp2 = sqrtP + Decimal(ai) / L
    return int((L * ((Decimal(1) / sqrtP) - (Decimal(1) / sp2))).to_integral_value(rounding="ROUND_FLOOR"))
num, den = fields["swapFeeNumerator"], fields["swapFeeDenominator"]
def amm_q(a, direction):
    br, qr = vaults["base"]["amount"], vaults["quote"]["amount"]
    net = a * (den - num) // den
    return (qr * net // (br + net)) if direction == "base_to_quote" else (br * net // (qr + net))
LAMP = Decimal(10) ** 9; U1 = Decimal(10) ** 6
spot = {"raydium_amm_usdc_per_sol": str((Decimal(vaults["quote"]["amount"]) / U1 / (Decimal(vaults["base"]["amount"]) / LAMP)).quantize(Decimal("0.000001"))),
        "orca_usdc_per_sol": str(((sqrtP * sqrtP) * Decimal(10) ** 9 / U1).quantize(Decimal("0.000001")))}
rows = []
for amt in [Decimal("0.1"), Decimal("1"), Decimal("10"), Decimal("25")]:
    inl = int(amt * LAMP)
    o_out = orca_q(inl, "a_to_b"); back1 = amm_q(o_out, "quote_to_base")
    a_out = amm_q(inl, "base_to_quote"); back2 = orca_q(a_out, "b_to_a")
    rows.append({"amount_in_sol": str(amt), "d1_orca_then_amm": {"out_sol": str(Decimal(back1) / LAMP), "net_sol": str((Decimal(back1) - inl) / LAMP)},
                 "d2_amm_then_orca": {"out_sol": str(Decimal(back2) / LAMP), "net_sol": str((Decimal(back2) - inl) / LAMP)}})
out["spot_prices"] = spot
out["quote_table_refresh"] = rows
out["requests"] = reqs
json.dump(out, open(BASE + r"\refresh_quotes.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1)[:6000])
