import json, time, datetime, hashlib
import requests
from eth_utils import keccak
from eth_abi import encode, decode

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\ARB04\live-20261109T141903Z\raw"
sess = requests.Session(); sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [300]
RPCS = [("arb1", "https://arb1.arbitrum.io/rpc")]


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def throttle(h):
    n = time.time()
    if h in last and n - last[h] < 0.3:
        time.sleep(0.3 - (n - last[h]))
    last[h] = time.time()


def rpc(method, params, tag):
    host, url = RPCS[0]
    throttle(host); _id[0] += 1; count[0] += 1
    e = {"n": count[0], "kind": "POST", "host": host, "tag": tag,
         "rpc_method": method, "at_utc": utcnow()}
    try:
        r = sess.post(url, json={"jsonrpc": "2.0", "id": _id[0],
                                 "method": method, "params": params}, timeout=25)
        e["http_status"] = r.status_code
        j = r.json(); log.append(e)
        if "error" in j:
            e["rpc_error"] = j["error"]; return None, j["error"]
        return j.get("result"), None
    except Exception as ex:
        e["error"] = repr(ex); log.append(e); return None, repr(ex)


def strip(h):
    return h[2:] if isinstance(h, str) and h.startswith("0x") else h


def sel(s):
    return "0x" + keccak(text=s)[:4].hex()


def selectors_from_code(code_hex):
    b = bytes.fromhex(strip(code_hex)) if code_hex else b""
    found = set()
    for i in range(len(b) - 4):
        if b[i] == 0x63:
            found.add("0x" + b[i + 1:i + 5].hex())
    return found


def main():
    out = {"started_at_utc": utcnow()}
    STATIC_A = "0x7CFaDFD5645B50bE87d546f42699d863648251ad"
    USDC = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
    POOL = "0x11092be90af6553434e0962cddfd7d84a4444154"
    QUOTER_V1 = "0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6"
    IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"

    bn, _ = rpc("eth_blockNumber", [], "head")
    out["head_block"] = int(bn, 16) if bn else None
    if bn:
        b, _ = rpc("eth_getBlockByNumber", [bn, False], "headBlock")
        if b:
            out["head_block_time_utc"] = datetime.datetime.fromtimestamp(
                int(b["timestamp"], 16), datetime.timezone.utc).isoformat()
    out["pinned_block"] = out["head_block"] - 2 if out["head_block"] else None
    pinned = hex(out["pinned_block"]) if out["pinned_block"] else "latest"

    def call(to, data, tag, block=None):
        return rpc("eth_call", [{"to": to, "data": data}, block or pinned], tag)

    st = {"address": STATIC_A}
    st["impl_slot"], _ = rpc("eth_getStorageAt", [STATIC_A, IMPL_SLOT, "latest"],
                             "static_a_impl_slot")
    impl = "0x" + strip(st["impl_slot"])[24:] if st["impl_slot"] else None
    st["impl"] = impl
    c, _ = rpc("eth_getCode", [impl, "latest"], "static_a_impl_code")
    st["impl_code_bytes"] = (len(c) - 2) // 2 if c else 0
    st["impl_code_sha256"] = hashlib.sha256(bytes.fromhex(strip(c))).hexdigest() if c else None
    sels = selectors_from_code(c)
    wanted = {
        "redeem(uint256,address,bool)": sel("redeem(uint256,address,bool)"),
        "redeem(uint256,address)": sel("redeem(uint256,address)"),
        "redeem(uint256)": sel("redeem(uint256)"),
        "previewRedeem(uint256)": sel("previewRedeem(uint256)"),
        "rate()": sel("rate()"), "aToken()": sel("aToken()"),
        "asset()": sel("asset()"), "totalSupply()": sel("totalSupply()"),
        "balanceOf(address)": sel("balanceOf(address)"),
        "convertToAssets(uint256)": sel("convertToAssets(uint256)"),
        "maxRedeem(address)": sel("maxRedeem(address)"),
    }
    st["selector_presence"] = {k: (v in sels) for k, v in wanted.items()}
    st["selector_count"] = len(sels)

    # static token state
    for fld, sig, kind in (("totalSupply", "totalSupply()", "int"),
                           ("rate", "rate()", "int"),
                           ("aToken", "aToken()", "addr"),
                           ("underlying", "underlying()", "addr"),
                           ("asset", "asset()", "addr")):
        r, err = call(STATIC_A, sel(sig), "static_a_" + fld)
        if kind == "int":
            st[fld] = str(int(r, 16)) if r else None
        else:
            st[fld] = "0x" + strip(r)[24:] if r else None
        st[fld + "_error"] = err
    if st.get("totalSupply"):
        r, err = call(STATIC_A, sel("previewRedeem(uint256)") +
                      encode(["uint256"], [10 ** 6]).hex(), "static_a_previewRedeem_1")
        st["previewRedeem_1"] = str(int(r, 16)) if r else None
        st["previewRedeem_1_error"] = err
    for fld, sig in (("redeem_selectors_test", None),):
        pass
    # aToken balance held by static wrapper -> real NAV backing
    if st.get("aToken"):
        r, err = call(st["aToken"], sel("balanceOf(address)") +
                      encode(["address"], [STATIC_A]).hex(), "static_a_atoken_balance")
        st["aToken_balance"] = str(int(r, 16)) if r else None
        st["aToken_balance_error"] = err
    out["static_a"] = st

    # Uniswap V3 pool state
    pool = {"address": POOL}
    c, _ = rpc("eth_getCode", [POOL, "latest"], "code_pool")
    pool["code_bytes"] = (len(c) - 2) // 2 if c else 0
    pool["code_sha256"] = hashlib.sha256(bytes.fromhex(strip(c))).hexdigest() if c else None
    for fld, sig in (("token0", "token0()"), ("token1", "token1()"), ("fee", "fee()"),
                     ("slot0", "slot0()"), ("liquidity", "liquidity()")):
        r, err = call(POOL, sel(sig), "pool_" + fld)
        if fld in ("token0", "token1"):
            pool[fld] = "0x" + strip(r)[24:] if r else None
        elif fld == "fee":
            pool[fld] = int(r, 16) if r else None
        elif fld == "slot0" and r:
            try:
                v = decode(["uint160", "int24", "uint16", "uint16", "uint16",
                            "uint32", "bool"], bytes.fromhex(strip(r)))
                pool["slot0_decoded"] = {"sqrtPriceX96": str(v[0]), "tick": v[1]}
            except Exception as ex:
                pool["slot0_error"] = repr(ex)
        elif fld == "liquidity" and r:
            pool["liquidity"] = str(int(r, 16))
        pool[fld + "_error"] = err
    out["uni_pool"] = pool

    # quotes at pinned block: buy STATIC_A with USDC and sell back
    quotes = []
    for label, tin, tout, amt in (
            ("100USDC_to_staticA", USDC, STATIC_A, 100 * 10**6),
            ("1000USDC_to_staticA", USDC, STATIC_A, 1000 * 10**6),
            ("10000USDC_to_staticA", USDC, STATIC_A, 10000 * 10**6),
            ("100staticA_to_USDC", STATIC_A, USDC, 100 * 10**6),
            ("1000staticA_to_USDC", STATIC_A, USDC, 1000 * 10**6)):
        data = sel("quoteExactInputSingle(address,address,uint24,uint256,uint160)") + encode(
            ["address", "address", "uint24", "uint256", "uint160"],
            [tin, tout, 100, amt, 0]).hex()
        r, err = call(QUOTER_V1, data, "quote_" + label)
        item = {"label": label, "token_in": tin, "token_out": tout,
                "amount_in": str(amt), "fee": 100, "block": out["pinned_block"],
                "amount_out": str(int(r, 16)) if r else None, "error": err}
        quotes.append(item)
        # chained: for USDC->static quotes, also quote static->USDC of actual output
        if tout == STATIC_A and r:
            out_amt = int(r, 16)
            data2 = sel("quoteExactInputSingle(address,address,uint24,uint256,uint160)") + encode(
                ["address", "address", "uint24", "uint256", "uint160"],
                [STATIC_A, USDC, 100, out_amt, 0]).hex()
            r2, err2 = call(QUOTER_V1, data2, "quote_back_" + label)
            if r2:
                item["sell_back_amount_out"] = str(int(r2, 16))
                item["sell_back_net"] = str(int(r2, 16) - amt)
            else:
                item["sell_back_error"] = err2
    out["quotes"] = quotes

    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeC-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeC.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:9000])


if __name__ == "__main__":
    main()
