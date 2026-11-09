import json, time, datetime, hashlib, sys

import requests
from eth_utils import keccak
from eth_abi import encode, decode

PROXY = "http://127.0.0.1:7897"
RPC = "https://bsc-dataseed.bnbchain.org"
OUT = r"D:\ds-arb-test\watch_market\evidence\N-BNB\live-20261109T141903Z\raw"

sess = requests.Session()
sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})

log = []
req_count = {"total": 0}
last_host_at = {}
_id = [0]


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def throttle(host):
    now = time.time()
    prev = last_host_at.get(host)
    if prev is not None and now - prev < 0.35:
        time.sleep(0.35 - (now - prev))
    last_host_at[host] = time.time()


def record(kind, host, tag, **kw):
    req_count["total"] += 1
    e = {"n": req_count["total"], "kind": kind, "host": host, "tag": tag,
         "at_utc": utcnow()}
    e.update(kw)
    log.append(e)
    return e


def http_get(url, tag, timeout=25):
    host = "api.dexscreener.com" if "dexscreener" in url else (
        "api.venus.io" if "venus" in url else "github.com")
    throttle(host)
    t0 = time.time()
    e = record("GET", host, tag, url=url)
    try:
        r = sess.get(url, timeout=timeout)
        e["http_status"] = r.status_code
        e["elapsed_s"] = round(time.time() - t0, 3)
        e["bytes"] = len(r.content)
        e["sha256"] = hashlib.sha256(r.content).hexdigest()
        try:
            return r.status_code, r.json(), e
        except Exception:
            return r.status_code, None, e
    except Exception as ex:
        e["error"] = repr(ex)
        e["elapsed_s"] = round(time.time() - t0, 3)
        return None, None, e


def rpc(method, params, tag, timeout=25):
    throttle("bsc-dataseed.bnbchain.org")
    _id[0] += 1
    payload = {"jsonrpc": "2.0", "id": _id[0], "method": method, "params": params}
    t0 = time.time()
    e = record("POST", "bsc-dataseed.bnbchain.org", tag,
               rpc_method=method, rpc_params=params)
    try:
        r = sess.post(RPC, json=payload, timeout=timeout)
        e["http_status"] = r.status_code
        e["elapsed_s"] = round(time.time() - t0, 3)
        j = r.json()
        if "error" in j:
            e["rpc_error"] = j["error"]
            return None, j["error"]
        e["rpc_result_sha256"] = hashlib.sha256(
            json.dumps(j.get("result")).encode()).hexdigest()
        return j.get("result"), None
    except Exception as ex:
        e["error"] = repr(ex)
        e["elapsed_s"] = round(time.time() - t0, 3)
        return None, repr(ex)


def sel(sig):
    return "0x" + keccak(text=sig)[:4].hex()


def topic(sig):
    return "0x" + keccak(text=sig).hex()


def call(to, data, tag, block="latest"):
    return rpc("eth_call", [{"to": to, "data": data}, block], tag)


def strip(h):
    return h[2:] if isinstance(h, str) and h.startswith("0x") else h


def main():
    out = {"started_at_utc": utcnow(), "rpc": RPC}
    FAC = "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865"
    QUOTER = "0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997"
    ROUTER_V2 = "0x10ED43C718714eb63d5aA57B78B54704E256024E"
    WBNB = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
    USDT = "0x55d398326f99059fF775485246999027B3197955"
    CAKE = "0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82"

    out["selectors"] = {
        "owner": sel("owner()"),
        "feeSpacing": sel("feeAmountTickSpacing(uint24)"),
        "feeExtra": sel("feeAmountTickSpacingExtraInfo(uint24)"),
        "getPool": sel("getPool(address,address,uint24)"),
        "quoteSingle": sel("quoteExactInputSingle((address,address,uint256,uint24,uint160))"),
        "getAmountsOut": sel("getAmountsOut(uint256,address[])"),
        "slot0": sel("slot0()"),
        "liquidity": sel("liquidity()"),
        "token0": sel("token0()"),
        "token1": sel("token1()"),
        "getPair": sel("getPair(address,address)"),
    }
    out["topics"] = {
        "PoolCreated": topic("PoolCreated(address,address,uint24,int24,address)"),
        "FeeAmountEnabled": topic("FeeAmountEnabled(uint24,int24)"),
        "FeeExtra": topic("FeeAmountExtraInfoUpdated(uint24,bool,bool)"),
        "PairCreated": topic("PairCreated(address,address,address,uint256)"),
    }

    cid, _ = rpc("eth_chainId", [], "chainId")
    out["chain_id_hex"] = cid
    out["chain_id"] = int(cid, 16) if cid else None
    bn, _ = rpc("eth_blockNumber", [], "blockNumber")
    out["head_block"] = int(bn, 16) if bn else None
    if bn:
        blk, _ = rpc("eth_getBlockByNumber", [bn, False], "headBlock")
        if blk:
            out["head_block_info"] = {k: blk.get(k) for k in
                                      ("number", "timestamp", "hash", "gasLimit", "baseFeePerGas")}
            out["head_block_time_utc"] = datetime.datetime.fromtimestamp(
                int(blk["timestamp"], 16), datetime.timezone.utc).isoformat()
    if out.get("head_block"):
        out["pinned_block"] = out["head_block"] - 2
        pinned = hex(out["pinned_block"])
    else:
        out["pinned_block"] = None
        pinned = "latest"

    for name, addr in (("factory_v3", FAC), ("quoter_v2", QUOTER)):
        code, err = rpc("eth_getCode", [addr, "latest"], f"code_{name}")
        out[f"{name}_code"] = {
            "address": addr, "bytes": (len(code) - 2) // 2 if code else None,
            "sha256": hashlib.sha256(bytes.fromhex(strip(code))).hexdigest() if code else None,
            "error": err,
        }

    owner, _ = call(FAC, out["selectors"]["owner"], "factory_owner")
    out["factory_owner"] = "0x" + strip(owner)[24:] if owner else None

    fees = {}
    for fee in (100, 500, 2500, 10000):
        data = out["selectors"]["feeSpacing"] + encode(["uint24"], [fee]).hex()
        res, err = call(FAC, data, f"feeSpacing_{fee}")
        sp = None
        if res:
            try:
                sp = decode(["int256"], bytes.fromhex(strip(res)))[0]
            except Exception as ex:
                err = repr(ex)
        fees[fee] = {"tickSpacing": sp, "error": err}
        data2 = out["selectors"]["feeExtra"] + encode(["uint24"], [fee]).hex()
        res2, err2 = call(FAC, data2, f"feeExtra_{fee}")
        if res2:
            try:
                wl, en = decode(["bool", "bool"], bytes.fromhex(strip(res2)))
                fees[fee].update({"whitelistRequested": wl, "enabled": en})
            except Exception as ex:
                fees[fee]["extra_error"] = repr(ex)
        else:
            fees[fee]["extra_error"] = err2
    out["factory_fee_tiers"] = fees

    pools = {}
    for label, (a, b, fee) in {
        "WBNB_USDT_500": (WBNB, USDT, 500),
        "WBNB_USDT_2500": (WBNB, USDT, 2500),
        "WBNB_CAKE_2500": (WBNB, CAKE, 2500),
        "USDT_CAKE_500": (USDT, CAKE, 500),
        "WBNB_USDT_10000": (WBNB, USDT, 10000),
    }.items():
        data = out["selectors"]["getPool"] + encode(
            ["address", "address", "uint24"], [a, b, fee]).hex()
        res, err = call(FAC, data, f"getPool_{label}", pinned)
        pools[label] = {
            "tokenA": a, "tokenB": b, "fee": fee,
            "pool": ("0x" + strip(res)[24:]) if res and int(res, 16) else None,
            "error": err,
        }
    out["get_pool"] = pools

    # QuoterV2 real quotes at pinned block
    quotes = []
    def quote(label, tin, tout, amt, fee):
        data = out["selectors"]["quoteSingle"] + encode(
            ["(address,address,uint256,uint24,uint160)"],
            [(tin, tout, amt, fee, 0)]).hex()
        res, err = call(QUOTER, data, f"quote_{label}", pinned)
        item = {"label": label, "token_in": tin, "token_out": tout,
                "amount_in": str(amt), "fee": fee, "block": out["pinned_block"],
                "raw": res, "error": err}
        if res:
            try:
                vals = decode(["uint256", "uint160", "uint32", "uint256"],
                              bytes.fromhex(strip(res)))
                item.update({"amount_out": str(vals[0]),
                             "sqrtPriceX96After": str(vals[1]),
                             "initializedTicksCrossed": vals[2],
                             "gasEstimate": str(vals[3])})
            except Exception as ex:
                item["decode_error"] = repr(ex)
        quotes.append(item)
    quote("1WBNB_to_USDT_fee500", WBNB, USDT, 10**18, 500)
    quote("100USDT_to_WBNB_fee500", USDT, WBNB, 100 * 10**18, 500)
    quote("1WBNB_to_USDT_fee2500", WBNB, USDT, 10**18, 2500)
    out["quotes"] = quotes

    # V2 router backstop quote
    data = out["selectors"]["getAmountsOut"] + encode(
        ["uint256", "address[]"], [10**18, [WBNB, USDT]]).hex()
    res, err = call(ROUTER_V2, data, "v2_getAmountsOut_1WBNB_USDT", pinned)
    v2 = {"block": out["pinned_block"], "error": err, "raw": res}
    if res:
        try:
            v2["amounts_out"] = [str(x) for x in decode(["uint256[]"],
                                                        bytes.fromhex(strip(res)))[0]]
        except Exception as ex:
            v2["decode_error"] = repr(ex)
    out["v2_router_quote"] = v2

    # Pool state for WBNB/USDT 500
    pool = pools["WBNB_USDT_500"]["pool"]
    out["pool_state"] = {"pool": pool}
    if pool:
        code, _ = rpc("eth_getCode", [pool, "latest"], "code_pool")
        out["pool_state"]["code_bytes"] = (len(code) - 2) // 2 if code else None
        out["pool_state"]["code_sha256"] = (
            hashlib.sha256(bytes.fromhex(strip(code))).hexdigest() if code else None)
        for fld in ("slot0", "liquidity", "token0", "token1"):
            res, err = call(pool, out["selectors"][fld], f"pool_{fld}", pinned)
            out["pool_state"][fld] = {"raw": res, "error": err}
        try:
            s0 = out["pool_state"]["slot0"]["raw"]
            if s0:
                v = decode(["uint160", "int24", "uint16", "uint16", "uint16",
                            "uint32", "bool"], bytes.fromhex(strip(s0)))
                out["pool_state"]["slot0_decoded"] = {
                    "sqrtPriceX96": str(v[0]), "tick": v[1],
                    "observationIndex": v[2], "observationCardinality": v[3],
                    "observationCardinalityNext": v[4], "feeProtocol": v[5],
                    "unlocked": v[6]}
                # human price token1/token0
                import decimal
                p = (decimal.Decimal(v[0]) / decimal.Decimal(2**96)) ** 2
                out["pool_state"]["spot_price_token1_per_token0"] = str(p)
        except Exception as ex:
            out["pool_state"]["slot0_decode_error"] = repr(ex)
        try:
            if out["pool_state"]["liquidity"]["raw"]:
                out["pool_state"]["liquidity_decoded"] = str(
                    decode(["uint128"], bytes.fromhex(
                        strip(out["pool_state"]["liquidity"]["raw"])))[0])
        except Exception as ex:
            out["pool_state"]["liquidity_decode_error"] = repr(ex)

    # Factory events over recent window (try widening on success)
    events = {}
    if out.get("head_block"):
        for span in (2000, 5000):
            frm = out["head_block"] - span
            topics = [[out["topics"]["PoolCreated"],
                       out["topics"]["FeeAmountEnabled"],
                       out["topics"]["FeeExtra"]]]
            res, err = rpc("eth_getLogs", [{
                "address": FAC, "fromBlock": hex(frm),
                "toBlock": hex(out["head_block"]), "topics": topics}],
                f"factoryEvents_{span}")
            if res is not None:
                events = {"from_block": frm, "to_block": out["head_block"],
                          "count": len(res), "logs": res[:60]}
                break
            events = {"from_block": frm, "to_block": out["head_block"],
                      "error": err}
    out["factory_events"] = events

    # Discovery: dexscreener latest token profiles filtered to bsc
    st, j, e = http_get("https://api.dexscreener.com/token-profiles/latest/v1",
                        "dexscreener_profiles")
    prof = {"http_status": st, "count": None, "bsc": [], "error": e.get("error")}
    if isinstance(j, list):
        prof["count"] = len(j)
        for it in j:
            if str(it.get("chainId", "")).lower() == "bsc":
                prof["bsc"].append({"tokenAddress": it.get("tokenAddress"),
                                    "description": str(it.get("description"))[:160],
                                    "links": [l.get("url") for l in
                                              (it.get("links") or [])][:3]})
    out["dexscreener_profiles"] = prof

    # Venus markets list (BNB chain lending markets)
    st, j, e = http_get("https://api.venus.io/markets?chainId=56",
                        "venus_markets")
    vm = {"http_status": st, "error": e.get("error"), "count": None, "markets": []}
    if isinstance(j, dict) and isinstance(j.get("data"), list):
        vm["count"] = len(j["data"])
        for m in j["data"]:
            vm["markets"].append({
                "symbol": m.get("symbol"), "address": m.get("address"),
                "underlying": (m.get("underlying") or {}).get("address"),
                "supplyApy": m.get("supplyApy"), "borrowApy": m.get("borrowApy"),
                "collateralFactor": m.get("collateralFactor"),
                "liquidity": m.get("liquidity"), "isListed": m.get("isListed"),
            })
    out["venus_markets"] = vm

    out["finished_at_utc"] = utcnow()
    out["request_count"] = req_count["total"]
    with open(OUT + r"\rpc-log.json", "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=1)
    with open(OUT + r"\bsc-probe.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: out[k] for k in (
        "chain_id", "head_block", "head_block_time_utc", "pinned_block",
        "factory_owner", "factory_fee_tiers", "get_pool", "quotes",
        "v2_router_quote", "factory_events", "request_count")},
        ensure_ascii=False, indent=1))
    print("PROFILE_COUNT", out["dexscreener_profiles"].get("count"),
          "BSC_PROFILES", len(out["dexscreener_profiles"].get("bsc", [])))
    print("VENUS_COUNT", out["venus_markets"].get("count"))


if __name__ == "__main__":
    main()
