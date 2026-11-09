import json, time, datetime, hashlib
import requests
from eth_utils import keccak
from eth_abi import encode, decode

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\N-BNB\live-20261109T141903Z\raw"
sess = requests.Session(); sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [300]


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def throttle(h):
    n = time.time()
    if h in last and n - last[h] < 0.35:
        time.sleep(0.35 - (n - last[h]))
    last[h] = time.time()


def rpc(method, params, tag, urls=None, retry_alt=True):
    urls = urls or [("dataseed", "https://bsc-dataseed.bnbchain.org"),
                    ("publicnode", "https://bsc-rpc.publicnode.com")]
    err_last = None
    for i, (host, url) in enumerate(urls):
        throttle(host)
        _id[0] += 1
        count[0] += 1
        e = {"n": count[0], "kind": "POST", "host": host, "tag": tag,
             "rpc_method": method, "at_utc": utcnow()}
        try:
            r = sess.post(url, json={"jsonrpc": "2.0", "id": _id[0],
                                     "method": method, "params": params},
                          timeout=25)
            e["http_status"] = r.status_code
            j = r.json()
            if "error" in j:
                e["rpc_error"] = j["error"]; err_last = j["error"]
                log.append(e)
                if retry_alt and i == 0:
                    continue
                return None, err_last
            log.append(e)
            return j.get("result"), None
        except Exception as ex:
            e["error"] = repr(ex); err_last = repr(ex); log.append(e)
            if retry_alt and i == 0:
                continue
            return None, err_last
    return None, err_last


def sel(s):
    return "0x" + keccak(text=s)[:4].hex()


def strip(h):
    return h[2:] if isinstance(h, str) and h.startswith("0x") else h


def call(to, data, tag):
    return rpc("eth_call", [{"to": to, "data": data}, "latest"], tag)


def dec_addr(res):
    return "0x" + strip(res)[24:] if res else None


def dec_str(res):
    if not res:
        return None
    b = bytes.fromhex(strip(res))
    try:
        off = int.from_bytes(b[:32], "big")
        ln = int.from_bytes(b[off:off + 32], "big")
        return b[off + 32:off + 32 + ln].decode("utf-8", "replace")
    except Exception:
        return None


def main():
    out = {"started_at_utc": utcnow()}
    WBNB = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
    USDT = "0x55d398326f99059fF775485246999027B3197955"
    QUOTER = "0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997"
    ROUTER_V2 = "0x10ED43C718714eb63d5aA57B78B54704E256024E"
    FACTORY_V2 = "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"
    bn, _ = rpc("eth_blockNumber", [], "head")
    out["head_block"] = int(bn, 16) if bn else None
    blk = {"tag": "latest"}
    if out["head_block"]:
        blkraw, _ = rpc("eth_getBlockByNumber", [hex(out["head_block"]), False],
                        "headBlock")
        if blkraw:
            out["head_block_time_utc"] = datetime.datetime.fromtimestamp(
                int(blkraw["timestamp"], 16), datetime.timezone.utc).isoformat()

    res = {}
    # --- Market A: new Pancake V3 pool fee=100 USDT/token created block 132597805
    A = "0x89d58f83e57ae74362a83b23086c556a206ffeb2"
    t0 = dec_addr(call(A, sel("token0()"), "A_token0")[0])
    t1 = dec_addr(call(A, sel("token1()"), "A_token1")[0])
    res["market_A_v3_pool"] = {
        "pool": A, "fee": 100, "tickSpacing": 1,
        "created_block": 132597805,
        "created_tx": "0x742846d2908b6fbc00192e4d54bdc937766e6d8aa18ff39b3b282cce685a5410",
        "token0": t0, "token1": t1,
    }
    tokA = t0 if t0 and t0.lower() != USDT.lower() else t1
    if tokA:
        code, _ = rpc("eth_getCode", [tokA, "latest"], "A_token_code")
        res["market_A_v3_pool"]["token_code_bytes"] = (len(code) - 2) // 2 if code else None
        res["market_A_v3_pool"]["token_code_sha256"] = (
            hashlib.sha256(bytes.fromhex(strip(code))).hexdigest() if code else None)
        d, _ = call(tokA, sel("decimals()"), "A_token_decimals")
        res["market_A_v3_pool"]["token_decimals"] = int(strip(d), 16) if d else None
        s, _ = call(tokA, sel("symbol()"), "A_token_symbol")
        res["market_A_v3_pool"]["token_symbol"] = dec_str(s)
        # real quote: 1 USDT -> token via fee=100 (if USDT is token1, direction USDT->token)
        tin, tout = (USDT, tokA)
        data = sel("quoteExactInputSingle((address,address,uint256,uint24,uint160))") + encode(
            ["(address,address,uint256,uint24,uint160)"],
            [(tin, tout, 10**18, 100, 0)]).hex()
        q, err = call(QUOTER, data, "A_quote_1USDT_to_token_fee100")
        qq = {"token_in": tin, "token_out": tout, "amount_in": "1e18",
              "block": out["head_block"], "raw": q, "error": err}
        if q:
            try:
                v = decode(["uint256", "uint160", "uint32", "uint256"],
                           bytes.fromhex(strip(q)))
                qq.update({"amount_out": str(v[0]),
                           "sqrtPriceX96After": str(v[1]),
                           "gasEstimate": str(v[3])})
            except Exception as ex:
                qq["decode_error"] = repr(ex)
        res["market_A_v3_pool"]["quote"] = qq

    # --- Market C: newest V2 pair from factory log (token ...67777 / WBNB)
    C = "0x1c007460942ff6025a75976b71b1596720296704"
    tokC = "0x30ddb30f10126c6614c9865ac45de4718ff67777"
    c = {"pair": C, "created_block": 132600203,
         "created_tx": "0xaa40d9ab07587187a8550102fa5054d94dff65d7b56e27fbe7c6c332b62f2ee6",
         "token": tokC}
    gp, _ = call(FACTORY_V2, sel("getPair(address,address)") + encode(
        ["address", "address"], [WBNB, tokC]).hex(), "C_getPair")
    c["factory_getPair"] = dec_addr(gp)
    c["factory_match"] = bool(dec_addr(gp) and dec_addr(gp).lower() == C.lower())
    rv, err = call(C, sel("getReserves()"), "C_reserves")
    c["getReserves"] = {"raw": rv, "error": err}
    if rv:
        r0, r1, ts = decode(["uint112", "uint112", "uint32"], bytes.fromhex(strip(rv)))
        c["reserves"] = {"reserve0": str(r0), "reserve1": str(r1),
                         "blockTimestampLast": ts}
    for fld, sig in (("token0", "token0()"), ("token1", "token1()")):
        v, _ = call(C, sel(sig), f"C_{fld}")
        c[fld] = dec_addr(v)
    d, _ = call(tokC, sel("decimals()"), "C_token_decimals")
    c["token_decimals"] = int(strip(d), 16) if d else None
    s, _ = call(tokC, sel("symbol()"), "C_token_symbol")
    c["token_symbol"] = dec_str(s)
    data = sel("getAmountsOut(uint256,address[])") + encode(
        ["uint256", "address[]"], [10**16, [WBNB, tokC]]).hex()
    q2, err2 = call(ROUTER_V2, data, "C_quote_001BNB_to_token")
    cq = {"block": out["head_block"], "amount_in_wei": "1e16",
          "raw": q2, "error": err2}
    if q2:
        try:
            cq["amounts_out"] = [str(x) for x in decode(
                ["uint256[]"], bytes.fromhex(strip(q2)))[0]]
        except Exception as ex:
            cq["decode_error"] = repr(ex)
    c["quote"] = cq
    res["market_C_v2_pair"] = c

    # --- Market D: four.meme sample token pair from aggregator discovery
    D = "0xb7f46F38DD432Fd160b0C7965771309838Ae5C7c"
    tokD = "0xf80e4DB5f779788c66E9186E03F5e0C12262ffFF"
    gp, _ = call(FACTORY_V2, sel("getPair(address,address)") + encode(
        ["address", "address"], [WBNB, tokD]).hex(), "D_getPair")
    dd = {"pair_from_aggregator": D, "factory_getPair": dec_addr(gp),
          "factory_match": bool(dec_addr(gp) and dec_addr(gp).lower() == D.lower())}
    rv, err = call(D, sel("getReserves()"), "D_reserves")
    dd["getReserves"] = {"raw": rv, "error": err}
    if rv:
        r0, r1, ts = decode(["uint112", "uint112", "uint32"], bytes.fromhex(strip(rv)))
        dd["reserves"] = {"reserve0": str(r0), "reserve1": str(r1),
                          "blockTimestampLast": ts}
    for fld, sig in (("token0", "token0()"), ("token1", "token1()")):
        v, _ = call(D, sel(sig), f"D_{fld}")
        dd[fld] = dec_addr(v)
    d, _ = call(tokD, sel("decimals()"), "D_token_decimals")
    dd["token_decimals"] = int(strip(d), 16) if d else None
    s, _ = call(tokD, sel("symbol()"), "D_token_symbol")
    dd["token_symbol"] = dec_str(s)
    data = sel("getAmountsOut(uint256,address[])") + encode(
        ["uint256", "address[]"], [10**16, [WBNB, tokD]]).hex()
    q3, err3 = call(ROUTER_V2, data, "D_quote_001BNB_to_token")
    dq = {"block": out["head_block"], "amount_in_wei": "1e16",
          "raw": q3, "error": err3}
    if q3:
        try:
            dq["amounts_out"] = [str(x) for x in decode(
                ["uint256[]"], bytes.fromhex(strip(q3)))[0]]
        except Exception as ex:
            dq["decode_error"] = repr(ex)
    dd["quote"] = dq
    res["market_D_fourmeme_pair"] = dd

    out["verification"] = res
    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\rpc-log3.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\bsc-probe3.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:8000])


if __name__ == "__main__":
    main()
