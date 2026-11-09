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
UNI_FACTORY = "0x1F98431c8aD98523631AE4a59f267346ea31F984"
L1_QUOTER_V2 = "0x61fFE014bA17989E743c5F6cB21bF9697530B21e"
B_QUOTER_V1 = "0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6"
B_QUOTER_V2 = "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a"
L1_BRIDGE = "0x3154Cf16ccdb4C6d922629664174b904d80F2C35"
L1_PORTAL = "0x49048044D57e1C92A77f79988d21Fa8fAF74E97e"
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


def self_check():
    ok = True
    out = {}
    for sig, exp in {
        "getPool(address,address,uint24)": "0x1698ee82",
        "slot0()": "0x3850c7bd",
        "liquidity()": "0x1a686502",
        "l1Token()": "0x49f9a2f0",
        "bridge()": "0xe78cea92",
        "paused()": "0x5c975abb",
    }.items():
        got = sel(sig)
        out[sig] = got
        if exp is not None and got != exp:
            ok = False
    enc = encode(["(address,address,uint256,uint24,uint160)"], [(L1_CBETH, L1_WETH, 10**18, 500, 0)])
    out["qv2_payload_len"] = len(enc)
    ok = ok and len(enc) == 160
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

    def code(url, host, addr, tag, chain):
        c, _ = rpc(url, host, "eth_getCode", [addr, "latest"], tag, chain)
        return {"address": addr, "bytes": (len(c) - 2) // 2 if c else 0,
                "sha256": hashlib.sha256(bytes.fromhex(strip(c))).hexdigest() if c else None}

    def addr(r):
        return "0x" + strip(r)[24:] if r and int(r, 16) else None

    def qv2(url, host, quoter, chain, block, tin, tout, amt, fee, tag):
        data = sel("quoteExactInputSingle((address,address,uint256,uint24,uint160))") + encode(
            ["(address,address,uint256,uint24,uint160)"], [(tin, tout, amt, fee, 0)]).hex()
        r, err = call(url, host, quoter, data, tag, chain, block)
        item = {"amount_in": str(amt), "fee": fee, "amount_out": None, "error": err}
        if r:
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
                st[fld] = int(r, 16) if r else None
            elif fld == "slot0" and r:
                try:
                    v = decode(["uint160", "int24", "uint16", "uint16", "uint16",
                                "uint32", "bool"], bytes.fromhex(strip(r)))
                    st["slot0"] = {"sqrtPriceX96": str(v[0]), "tick": v[1]}
                except Exception as ex:
                    st["slot0_error"] = repr(ex)
            elif fld == "liquidity" and r:
                st["liquidity"] = str(int(r, 16))
            st[fld + "_error"] = err
        return st

    # ---------------- Ethereum side ----------------
    l1b = hex(l1["head_block"] - 2) if l1["head_block"] else "latest"
    out["ethereum"]["pinned_block"] = l1["head_block"] - 2 if l1["head_block"] else None
    l1res = {}
    l1res["cbeth_token"] = code(L1, "ethereum-rpc.publicnode.com", L1_CBETH, "l1_cbeth_code", "ethereum")
    l1res["quoter_v2"] = code(L1, "ethereum-rpc.publicnode.com", L1_QUOTER_V2, "l1_quoter_code", "ethereum")
    l1pools = {}
    for fee in (100, 500, 3000):
        r, err = call(L1, "ethereum-rpc.publicnode.com", UNI_FACTORY,
                      sel("getPool(address,address,uint24)") +
                      encode(["address", "address", "uint24"], [L1_CBETH, L1_WETH, fee]).hex(),
                      f"l1_getPool_{fee}", "ethereum", l1b)
        l1pools[str(fee)] = {"pool": addr(r), "error": err}
    l1res["uni_pools"] = l1pools
    l1chosen = next(((f, v["pool"]) for f, v in l1pools.items() if v["pool"]),
                    (None, None))
    l1res["chosen_fee"] = int(l1chosen[0]) if l1chosen[0] else None
    if l1chosen[1]:
        l1res["pool"] = l1chosen[1]
        l1res["pool_state"] = pool_state(L1, "ethereum-rpc.publicnode.com", "ethereum",
                                         l1b, l1chosen[1], "l1pool")
        l1res["quotes"] = [
            {"side": "sell_cbeth_1", "block": l1["pinned_block"],
             **qv2(L1, "ethereum-rpc.publicnode.com", L1_QUOTER_V2, "ethereum", l1b,
                   L1_CBETH, L1_WETH, 10**18, l1res["chosen_fee"], "l1_sell1")},
            {"side": "sell_cbeth_10", "block": l1["pinned_block"],
             **qv2(L1, "ethereum-rpc.publicnode.com", L1_QUOTER_V2, "ethereum", l1b,
                   L1_CBETH, L1_WETH, 10 * 10**18, l1res["chosen_fee"], "l1_sell10")},
            {"side": "buy_cbeth_1", "block": l1["pinned_block"],
             **qv2(L1, "ethereum-rpc.publicnode.com", L1_QUOTER_V2, "ethereum", l1b,
                   L1_WETH, L1_CBETH, 10**18, l1res["chosen_fee"], "l1_buy1")},
        ]
    # L1 Base bridge (canonical) + portal
    bridge = {"address": L1_BRIDGE, **code(L1, "ethereum-rpc.publicnode.com", L1_BRIDGE,
                                           "l1_bridge_code", "ethereum")}
    r, err = call(L1, "ethereum-rpc.publicnode.com", L1_BRIDGE, sel("paused()"),
                  "l1_bridge_paused", "ethereum", l1b)
    bridge["paused"] = bool(int(r, 16)) if r else None
    bridge["paused_raw_error"] = err
    r, err = call(L1, "ethereum-rpc.publicnode.com", L1_BRIDGE, sel("messenger()"),
                  "l1_bridge_messenger", "ethereum", l1b)
    bridge["messenger"] = addr(r)
    l1res["bridge"] = bridge
    l1res["portal"] = code(L1, "ethereum-rpc.publicnode.com", L1_PORTAL, "l1_portal_code", "ethereum")
    out["ethereum"]["cfg"] = l1res

    # ---------------- Base side ----------------
    l2b = hex(l2["head_block"] - 2) if l2["head_block"] else "latest"
    out["base"]["pinned_block"] = l2["head_block"] - 2 if l2["head_block"] else None
    bres = {}
    bres["cbeth_token"] = code(L2, "mainnet.base.org", B_CBETH, "b_cbeth_code", "base")
    for fld, sig in (("l1Token", "l1Token()"), ("bridge", "bridge()")):
        r, err = call(L2, "mainnet.base.org", B_CBETH, sel(sig), "b_cbeth_" + fld, "base", l2b)
        bres[fld] = {"value": addr(r), "error": err}
    bres["quoter_v1"] = code(L2, "mainnet.base.org", B_QUOTER_V1, "b_quoter_v1_code", "base")
    bres["quoter_v2"] = code(L2, "mainnet.base.org", B_QUOTER_V2, "b_quoter_v2_code", "base")
    quoter_b = B_QUOTER_V2 if bres["quoter_v2"]["bytes"] else B_QUOTER_V1
    bres["quoter_used"] = quoter_b
    bpools = {}
    for fee in (100, 500, 3000):
        r, err = call(L2, "mainnet.base.org", UNI_FACTORY,
                      sel("getPool(address,address,uint24)") +
                      encode(["address", "address", "uint24"], [B_CBETH, B_WETH, fee]).hex(),
                      f"b_getPool_{fee}", "base", l2b)
        bpools[str(fee)] = {"pool": addr(r), "error": err}
    bres["uni_pools"] = bpools
    bchosen = next(((f, v["pool"]) for f, v in bpools.items() if v["pool"]), (None, None))
    bres["chosen_fee"] = int(bchosen[0]) if bchosen[0] else None
    if bchosen[1]:
        bres["pool"] = bchosen[1]
        bres["pool_state"] = pool_state(L2, "mainnet.base.org", "base", l2b, bchosen[1], "bpool")
        bfee = bres["chosen_fee"]
        bres["quotes"] = [
            {"side": "sell_cbeth_1", "block": l2["pinned_block"],
             **qv2(L2, "mainnet.base.org", quoter_b, "base", l2b, B_CBETH, B_WETH,
                   10**18, bfee, "b_sell1")},
            {"side": "sell_cbeth_10", "block": l2["pinned_block"],
             **qv2(L2, "mainnet.base.org", quoter_b, "base", l2b, B_CBETH, B_WETH,
                   10 * 10**18, bfee, "b_sell10")},
            {"side": "buy_cbeth_1", "block": l2["pinned_block"],
             **qv2(L2, "mainnet.base.org", quoter_b, "base", l2b, B_WETH, B_CBETH,
                   10**18, bfee, "b_buy1")},
        ]
    l2bridge = {"address": L2_BRIDGE, **code(L2, "mainnet.base.org", L2_BRIDGE,
                                             "l2_bridge_code", "base")}
    r, err = call(L2, "mainnet.base.org", L2_BRIDGE, sel("paused()"),
                  "l2_bridge_paused", "base", l2b)
    l2bridge["paused"] = bool(int(r, 16)) if r else None
    l2bridge["paused_raw_error"] = err
    bres["bridge"] = l2bridge
    out["base"]["cfg"] = bres

    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeA-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeA.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("SAVED; requests:", out["request_count_this_script"])
    print(json.dumps(out, ensure_ascii=False, indent=1)[:9500])


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        sys.exit(0 if self_check() else 1)
    main()
