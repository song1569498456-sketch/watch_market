import json, time, datetime, hashlib, decimal
import requests
from eth_utils import keccak
from eth_abi import encode, decode

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\ARB01\live-20261109T141903Z\raw"
sess = requests.Session(); sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [100]
RPCS = [("arb1", "https://arb1.arbitrum.io/rpc"),
        ("arb-publicnode", "https://arbitrum-one-rpc.publicnode.com")]


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def throttle(h):
    n = time.time()
    if h in last and n - last[h] < 0.3:
        time.sleep(0.3 - (n - last[h]))
    last[h] = time.time()


def http_get(url, tag, host):
    throttle(host); count[0] += 1
    e = {"n": count[0], "kind": "GET", "host": host, "tag": tag, "url": url,
         "at_utc": utcnow()}
    try:
        r = sess.get(url, timeout=25)
        e["http_status"] = r.status_code
        e["sha256"] = hashlib.sha256(r.content).hexdigest()
        log.append(e)
        return r.status_code, r.json()
    except Exception as ex:
        e["error"] = repr(ex); log.append(e); return None, None


def rpc(method, params, tag):
    err = None
    for host, url in RPCS:
        throttle(host); _id[0] += 1; count[0] += 1
        e = {"n": count[0], "kind": "POST", "host": host, "tag": tag,
             "rpc_method": method, "at_utc": utcnow()}
        try:
            r = sess.post(url, json={"jsonrpc": "2.0", "id": _id[0],
                                     "method": method, "params": params}, timeout=25)
            e["http_status"] = r.status_code
            j = r.json(); log.append(e)
            if "error" in j:
                e["rpc_error"] = j["error"]; err = j["error"]; continue
            return j.get("result"), None
        except Exception as ex:
            e["error"] = repr(ex); err = repr(ex); log.append(e); continue
    return None, err


def strip(h):
    return h[2:] if isinstance(h, str) and h.startswith("0x") else h


def sel(s):
    return "0x" + keccak(text=s)[:4].hex()


def main():
    out = {"started_at_utc": utcnow()}
    WETH = "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1"
    USDC_E = "0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8"
    QUOTER_V1 = "0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6"
    SUSHI_ROUTER = "0x1b02dA8Cb0d097eB8D57A175b88c7D8b47997506"
    UNI_POOL = "0xc31e54c7a869b9fcbecc14363cf510d1c41fa443"
    SUSHI_PAIR = "0x905dfcd5649217c42684f23958568e533c711aa3"
    BLPX_POOL = "0x7c03126dc25748c658efb946d32b42a4a84d49d2"
    BLPX = "0xf2925a78adac85ca330643bc5584a694199afb76"
    USDC = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"

    bn, _ = rpc("eth_blockNumber", [], "head")
    out["head_block"] = int(bn, 16) if bn else None
    if bn:
        b, _ = rpc("eth_getBlockByNumber", [bn, False], "headBlock")
        if b:
            out["head_block_time_utc"] = datetime.datetime.fromtimestamp(
                int(b["timestamp"], 16), datetime.timezone.utc).isoformat()
    pinned_b = 522706375
    out["quotes_block"] = pinned_b
    pinned = hex(pinned_b)

    def call(to, data, tag, block=None):
        return rpc("eth_call", [{"to": to, "data": data}, block or pinned], tag)

    def quote_uni(tin, tout, amt, fee, tag):
        data = sel("quoteExactInputSingle(address,address,uint24,uint256,uint160)") + encode(
            ["address", "address", "uint24", "uint256", "uint160"],
            [tin, tout, fee, amt, 0]).hex()
        r, err = call(QUOTER_V1, data, tag)
        val = None
        if r:
            try:
                val = int(r, 16)
            except Exception:
                err = repr(r)
        return {"amount_in": str(amt), "amount_out": val, "error": err}

    def quote_sushi(tin, tout, amt, tag):
        data = sel("getAmountsOut(uint256,address[])") + encode(
            ["uint256", "address[]"], [amt, [tin, tout]]).hex()
        r, err = call(SUSHI_ROUTER, data, tag)
        val = None
        if r:
            try:
                val = int(decode(["uint256[]"], bytes.fromhex(strip(r)))[0][-1])
            except Exception as ex:
                err = repr(ex)
        return {"amount_in": str(amt), "amount_out": val, "error": err}

    tiers = []
    for amt in (10, 100):
        t = {"input_stable": amt, "block": pinned_b}
        q1u = quote_uni(USDC_E, WETH, amt * 10**6, 500, f"u_s2w_{amt}")
        t["univ3_stable_to_weth"] = q1u
        if q1u["amount_out"]:
            t["sushi_weth_to_stable_from_uni"] = quote_sushi(
                WETH, USDC_E, q1u["amount_out"], f"s_w2s_{amt}")
        q1s = quote_sushi(USDC_E, WETH, amt * 10**6, f"s_s2w_{amt}")
        t["sushi_stable_to_weth"] = q1s
        if q1s["amount_out"]:
            t["univ3_weth_to_stable_from_sushi"] = quote_uni(
                WETH, USDC_E, q1s["amount_out"], 500, f"u_w2s_{amt}")
        tiers.append(t)
    out["small_tier_quotes"] = tiers

    # mid-price spread from same-block pool states
    us, _ = rpc("eth_call", [{"to": UNI_POOL,
                              "data": sel("slot0()")}, "latest"], "uni_slot0_recheck")
    u_mid = None
    if us:
        v = decode(["uint160", "int24", "uint16", "uint16", "uint16", "uint32", "bool"],
                   bytes.fromhex(strip(us)))
        p = (decimal.Decimal(v[0]) / decimal.Decimal(2 ** 96)) ** 2
        u_mid = p * decimal.Decimal(10) ** 12  # token1/token0 human: USDC.e per WETH
    spr, _ = rpc("eth_call", [{"to": SUSHI_PAIR, "data": sel("getReserves()")},
                              "latest"], "sushi_reserves_recheck")
    s_mid = None
    sr = None
    if spr:
        r0, r1, ts = decode(["uint112", "uint112", "uint32"], bytes.fromhex(strip(spr)))
        sr = {"reserve0_WETH": str(r0), "reserve1_USDCe": str(r1), "ts": ts}
        # token0=WETH, token1=USDC.e
        s_mid = (decimal.Decimal(r1) / decimal.Decimal(10) ** 6) / (
            decimal.Decimal(r0) / decimal.Decimal(10) ** 18)
    out["mid_prices"] = {
        "uniswap_v3_mid_usdce_per_weth": str(u_mid),
        "sushi_v2_mid_usdce_per_weth": str(s_mid),
        "spread_bps_sushi_minus_uni": str(
            (s_mid - u_mid) / u_mid * 10000) if (u_mid and s_mid) else None,
        "sushi_reserves": sr}

    # N-ARB new pool candidate: identity + liquidity/quotability
    cand = {"pool": BLPX_POOL, "suspected_token": BLPX, "stable": USDC}
    for name, addr in (("pool", BLPX_POOL),):
        c, _ = rpc("eth_getCode", [addr, "latest"], "code_blpx_pool")
        cand["pool_code_bytes"] = (len(c) - 2) // 2 if c else 0
        cand["pool_code_sha256"] = hashlib.sha256(bytes.fromhex(strip(c))).hexdigest() if c else None
    for fld, sig in (("token0", "token0()"), ("token1", "token1()"), ("fee", "fee()"),
                     ("slot0", "slot0()"), ("liquidity", "liquidity()")):
        r, err = call(BLPX_POOL, sel(sig), "blpx_" + fld, block="latest")
        if fld in ("token0", "token1"):
            cand[fld] = "0x" + strip(r)[24:] if r else None
        elif fld == "fee":
            cand[fld] = int(r, 16) if r else None
        elif fld == "slot0" and r:
            try:
                v = decode(["uint160", "int24", "uint16", "uint16", "uint16",
                            "uint32", "bool"], bytes.fromhex(strip(r)))
                cand["slot0"] = {"sqrtPriceX96": str(v[0]), "tick": v[1]}
            except Exception as ex:
                cand["slot0_error"] = repr(ex)
        elif fld == "liquidity" and r:
            cand["liquidity"] = str(int(r, 16))
        cand[fld + "_error"] = err
    # quote 100 USDC -> BLPX on that pool (fee 3000)
    cq = quote_uni(USDC, BLPX, 100 * 10**6, 3000, "blpx_quote_100usdc")
    cand["quote_100USDC_to_BLPX"] = cq
    cq2 = quote_uni(BLPX, USDC, 10**18, 3000, "blpx_quote_1BLPX")
    cand["quote_1BLPX_to_USDC"] = cq2
    out["n_arb_new_pool"] = cand

    # dexscreener discovery for BLPX token: how many DEX venues
    st, j = http_get("https://api.dexscreener.com/latest/dex/tokens/" + BLPX,
                     "ds_blpx_pairs", "api.dexscreener.com")
    pairs = []
    if isinstance(j, dict):
        for p in (j.get("pairs") or [])[:10]:
            pairs.append({"chainId": p.get("chainId"), "dexId": p.get("dexId"),
                          "pairAddress": p.get("pairAddress"),
                          "liquidityUsd": (p.get("liquidity") or {}).get("usd"),
                          "priceUsd": p.get("priceUsd"),
                          "createdAt": p.get("pairCreatedAt")})
    out["dexscreener_blpx"] = {"http_status": st, "pairs": pairs}

    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeB-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeB.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:8000])


if __name__ == "__main__":
    main()
