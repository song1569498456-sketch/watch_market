import json, time, datetime, hashlib, os
import requests
from eth_utils import keccak
from eth_abi import encode, decode

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\ARB01\live-20261109T141903Z\raw"
os.makedirs(OUT, exist_ok=True)
sess = requests.Session(); sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [0]
RPCS = [("arb1", "https://arb1.arbitrum.io/rpc"),
        ("arb-publicnode", "https://arbitrum-one-rpc.publicnode.com")]


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def throttle(h):
    n = time.time()
    if h in last and n - last[h] < 0.3:
        time.sleep(0.3 - (n - last[h]))
    last[h] = time.time()


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
    USDC = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"      # native
    USDC_E = "0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8"    # bridged
    UNI_FACTORY = "0x1F98431c8aD98523631AE4a59f267346ea31F984"
    SUSHI_FACTORY = "0xc35DADB65012eC5796536bD9864eD8773aBc74C4"
    SUSHI_ROUTER = "0x1b02dA8Cb0d097eB8D57A175b88c7D8b47997506"
    QUOTER_V1 = "0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6"
    BLPX_POOL = "0x7c03126d"  # prefix from briefing

    cid, _ = rpc("eth_chainId", [], "chainId")
    out["chain_id"] = int(cid, 16) if cid else None
    bn, _ = rpc("eth_blockNumber", [], "blockNumber")
    out["head_block"] = int(bn, 16) if bn else None
    if bn:
        b, _ = rpc("eth_getBlockByNumber", [bn, False], "headBlock")
        if b:
            out["head_block_info"] = {k: b.get(k) for k in
                                      ("number", "timestamp", "hash", "gasLimit", "baseFeePerGas")}
            out["head_block_time_utc"] = datetime.datetime.fromtimestamp(
                int(b["timestamp"], 16), datetime.timezone.utc).isoformat()
    out["pinned_block"] = out["head_block"] - 2 if out["head_block"] else None
    pinned = hex(out["pinned_block"]) if out["pinned_block"] else "latest"
    gp, _ = rpc("eth_gasPrice", [], "gasPrice")
    out["gas_price_wei"] = int(gp, 16) if gp else None

    def call(to, data, tag, block=None):
        return rpc("eth_call", [{"to": to, "data": data}, block or pinned], tag)

    def code(addr, tag):
        c, _ = rpc("eth_getCode", [addr, "latest"], tag)
        return {"address": addr, "bytes": (len(c) - 2) // 2 if c else 0,
                "sha256": hashlib.sha256(bytes.fromhex(strip(c))).hexdigest() if c else None}

    out["contracts"] = {
        "uniswap_v3_factory": code(UNI_FACTORY, "code_uni_factory"),
        "sushi_v2_factory": code(SUSHI_FACTORY, "code_sushi_factory"),
        "sushi_router": code(SUSHI_ROUTER, "code_sushi_router"),
        "quoter_v1": code(QUOTER_V1, "code_quoter_v1"),
    }

    # candidate pools: Uniswap V3 same pair across fee tiers; Sushi V2 pairs
    def dec_addr(r):
        return "0x" + strip(r)[24:] if r and int(r, 16) else None

    uni = {}
    for label, (a, b, fee) in {
        "WETH_USDCe_500": (WETH, USDC_E, 500),
        "WETH_USDCe_3000": (WETH, USDC_E, 3000),
        "WETH_USDC_500": (WETH, USDC, 500),
    }.items():
        r, err = call(UNI_FACTORY, sel("getPool(address,address,uint24)") +
                      encode(["address", "address", "uint24"], [a, b, fee]).hex(),
                      "uni_getPool_" + label)
        uni[label] = {"tokenA": a, "tokenB": b, "fee": fee,
                      "pool": dec_addr(r), "error": err}
    out["uniswap_pools"] = uni
    sushi = {}
    for label, (a, b) in {
        "WETH_USDCe": (WETH, USDC_E),
        "WETH_USDC": (WETH, USDC),
    }.items():
        r, err = call(SUSHI_FACTORY, sel("getPair(address,address)") +
                      encode(["address", "address"], [a, b]).hex(),
                      "sushi_getPair_" + label)
        sushi[label] = {"tokenA": a, "tokenB": b, "pair": dec_addr(r), "error": err}
    out["sushi_pairs"] = sushi

    # pick same-token pair: USDC.e vs WETH if both venues have pools
    cands = [("USDC_E", USDC_E, "WETH", WETH,
              uni["WETH_USDCe_500"]["pool"], sushi["WETH_USDCe"]["pair"], 500),
             ("USDC", USDC, "WETH", WETH,
              uni["WETH_USDC_500"]["pool"], sushi["WETH_USDC"]["pair"], 500)]
    chosen = None
    for c in cands:
        if c[4] and c[5]:
            chosen = c; break
    out["chosen_pair"] = None if not chosen else {
        "stable_symbol": c[0], "stable": c[1], "weth": c[3],
        "uniswap_pool": c[4], "sushi_pair": c[5], "uniswap_fee": c[6]}
    if not chosen:
        out["error"] = "no same-token pair found on both venues"
        json.dump(out, open(OUT + r"\probeA.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(json.dumps(out, ensure_ascii=False, indent=1)[:4000]); return

    sym, STABLE, _, WETH2, UP, SP, FEE = chosen
    dec_stable = 6
    dec_weth = 18

    # identity + state reads
    pool_state = {}
    for name, addr in (("uniswap_pool", UP), ("sushi_pair", SP)):
        item = {"address": addr}
        c, _ = rpc("eth_getCode", [addr, "latest"], "code_" + name)
        item["code_bytes"] = (len(c) - 2) // 2 if c else 0
        item["code_sha256"] = hashlib.sha256(bytes.fromhex(strip(c))).hexdigest() if c else None
        for fld, sig in (("token0", "token0()"), ("token1", "token1()")):
            r, err = call(addr, sel(sig), f"{name}_{fld}")
            item[fld] = dec_addr(r); item[fld + "_error"] = err
        if name == "uniswap_pool":
            for fld, sig in (("fee", "fee()"), ("slot0", "slot0()"),
                             ("liquidity", "liquidity()")):
                r, err = call(addr, sel(sig), f"{name}_{fld}")
                if fld == "fee":
                    item[fld] = int(r, 16) if r else None
                elif fld == "slot0" and r:
                    try:
                        v = decode(["uint160", "int24", "uint16", "uint16", "uint16",
                                    "uint32", "bool"], bytes.fromhex(strip(r)))
                        item["slot0_decoded"] = {"sqrtPriceX96": str(v[0]), "tick": v[1]}
                    except Exception as ex:
                        item["slot0_decode_error"] = repr(ex)
                elif fld == "liquidity" and r:
                    item["liquidity"] = str(int(r, 16))
                item[fld + "_error"] = err
        else:
            r, err = call(addr, sel("getReserves()"), f"{name}_reserves")
            if r:
                r0, r1, ts = decode(["uint112", "uint112", "uint32"],
                                    bytes.fromhex(strip(r)))
                item["reserves"] = {"reserve0": str(r0), "reserve1": str(r1),
                                    "blockTimestampLast": ts}
            item["getReserves_error"] = err
        pool_state[name] = item
    out["pool_state"] = pool_state

    def quote_uni(tin, tout, amt, tag):
        data = sel("quoteExactInputSingle(address,address,uint24,uint256,uint160)") + encode(
            ["address", "address", "uint24", "uint256", "uint160"],
            [tin, tout, FEE, amt, 0]).hex()
        r, err = call(QUOTER_V1, data, tag)
        val = None
        if r:
            try:
                val = int(r, 16)
            except Exception:
                err = repr(r)
        return {"amount_in": str(amt), "amount_out": val, "raw": r, "error": err}

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
        return {"amount_in": str(amt), "amount_out": val, "raw": r, "error": err}

    # quotes: direction A: stable->WETH on Uniswap then WETH->stable on Sushi
    # direction B: stable->WETH on Sushi then WETH->stable on Uniswap
    tiers = []
    for amt_stable in (1000, 10000, 100000):
        t = {"input_stable": amt_stable, "block": out["pinned_block"]}
        # leg1 on Uniswap
        q1u = quote_uni(STABLE, WETH2, amt_stable * 10**dec_stable,
                        f"u_stable_to_weth_{amt_stable}")
        t["univ3_stable_to_weth"] = q1u
        # leg2 on Sushi with actual output
        if q1u["amount_out"]:
            t["sushi_weth_to_stable_from_uni"] = quote_sushi(
                WETH2, STABLE, q1u["amount_out"], f"s_weth_to_stable_{amt_stable}")
        # leg1 on Sushi
        q1s = quote_sushi(STABLE, WETH2, amt_stable * 10**dec_stable,
                          f"s_stable_to_weth_{amt_stable}")
        t["sushi_stable_to_weth"] = q1s
        if q1s["amount_out"]:
            t["univ3_weth_to_stable_from_sushi"] = quote_uni(
                WETH2, STABLE, q1s["amount_out"], f"u_weth_to_stable_{amt_stable}")
        # direct both-venue stable->weth comparison at same input
        tiers.append(t)
    out["quotes"] = tiers

    # derived nets
    derived = []
    for t in tiers:
        row = {"input_stable": t["input_stable"], "block": t["block"]}
        try:
            a = t["univ3_stable_to_weth"]["amount_out"]
            b = t.get("sushi_weth_to_stable_from_uni", {}).get("amount_out")
            row["route_uni_buy_sushi_sell"] = {
                "stable_in": t["input_stable"],
                "weth_bought": a / 1e18 if a else None,
                "stable_back": b / 1e6 if b else None,
                "net_stable": (b - t["input_stable"] * 10**6) / 1e6 if b else None}
        except Exception as ex:
            row["route_uni_buy_sushi_sell_error"] = repr(ex)
        try:
            a2 = t["sushi_stable_to_weth"]["amount_out"]
            b2 = t.get("univ3_weth_to_stable_from_sushi", {}).get("amount_out")
            row["route_sushi_buy_uni_sell"] = {
                "stable_in": t["input_stable"],
                "weth_bought": a2 / 1e18 if a2 else None,
                "stable_back": b2 / 1e6 if b2 else None,
                "net_stable": (b2 - t["input_stable"] * 10**6) / 1e6 if b2 else None}
        except Exception as ex:
            row["route_sushi_buy_uni_sell_error"] = repr(ex)
        derived.append(row)
    out["derived_round_trips"] = derived

    # new pool candidate from N-ARB briefing: prefix 0x7c03126d - find via logs impossible; try known pair list via dexscreener not needed.
    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeA-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeA.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:9000])


if __name__ == "__main__":
    main()
