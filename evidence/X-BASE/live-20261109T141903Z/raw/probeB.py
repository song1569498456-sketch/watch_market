import json, time, datetime, hashlib, os, sys
import requests
from eth_utils import keccak
from eth_abi import encode, decode

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\X-BASE\live-20261109T141903Z\raw"
os.makedirs(OUT, exist_ok=True)
L1 = "https://ethereum-rpc.publicnode.com"
L2 = "https://mainnet.base.org"
sess = requests.Session(); sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [0]

L1_CBETH = "0xBe9895146f7AF43049ca1c1AE358B0541Ea49704"
L1_WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
B_CBETH = "0x2Ae3F1Ec7F1F5012CFEab0185bfc7aa3cf0DEc22"
B_WETH = "0x4200000000000000000000000000000000000006"
L1_FACTORY = "0x1F98431c8aD98523631AE4a59f267346ea31F984"
B_FACTORY = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"
L1_QUOTER_V2 = "0x61fFE014bA17989E743c5F6cB21bF9697530B21e"
B_QUOTER_V2 = "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a"
B_QUOTER_V1 = "0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6"
L1_BRIDGE = "0x3154Cf16ccdb4C6d922629664174b904d80F2C35"
L2_BRIDGE = "0x4200000000000000000000000000000000000010"


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def throttle(h):
    n = time.time()
    if h in last and n - last[h] < 0.3:
        time.sleep(0.3 - (n - last[h]))
    last[h] = time.time()


def rpc(url, host, method, params, tag, chain):
    throttle(host); _id[0] += 1; count[0] += 1
    e = {"n": count[0], "kind": "POST", "chain": chain, "host": host, "tag": tag,
         "rpc_method": method, "at_utc": utcnow()}
    try:
        r = sess.post(url, json={"jsonrpc": "2.0", "id": _id[0], "method": method,
                                 "params": params}, timeout=30)
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


def addr(r):
    s = strip(r) if r else ""
    return "0x" + s[24:] if len(s) >= 40 and int(s, 16) else None


def self_check():
    ok = True
    out = {}
    for sig, exp in {
        "getPool(address,address,uint24)": "0x1698ee82",
        "slot0()": "0x3850c7bd",
        "liquidity()": "0x1a686502",
        "l1Token()": "0xc01e1bd6",
        "bridge()": "0xe78cea92",
        "paused()": "0x5c975abb",
    }.items():
        got = sel(sig)
        out[sig] = got
        if exp is not None and got != exp:
            ok = False
    enc = encode(["(address,address,uint256,uint24,uint160)"], [(L1_CBETH, L1_WETH, 10**18, 500, 0)])
    out["qv2_payload_len"] = len(enc)
    # addr() guard for empty result
    out["addr_empty_guard"] = (addr("0x") is None and addr(None) is None)
    ok = ok and len(enc) == 160 and out["addr_empty_guard"]
    print(json.dumps({"self_check_ok": ok, "selectors": out}, indent=1))
    return ok


def main():
    out = {"started_at_utc": utcnow()}

    def chain_state(label, url, host, chain):
        cid, _ = rpc(url, host, "eth_chainId", [], "chainId", chain)
        bn, _ = rpc(url, host, "eth_blockNumber", [], "blockNumber", chain)
        st = {"chain_id": int(cid, 16) if cid else None,
              "head_block": int(bn, 16) if bn else None}
        if bn:
            b, _ = rpc(url, host, "eth_getBlockByNumber", [bn, False], "headBlock", chain)
            if b:
                st["head_time_utc"] = datetime.datetime.fromtimestamp(
                    int(b["timestamp"], 16), datetime.timezone.utc).isoformat()
                st["base_fee"] = b.get("baseFeePerGas")
        return st

    l1 = chain_state("ethereum", L1, "ethereum-rpc.publicnode.com", "ethereum")
    l2 = chain_state("base", L2, "mainnet.base.org", "base")
    out["ethereum"] = l1
    out["base"] = l2

    def call(url, host, to, data, tag, chain, block):
        return rpc(url, host, "eth_call", [{"to": to, "data": data}, block], tag, chain)

    def code(url, host, addr_, tag, chain):
        c, _ = rpc(url, host, "eth_getCode", [addr_, "latest"], tag, chain)
        return {"address": addr_, "bytes": (len(c) - 2) // 2 if c else 0,
                "sha256": hashlib.sha256(bytes.fromhex(strip(c))).hexdigest() if c else None}

    def qv2(url, host, quoter, chain, block, tin, tout, amt, fee, tag):
        data = sel("quoteExactInputSingle((address,address,uint256,uint24,uint160))") + encode(
            ["(address,address,uint256,uint24,uint160)"], [(tin, tout, amt, fee, 0)]).hex()
        r, err = call(url, host, quoter, data, tag, chain, block)
        item = {"amount_in": str(amt), "fee": fee, "amount_out": None, "error": err}
        if r and strip(r):
            try:
                v = decode(["uint256", "uint160", "uint32", "uint256"], bytes.fromhex(strip(r)))
                item.update({"amount_out": str(v[0]), "gasEstimate": str(v[3])})
            except Exception as ex:
                item["decode_error"] = repr(ex)
        return item

    def pool_state(url, host, chain, block, pool, label):
        st = {}
        for fld, sig in (("token0", "token0()"), ("token1", "token1()"),
                         ("fee", "fee()"), ("slot0", "slot0()"), ("liquidity", "liquidity()")):
            r, err = call(url, host, pool, sel(sig), label + "_" + fld, chain, block)
            if fld in ("token0", "token1"):
                st[fld] = addr(r)
            elif fld == "fee":
                st[fld] = int(r, 16) if r and strip(r) else None
            elif fld == "slot0" and r and strip(r):
                try:
                    v = decode(["uint160", "int24", "uint16", "uint16", "uint16",
                                "uint32", "bool"], bytes.fromhex(strip(r)))
                    st["slot0"] = {"sqrtPriceX96": str(v[0]), "tick": v[1]}
                except Exception as ex:
                    st["slot0_error"] = repr(ex)
            elif fld == "liquidity" and r and strip(r):
                st["liquidity"] = str(int(r, 16))
            st[fld + "_error"] = err
        return st

    def price_from_sqrt(sqrtp):
        return (sqrtp / 2**96) ** 2 * 10**12  # both tokens 18 decimals -> WETH per cbETH

    def side(url, host, chain, chain_label, cbeth, weth, factory, quoter, bridge, cbeth_fee_order):
        block_num = out[chain_label]["head_block"]
        b = hex(block_num - 2)
        out[chain_label]["pinned_block"] = block_num - 2
        res = {"cbeth_token": code(url, host, cbeth, chain_label + "_cbeth_code", chain),
               "factory": code(url, host, factory, chain_label + "_factory_code", chain),
               "quoter": code(url, host, quoter, chain_label + "_quoter_code", chain)}
        pools = {}
        for fee in (100, 500, 3000):
            r, err = call(url, host, factory, sel("getPool(address,address,uint24)") +
                          encode(["address", "address", "uint24"], [cbeth, weth, fee]).hex(),
                          f"{chain_label}_getPool_{fee}", chain, b)
            pools[str(fee)] = {"pool": addr(r), "error": err}
        res["uni_pools"] = pools
        chosen = next(((int(f), v["pool"]) for f, v in pools.items() if v["pool"]), (None, None))
        res["chosen_fee"] = chosen[0]
        if chosen[1]:
            res["pool"] = chosen[1]
            st = pool_state(url, host, chain, b, chosen[1], chain_label + "_pool")
            res["pool_state"] = st
            if st.get("slot0"):
                res["mid_weth_per_cbeth"] = price_from_sqrt(st["slot0"]["sqrtPriceX96"])
            fee = chosen[0]
            res["quotes"] = [
                {"side": "sell_1_cbeth", "block": out[chain_label]["pinned_block"],
                 **qv2(url, host, quoter, chain, b, cbeth, weth, 10**18, fee, chain_label + "_sell1")},
                {"side": "sell_10_cbeth", "block": out[chain_label]["pinned_block"],
                 **qv2(url, host, quoter, chain, b, cbeth, weth, 10 * 10**18, fee, chain_label + "_sell10")},
                {"side": "buy_1_cbeth_for_1WETH", "block": out[chain_label]["pinned_block"],
                 **qv2(url, host, quoter, chain, b, weth, cbeth, 10**18, fee, chain_label + "_buy1")},
            ]
        br = {"address": bridge, **code(url, host, bridge, chain_label + "_bridge_code", chain)}
        r, err = call(url, host, bridge, sel("paused()"), chain_label + "_bridge_paused", chain, b)
        br["paused"] = bool(int(r, 16)) if r and strip(r) else None
        br["paused_error"] = err
        res["bridge"] = br
        return res

    out["ethereum"]["cfg"] = side(L1, "ethereum-rpc.publicnode.com", "ethereum", "ethereum",
                                  L1_CBETH, L1_WETH, L1_FACTORY, L1_QUOTER_V2, L1_BRIDGE, True)
    out["base"]["cfg"] = side(L2, "mainnet.base.org", "base", "base",
                              B_CBETH, B_WETH, B_FACTORY, B_QUOTER_V2, L2_BRIDGE, False)
    # Base cbETH mapping (l1Token / bridge)
    bres = out["base"]["cfg"]
    for fld, sig in (("l1Token", "l1Token()"), ("bridge", "bridge()")):
        r, err = call(L2, "mainnet.base.org", B_CBETH, sel(sig), "b_cbeth_" + fld, "base",
                      hex(out["base"]["head_block"] - 2))
        bres[fld] = {"value": addr(r), "error": err}
    out["base"]["cbeth_mapping"] = {"l1Token": bres.get("l1Token"),
                                    "bridge": bres.get("bridge"),
                                    "expected_l1_cbeth": L1_CBETH,
                                    "expected_l2_bridge": L2_BRIDGE}

    # cross-chain comparison
    cmp = {}
    try:
        le = out["ethereum"]["cfg"]
        be = out["base"]["cfg"]
        cmp["l1_mid_weth_per_cbeth"] = le.get("mid_weth_per_cbeth")
        cmp["base_mid_weth_per_cbeth"] = be.get("mid_weth_per_cbeth")
        if le.get("mid_weth_per_cbeth") and be.get("mid_weth_per_cbeth"):
            m1, m2 = le["mid_weth_per_cbeth"], be["mid_weth_per_cbeth"]
            cmp["mid_gap_bps"] = round((m2 - m1) / m1 * 10000, 2)
        l1s = next((q for q in le.get("quotes", []) if q.get("side") == "sell_1_cbeth"), {})
        b1s = next((q for q in be.get("quotes", []) if q.get("side") == "sell_1_cbeth"), {})
        if l1s.get("amount_out") and b1s.get("amount_out"):
            l1o, b1o = int(l1s["amount_out"]), int(b1s["amount_out"])
            cmp["executable_sell_1_cbeth"] = {"l1_weth": str(l1o), "base_weth": str(b1o),
                                              "base_vs_l1_bps": round((b1o - l1o) / l1o * 10000, 2)}
    except Exception as ex:
        cmp["error"] = repr(ex)
    out["cross_chain_comparison"] = cmp

    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeB-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeB.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("SAVED; requests:", out["request_count_this_script"])
    print(json.dumps({k: out.get(k) for k in ("started_at_utc", "ethereum", "base",
                                              "cross_chain_comparison")},
                     ensure_ascii=False, indent=1)[:8000])


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        sys.exit(0 if self_check() else 1)
    main()
