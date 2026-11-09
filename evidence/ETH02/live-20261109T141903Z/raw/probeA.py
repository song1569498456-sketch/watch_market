import json, time, datetime, hashlib, os, sys
import requests
from eth_utils import keccak
from eth_abi import encode, decode

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\ETH02\live-20261109T141903Z\raw"
os.makedirs(OUT, exist_ok=True)
RPC = "https://ethereum-rpc.publicnode.com"
sess = requests.Session(); sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [0]

USDC = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
LUSD = "0x5f98805A4E8be255a32880FDeC7F6728C6568bA0"
TROVE_MANAGER = "0xA39739EF8b0231DbFA0DcdA07d7e29faAbCf4bb2"
ACTIVE_POOL = "0xDf9Eb223bAFBE5c5271415C75aeCD68C21fE3D7F"
PRICE_FEED = "0x4c517D4e2C851CA76d7eC94B805269Df0f2201De"
UNI_FACTORY = "0x1F98431c8aD98523631AE4a59f267346ea31F984"
QUOTER_V2 = "0x61fFE014bA17989E743c5F6cB21bF9697530B21e"


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def throttle(h):
    n = time.time()
    if h in last and n - last[h] < 0.35:
        time.sleep(0.35 - (n - last[h]))
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
        return r.status_code, r.text
    except Exception as ex:
        e["error"] = repr(ex); log.append(e); return None, ""


def rpc(method, params, tag):
    throttle("ethereum-rpc.publicnode.com"); _id[0] += 1; count[0] += 1
    e = {"n": count[0], "kind": "POST", "host": "ethereum-rpc.publicnode.com",
         "tag": tag, "rpc_method": method, "at_utc": utcnow()}
    try:
        r = sess.post(RPC, json={"jsonrpc": "2.0", "id": _id[0],
                                 "method": method, "params": params}, timeout=30)
        e["http_status"] = r.status_code
        j = r.json(); log.append(e)
        if "error" in j:
            e["rpc_error"] = j["error"]; return None, j["error"]
        return j.get("result"), None
    except Exception as ex:
        e["error"] = repr(ex); log.append(e); return None, repr(ex)


def sel(s):
    return "0x" + keccak(text=s)[:4].hex()


def strip(h):
    return h[2:] if isinstance(h, str) and h.startswith("0x") else h


def self_check():
    """Offline structural self-check: selectors/encoding/decoding, no network."""
    checks = {}
    known = {
        "getPool(address,address,uint24)": "0x1698ee82",
        "getPair(address,address)": "0xe6a43905",
        "decimals()": "0x313ce567",
        "symbol()": "0x95d89b41",
        "totalSupply()": "0x18160ddd",
        "fetchPrice()": None,
        "getTCR(uint256)": None,
        "getEntireSystemDebt()": None,
        "baseRate()": None,
        "getRedemptionRateWithDecay()": None,
        "getRedemptionFeeWithDecay(uint256)": None,
        "MCR()": None,
    }
    ok = True
    for sig, expect in known.items():
        got = sel(sig)
        checks[sig] = {"selector": got, "expected": expect,
                       "match": (expect is None or got == expect)}
        if expect is not None and got != expect:
            ok = False
    # encode/decode round-trip for quote tuple (QuoterV2 signature known selector check)
    q_sig = "quoteExactInputSingle((address,address,uint256,uint24,uint160))"
    q_sel = sel(q_sig)
    enc = encode(["(address,address,uint256,uint24,uint160)"],
                 [(USDC, LUSD, 1000 * 10**6, 500, 0)])
    checks["quote_selector"] = {"selector": q_sel,
                                "expected_v2": "0xc6a5026a",
                                "match": q_sel == "0xc6a5026a",
                                "payload_bytes": len(enc)}
    if q_sel != "0xc6a5026a":
        ok = False
    # decode known-shape QuoterV2 response
    fake = encode(["uint256", "uint160", "uint32", "uint256"],
                  [123456789, 2**96, 3, 200000])
    v = decode(["uint256", "uint160", "uint32", "uint256"], fake)
    checks["decode_roundtrip"] = {"ok": v[0] == 123456789 and v[2] == 3}
    # one-word decode helper
    checks["uint256_decode"] = {"ok": int.from_bytes((123456).to_bytes(32, "big"), "big") == 123456}
    for v2 in checks.values():
        if v2.get("match") is False or v2.get("ok") is False:
            ok = False
    print(json.dumps({"self_check_ok": ok, "checks": checks}, indent=1))
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
                                      ("number", "timestamp", "hash", "baseFeePerGas")}
            out["head_block_time_utc"] = datetime.datetime.fromtimestamp(
                int(b["timestamp"], 16), datetime.timezone.utc).isoformat()
    out["pinned_block"] = out["head_block"] - 2 if out["head_block"] else None
    pinned = hex(out["pinned_block"]) if out["pinned_block"] else "latest"

    def call(to, data, tag, block=None):
        return rpc("eth_call", [{"to": to, "data": data}, block or pinned], tag)

    def gwei():
        r, _ = rpc("eth_gasPrice", [], "gasPrice")
        return int(r, 16) if r else None

    # 1) Liquity v1 identity + system state
    tm = {"address": TROVE_MANAGER}
    c, _ = rpc("eth_getCode", [TROVE_MANAGER, "latest"], "code_trovermanager")
    tm["code_bytes"] = (len(c) - 2) // 2 if c else 0
    tm["code_sha256"] = hashlib.sha256(bytes.fromhex(strip(c))).hexdigest() if c else None
    pref, _ = rpc("eth_getCode", [PRICE_FEED, "latest"], "code_pricefeed")
    lusd_code, _ = rpc("eth_getCode", [LUSD, "latest"], "code_lusd")
    out["contracts"] = {
        "trove_manager": {"address": TROVE_MANAGER, "code_bytes": tm["code_bytes"],
                          "code_sha256": tm["code_sha256"]},
        "price_feed": {"address": PRICE_FEED,
                       "code_bytes": (len(pref) - 2) // 2 if pref else 0,
                       "code_sha256": hashlib.sha256(bytes.fromhex(strip(pref))).hexdigest() if pref else None},
        "lusd_token": {"address": LUSD,
                       "code_bytes": (len(lusd_code) - 2) // 2 if lusd_code else 0,
                       "code_sha256": hashlib.sha256(bytes.fromhex(strip(lusd_code))).hexdigest() if lusd_code else None},
        "active_pool": {"address": ACTIVE_POOL},
    }
    price, price_err = call(PRICE_FEED, sel("fetchPrice()"), "pricefeed_fetchPrice")
    out["oracle_price_1e18"] = str(int(price, 16)) if price else None
    out["oracle_price_error"] = price_err
    tm_reads = {}
    for fld, sig in (("getEntireSystemDebt", "getEntireSystemDebt()"),
                     ("getEntireSystemColl", "getEntireSystemColl()"),
                     ("baseRate", "baseRate()"),
                     ("getRedemptionRateWithDecay", "getRedemptionRateWithDecay()"),
                     ("MCR", "MCR()"),
                     ("REDEMPTION_FEE_FLOOR", "REDEMPTION_FEE_FLOOR()"),
                     ("LUSD_GAS_COMPENSATION", "LUSD_GAS_COMPENSATION()")):
        r, err = call(TROVE_MANAGER, sel(sig), "tm_" + fld)
        item = {"raw": r, "error": err}
        if r:
            try:
                item["uint"] = str(int(r, 16))
            except Exception:
                pass
        tm_reads[fld] = item
    if out["oracle_price_1e18"]:
        r, err = call(TROVE_MANAGER, sel("getTCR(uint256)") +
                      encode(["uint256"], [int(out["oracle_price_1e18"])]).hex(),
                      "tm_getTCR")
        tm_reads["getTCR"] = {"raw": r, "error": err,
                              "uint": str(int(r, 16)) if r else None}
    # redemption fee with decay for 10 ETH output (ETHdrawn sample)
    r, err = call(TROVE_MANAGER, sel("getRedemptionFeeWithDecay(uint256)") +
                  encode(["uint256"], [10 * 10**18]).hex(), "tm_getRedemptionFeeWithDecay")
    tm_reads["getRedemptionFeeWithDecay_10ETH"] = {"raw": r, "error": err,
                                                   "uint": str(int(r, 16)) if r else None}
    out["trove_manager_state"] = tm_reads
    for fld, sig in (("totalSupply", "totalSupply()"), ("symbol", "symbol()"),
                     ("decimals", "decimals()")):
        r, _ = call(LUSD, sel(sig), "lusd_" + fld)
        if fld == "totalSupply":
            out["lusd_totalSupply"] = str(int(r, 16)) if r else None
        elif fld == "symbol":
            b = bytes.fromhex(strip(r)) if r else b""
            try:
                off = int.from_bytes(b[:32], "big"); ln = int.from_bytes(b[off:off + 32], "big")
                out["lusd_symbol"] = b[off + 32:off + 32 + ln].decode()
            except Exception:
                out["lusd_symbol"] = None
        else:
            out["lusd_decimals"] = int(r, 16) if r else None
    r, _ = call(ACTIVE_POOL, sel("getETH()"), "activepool_getETH")
    out["active_pool_eth"] = str(int(r, 16)) if r else None
    out["gas_price_wei"] = gwei()

    # 2) DEX discovery (aggregator; discovery only)
    st, txt = http_get("https://api.dexscreener.com/latest/dex/tokens/" + LUSD,
                       "ds_lusd_pairs", "api.dexscreener.com")
    pairs = []
    try:
        j = json.loads(txt)
        for p in (j.get("pairs") or [])[:12]:
            pairs.append({"chainId": p.get("chainId"), "dexId": p.get("dexId"),
                          "pairAddress": p.get("pairAddress"),
                          "baseToken": (p.get("baseToken") or {}).get("address"),
                          "quoteToken": (p.get("quoteToken") or {}).get("address"),
                          "priceUsd": p.get("priceUsd"),
                          "liquidityUsd": (p.get("liquidity") or {}).get("usd")})
    except Exception as ex:
        out["ds_parse_error"] = repr(ex)
    out["dexscreener_lusd"] = {"http_status": st, "pairs": pairs}

    # 3) Uniswap V3 pools LUSD/USDC and USDC/WETH
    qc, _ = rpc("eth_getCode", [QUOTER_V2, "latest"], "code_quoter")
    out["quoter_v2"] = {"address": QUOTER_V2,
                        "code_bytes": (len(qc) - 2) // 2 if qc else 0,
                        "code_sha256": hashlib.sha256(bytes.fromhex(strip(qc))).hexdigest() if qc else None}
    pools = {}
    for label, (a, b, fee) in {
        "LUSD_USDC_100": (LUSD, USDC, 100),
        "LUSD_USDC_500": (LUSD, USDC, 500),
        "LUSD_USDC_3000": (LUSD, USDC, 3000),
        "LUSD_USDT_500": (LUSD, "0xdAC17F958D2ee523a2206206994597C13D831ec7", 500),
        "USDC_WETH_500": (USDC, WETH, 500),
    }.items():
        r, err = call(UNI_FACTORY, sel("getPool(address,address,uint24)") +
                      encode(["address", "address", "uint24"], [a, b, fee]).hex(),
                      "uni_getPool_" + label)
        pools[label] = {"tokenA": a, "tokenB": b, "fee": fee,
                        "pool": "0x" + strip(r)[24:] if r and int(r, 16) else None,
                        "error": err}
    out["uni_pools"] = pools

    # choose first LUSD/USDC pool with code/liquidity
    chosen = None
    for label, item in pools.items():
        if not label.startswith("LUSD_USDC") or not item.get("pool"):
            continue
        paddr = item["pool"]
        c, _ = rpc("eth_getCode", [paddr, "latest"], "code_pool_" + label)
        item["code_bytes"] = (len(c) - 2) // 2 if c else 0
        if item["code_bytes"] == 0:
            continue
        state = {}
        for fld, sig in (("token0", "token0()"), ("token1", "token1()"),
                         ("fee", "fee()"), ("slot0", "slot0()"),
                         ("liquidity", "liquidity()")):
            r, err = call(paddr, sel(sig), "pool_" + label + "_" + fld)
            if fld in ("token0", "token1"):
                state[fld] = "0x" + strip(r)[24:] if r else None
            elif fld == "fee":
                state[fld] = int(r, 16) if r else None
            elif fld == "slot0" and r:
                try:
                    v = decode(["uint160", "int24", "uint16", "uint16", "uint16",
                                "uint32", "bool"], bytes.fromhex(strip(r)))
                    state["slot0"] = {"sqrtPriceX96": str(v[0]), "tick": v[1]}
                except Exception as ex:
                    state["slot0_error"] = repr(ex)
            elif fld == "liquidity" and r:
                state["liquidity"] = str(int(r, 16))
            state[fld + "_error"] = err
        item["state"] = state
        if state.get("liquidity") and int(state["liquidity"]) > 0:
            chosen = (label, item)
            break
        if chosen is None:
            chosen = (label, item)
    out["chosen_lusd_pool"] = None if not chosen else {"label": chosen[0], **chosen[1]}

    # 4) quotes: buy LUSD with USDC on chosen pool; ETH exit pool quote USDC/WETH
    quotes = []
    if chosen:
        label, item = chosen
        fee = int(item["fee"])
        def qv2(tin, tout, amt, tag):
            data = sel("quoteExactInputSingle((address,address,uint256,uint24,uint160))") + encode(
                ["(address,address,uint256,uint24,uint160)"],
                [(tin, tout, amt, fee, 0)]).hex()
            r, err = call(QUOTER_V2, data, tag)
            item_q = {"amount_in": str(amt), "fee": fee, "amount_out": None, "error": err}
            if r:
                try:
                    v = decode(["uint256", "uint160", "uint32", "uint256"],
                               bytes.fromhex(strip(r)))
                    item_q.update({"amount_out": str(v[0]), "gasEstimate": str(v[3])})
                except Exception as ex:
                    item_q["decode_error"] = repr(ex)
            return item_q
        for amt_usd in (1000, 10000):
            quotes.append({"label": f"buy_LUSD_with_{amt_usd}USDC", "block": out["pinned_block"],
                           **qv2(USDC, LUSD, amt_usd * 10**6, f"buy_{amt_usd}")})
        # ETH->USDC exit quote for 1 ETH
        if pools["USDC_WETH_500"].get("pool"):
            data = sel("quoteExactInputSingle((address,address,uint256,uint24,uint160))") + encode(
                ["(address,address,uint256,uint24,uint160)"],
                [(WETH, USDC, 10**18, 500, 0)]).hex()
            r, err = call(QUOTER_V2, data, "quote_1ETH_to_USDC")
            item_q = {"label": "sell_1ETH_for_USDC", "block": out["pinned_block"],
                      "amount_in": str(10**18), "fee": 500, "amount_out": None, "error": err}
            if r:
                try:
                    v = decode(["uint256", "uint160", "uint32", "uint256"],
                               bytes.fromhex(strip(r)))
                    item_q["amount_out"] = str(v[0])
                except Exception as ex:
                    item_q["decode_error"] = repr(ex)
            quotes.append(item_q)
    out["quotes"] = quotes

    # 5) protocol redemption math (using read price/rate/floor)
    red = {}
    try:
        price = int(out["oracle_price_1e18"])
        rate = int(tm_reads["getRedemptionRateWithDecay"]["uint"])
        floor = int(tm_reads["REDEMPTION_FEE_FLOOR"]["uint"])
        eth_drawn = lambda lusd_amt: lusd_amt * 10**18 // price
        fee = lambda eth_amt: eth_amt * rate // 10**18
        for amt in (1000, 10000):
            e = eth_drawn(amt * 10**18)
            f = fee(e)
            red[str(amt)] = {"lusd_in": amt, "eth_drawn": str(e),
                             "redemption_rate_1e18": rate,
                             "fee_eth": str(f), "net_eth": str(e - f)}
        red["floor_1e18"] = floor
        red["_note"] = "公式来自 Liquity v1 TroveManager 源码（ETHdrawn=LUSD*1e18/price；fee=ETHdrawn*rate/1e18）；未执行、未计 gas/部分赎回取消"
    except Exception as ex:
        red["error"] = repr(ex)
    out["protocol_redemption_math"] = red

    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeA-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeA.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("SAVED probeA.json; requests:", out["request_count_this_script"])
    print(json.dumps(out, ensure_ascii=False, indent=1)[:9000])


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        ok = self_check()
        sys.exit(0 if ok else 1)
    main()
