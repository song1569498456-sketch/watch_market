import json, time, datetime, hashlib, os, sys
import requests
from eth_utils import keccak
from eth_abi import encode, decode

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\OP02\live-20261109T141903Z\raw"
os.makedirs(OUT, exist_ok=True)
RPCS = [("op-mainnet", "https://mainnet.optimism.io"),
        ("op-publicnode", "https://optimism-rpc.publicnode.com")]
sess = requests.Session(); sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [0]

WETH = "0x4200000000000000000000000000000000000006"
USDC_E = "0x7F5c764cBc14f9669B88837ca1490cCa17c31607"
OPTOK = "0x4200000000000000000000000000000000000042"
VELO_FACTORY = "0xF1046053aa5682b4F9a81b5481394DA16BE5FF5a"
UNI_FACTORY = "0x1F98431c8aD98523631AE4a59f267346ea31F984"
UNI_QUOTER_V1 = "0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6"
SUSHI_FACTORY = "0xc35DADB65012eC5796536bD9864eD8773aBc74C4"
SUSHI_ROUTER = "0x1b02dA8Cb0d097eB8D57A175b88c7D8b47997506"


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


def sel(s):
    return "0x" + keccak(text=s)[:4].hex()


def strip(h):
    return h[2:] if isinstance(h, str) and h.startswith("0x") else h


def self_check():
    ok = True
    out = {}
    known = {
        "getPool(address,address,uint24)": "0x1698ee82",
        "getPair(address,address)": "0xe6a43905",
        "getAmountsOut(uint256,address[])": "0xd06ca61f",
        "quoteExactInputSingle(address,address,uint24,uint256,uint160)": None,
        "getAmountOut(uint256,address)": None,
        "isPaused(address)": None,
        "getFee(address)": None,
        "getPool(address,address,bool)": None,
        "getReserves()": "0x0902f1ac",
        "token0()": "0x0dfe1681",
        "token1()": "0xd21220a7",
        "slot0()": "0x3850c7bd",
    }
    for sig, exp in known.items():
        got = sel(sig)
        out[sig] = got
        if exp is not None and got != exp:
            ok = False
    # encode/decode roundtrip for Velodrome getAmountOut(uint256,address)
    enc = encode(["uint256", "address"], [10**18, WETH])
    out["getAmountOut_payload_len"] = len(enc)
    ok = ok and len(enc) == 64
    # decode a uint256 response
    ok = ok and int.from_bytes((123).to_bytes(32, "big"), "big") == 123
    print(json.dumps({"self_check_ok": ok, "selectors": out}, indent=1))
    return ok


def main():
    out = {"started_at_utc": utcnow()}
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

    def call(to, data, tag, block=None):
        return rpc("eth_call", [{"to": to, "data": data}, block or pinned], tag)

    def code(addr, tag):
        c, _ = rpc("eth_getCode", [addr, "latest"], tag)
        return {"address": addr, "bytes": (len(c) - 2) // 2 if c else 0,
                "sha256": hashlib.sha256(bytes.fromhex(strip(c))).hexdigest() if c else None,
                "code_hex": c}

    def dec_addr(r):
        return "0x" + strip(r)[24:] if r and int(r, 16) else None

    # ---- Velodrome V2 pool discovery ----
    velo = {}
    fc = code(VELO_FACTORY, "code_velo_factory")
    velo["factory"] = {k: v for k, v in fc.items() if k != "code_hex"}
    pool = None
    if fc["bytes"] > 0:
        r, err = call(VELO_FACTORY, sel("getPool(address,address,bool)") +
                      encode(["address", "address", "bool"], [WETH, USDC_E, False]).hex(),
                      "velo_getPool_volatile")
        velo["getPool_volatile"] = {"raw": r, "pool": dec_addr(r), "error": err}
        pool = dec_addr(r)
    velo["pool"] = pool
    if pool:
        pc = code(pool, "code_velo_pool")
        velo["pool_code"] = {k: v for k, v in pc.items() if k != "code_hex"}
        st = {}
        for fld, sig in (("token0", "token0()"), ("token1", "token1()"),
                         ("getReserves", "getReserves()"),
                         ("isPaused", "isPaused(address)"),
                         ("getFee", "getFee(address)")):
            data = sel(sig)
            if "address" in sig:
                data += encode(["address"], [pool]).hex()
            r, err = call(pool if not sig.startswith(("isPaused", "getFee")) else VELO_FACTORY,
                          data, "velo_" + fld)
            item = {"raw": r, "error": err}
            if fld in ("token0", "token1"):
                item["value"] = dec_addr(r)
            elif fld == "getReserves" and r:
                try:
                    r0, r1, ts = decode(["uint256", "uint256", "uint256"],
                                        bytes.fromhex(strip(r)))
                    item["reserves"] = {"reserve0": str(r0), "reserve1": str(r1), "ts": ts}
                except Exception:
                    try:
                        r0, r1, ts = decode(["uint112", "uint112", "uint32"],
                                            bytes.fromhex(strip(r)))
                        item["reserves"] = {"reserve0": str(r0), "reserve1": str(r1), "ts": ts}
                    except Exception as ex2:
                        item["decode_error"] = repr(ex2)
            elif r:
                item["value"] = str(int(r, 16))
            st[fld] = item
        velo["pool_state"] = st

    # ---- Uniswap V3 pool discovery ----
    uni = {}
    uni["factory"] = {k: v for k, v in code(UNI_FACTORY, "code_uni_factory").items()
                      if k != "code_hex"}
    uni["pools"] = {}
    upool = None
    for fee in (100, 500, 3000):
        r, err = call(UNI_FACTORY, sel("getPool(address,address,uint24)") +
                      encode(["address", "address", "uint24"], [WETH, USDC_E, fee]).hex(),
                      f"uni_getPool_{fee}")
        item = {"pool": dec_addr(r), "error": err}
        uni["pools"][str(fee)] = item
        if upool is None and item["pool"]:
            upool = item["pool"]
            uni["chosen_fee"] = fee
    uni["pool"] = upool
    if upool:
        uni["pool_code"] = {k: v for k, v in code(upool, "code_uni_pool").items()
                            if k != "code_hex"}
        pst = {}
        for fld, sig in (("token0", "token0()"), ("token1", "token1()"),
                         ("fee", "fee()"), ("slot0", "slot0()"),
                         ("liquidity", "liquidity()")):
            r, err = call(upool, sel(sig), "uni_pool_" + fld)
            if fld in ("token0", "token1"):
                pst[fld] = {"value": dec_addr(r), "error": err}
            elif fld == "fee":
                pst[fld] = {"value": int(r, 16) if r else None, "error": err}
            elif fld == "slot0" and r:
                try:
                    v = decode(["uint160", "int24", "uint16", "uint16", "uint16",
                                "uint32", "bool"], bytes.fromhex(strip(r)))
                    pst["slot0"] = {"sqrtPriceX96": str(v[0]), "tick": v[1]}
                except Exception as ex:
                    pst["slot0_error"] = repr(ex)
            elif fld == "liquidity" and r:
                pst["liquidity"] = str(int(r, 16))
            if fld not in pst:
                pst[fld] = {"error": err}
        uni["pool_state"] = pst
    uni["quoter"] = {k: v for k, v in code(UNI_QUOTER_V1, "code_uni_quoter").items()
                     if k != "code_hex"}

    # ---- Sushi V2 ----
    sushi = {}
    sushi["factory"] = {k: v for k, v in code(SUSHI_FACTORY, "code_sushi_factory").items()
                        if k != "code_hex"}
    r, err = call(SUSHI_FACTORY, sel("getPair(address,address)") +
                  encode(["address", "address"], [WETH, USDC_E]).hex(), "sushi_getPair")
    spool = dec_addr(r)
    sushi["pair"] = spool
    sushi["getPair"] = {"raw": r, "error": err}
    if spool:
        sushi["pair_code"] = {k: v for k, v in code(spool, "code_sushi_pair").items()
                              if k != "code_hex"}
        st = {}
        for fld, sig in (("token0", "token0()"), ("token1", "token1()"),
                         ("getReserves", "getReserves()")):
            r, err = call(spool, sel(sig), "sushi_pair_" + fld)
            if fld in ("token0", "token1"):
                st[fld] = {"value": dec_addr(r), "error": err}
            elif r:
                r0, r1, ts = decode(["uint112", "uint112", "uint32"], bytes.fromhex(strip(r)))
                st["reserves"] = {"reserve0": str(r0), "reserve1": str(r1), "ts": ts}
        sushi["pair_state"] = st
    sushi["router"] = {k: v for k, v in code(SUSHI_ROUTER, "code_sushi_router").items()
                       if k != "code_hex"}

    # ---- quotes at pinned block ----
    def velo_out(amt, token_in):
        data = sel("getAmountOut(uint256,address)") + encode(["uint256", "address"],
                                                             [amt, token_in]).hex()
        r, err = call(pool, data, f"velo_out_{token_in[:6]}_{amt}")
        return {"token_in": token_in, "amount_in": str(amt),
                "amount_out": str(int(r, 16)) if r else None, "error": err}

    def uni_out(tin, tout, amt, fee):
        data = sel("quoteExactInputSingle(address,address,uint24,uint256,uint160)") + encode(
            ["address", "address", "uint24", "uint256", "uint160"],
            [tin, tout, fee, amt, 0]).hex()
        r, err = call(UNI_QUOTER_V1, data, f"uni_out_{tin[:6]}_{amt}")
        val = None
        if r:
            try:
                val = int(r, 16)
            except Exception:
                err = repr(r)
        return {"token_in": tin, "token_out": tout, "amount_in": str(amt),
                "amount_out": str(val) if val is not None else None, "error": err}

    def sushi_out(tin, tout, amt):
        data = sel("getAmountsOut(uint256,address[])") + encode(
            ["uint256", "address[]"], [amt, [tin, tout]]).hex()
        r, err = call(SUSHI_ROUTER, data, f"sushi_out_{tin[:6]}_{amt}")
        val = None
        if r:
            try:
                val = int(decode(["uint256[]"], bytes.fromhex(strip(r)))[0][-1])
            except Exception as ex:
                err = repr(ex)
        return {"token_in": tin, "token_out": tout, "amount_in": str(amt),
                "amount_out": str(val) if val is not None else None, "error": err}

    uni_fee = int(uni.get("chosen_fee", 500))
    tiers = [("1WETH", WETH, 10**18), ("10WETH", WETH, 10 * 10**18)]
    quotes = []
    leg2 = []
    for label, tin, amt in tiers:
        qv = velo_out(amt, tin) if pool else {"error": "no velo pool"}
        qu = uni_out(tin, USDC_E, amt, uni_fee) if upool else {"error": "no uni pool"}
        qs = sushi_out(tin, USDC_E, amt) if spool else {"error": "no sushi pair"}
        quotes.append({"label": "velo_" + label, "market": "velodrome", "block": out["pinned_block"], **qv})
        quotes.append({"label": "uni_" + label, "market": "uniswap_v3", "block": out["pinned_block"], **qu})
        quotes.append({"label": "sushi_" + label, "market": "sushi_v2", "block": out["pinned_block"], **qs})
        # leg2: sell WETH on one venue, buy back WETH with actual USDC output on another
        def add_leg2(tag, out_amount, venue):
            if not out_amount:
                leg2.append({"label": tag, "error": "no leg1 output"}); return
            if venue == "velodrome" and pool:
                r = velo_out(out_amount, USDC_E)
            elif venue == "uniswap" and upool:
                r = uni_out(USDC_E, WETH, out_amount, uni_fee)
            elif venue == "sushi" and spool:
                r = sushi_out(USDC_E, WETH, out_amount)
            else:
                leg2.append({"label": tag, "error": "venue unavailable"}); return
            leg2.append({"label": tag, "block": out["pinned_block"], **r})
        if qv.get("amount_out"):
            add_leg2("velo1_uni2_" + label, int(qv["amount_out"]), "uniswap")
        if qu.get("amount_out"):
            add_leg2("uni1_velo2_" + label, int(qu["amount_out"]), "velodrome")
    out["quotes"] = quotes
    out["leg2_quotes"] = leg2

    # USDC.e -> WETH direction tiers (buy WETH with stable) for each venue
    rev = []
    for label, amt in (("1000USDCe", 1000 * 10**6), ("10000USDCe", 10000 * 10**6)):
        if pool:
            rev.append({"label": "velo_" + label, "market": "velodrome",
                        "block": out["pinned_block"], **velo_out(amt, USDC_E)})
        if upool:
            rev.append({"label": "uni_" + label, "market": "uniswap_v3",
                        "block": out["pinned_block"],
                        **uni_out(USDC_E, WETH, amt, uni_fee)})
        if spool:
            rev.append({"label": "sushi_" + label, "market": "sushi_v2",
                        "block": out["pinned_block"], **sushi_out(USDC_E, WETH, amt)})
    out["reverse_quotes"] = rev

    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeA-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeA.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("SAVED; requests:", out["request_count_this_script"])
    print(json.dumps(out, ensure_ascii=False, indent=1)[:9000])


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        sys.exit(0 if self_check() else 1)
    main()
