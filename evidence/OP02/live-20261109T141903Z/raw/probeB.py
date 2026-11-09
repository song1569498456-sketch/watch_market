import json, time, datetime, hashlib, sys
import requests
from eth_utils import keccak
from eth_abi import encode, decode

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\OP02\live-20261109T141903Z\raw"
RPC = "https://mainnet.optimism.io"
sess = requests.Session(); sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [300]

WETH = "0x4200000000000000000000000000000000000006"
USDC_E = "0x7F5c764cBc14f9669B88837ca1490cCa17c31607"
USDC = "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85"
VELO_FACTORY = "0xF1046053aa5682b4F9a81b5481394DA16BE5FF5a"
UNI_FACTORY = "0x1F98431c8aD98523631AE4a59f267346ea31F984"
UNI_QUOTER_V1 = "0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6"


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def throttle(h):
    n = time.time()
    if h in last and n - last[h] < 0.3:
        time.sleep(0.3 - (n - last[h]))
    last[h] = time.time()


def rpc(method, params, tag):
    throttle("mainnet.optimism.io"); _id[0] += 1; count[0] += 1
    e = {"n": count[0], "kind": "POST", "host": "mainnet.optimism.io", "tag": tag,
         "rpc_method": method, "at_utc": utcnow()}
    try:
        r = sess.post(RPC, json={"jsonrpc": "2.0", "id": _id[0],
                                 "method": method, "params": params}, timeout=25)
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
    out = {"getPool_bool": sel("getPool(address,address,bool)"),
           "getAmountOut": sel("getAmountOut(uint256,address)"),
           "isPaused": sel("isPaused(address)"),
           "getFee": sel("getFee(address)"),
           "getPool_uint24": sel("getPool(address,address,uint24)"),
           "quote_single": sel("quoteExactInputSingle(address,address,uint24,uint256,uint160)")}
    ok = out["getPool_uint24"] == "0x1698ee82"
    ok = ok and len(encode(["uint256", "address"], [1, WETH])) == 64
    print(json.dumps({"self_check_ok": ok, "out": out}, indent=1))
    return ok


def main():
    out = {"started_at_utc": utcnow()}
    bn, _ = rpc("eth_blockNumber", [], "head")
    out["head_block"] = int(bn, 16) if bn else None
    if bn:
        b, _ = rpc("eth_getBlockByNumber", [bn, False], "headBlock")
        if b:
            out["head_block_time_utc"] = datetime.datetime.fromtimestamp(
                int(b["timestamp"], 16), datetime.timezone.utc).isoformat()
    pinned = hex(out["head_block"] - 2) if out["head_block"] else "latest"
    out["pinned_block"] = out["head_block"] - 2 if out["head_block"] else None

    def call(to, data, tag):
        return rpc("eth_call", [{"to": to, "data": data}, pinned], tag)

    def code(addr, tag):
        c, _ = rpc("eth_getCode", [addr, "latest"], tag)
        return {"bytes": (len(c) - 2) // 2 if c else 0,
                "sha256": hashlib.sha256(bytes.fromhex(strip(c))).hexdigest() if c else None}

    def dec_addr(r):
        return "0x" + strip(r)[24:] if r and int(r, 16) else None

    # ---- Velodrome pools (volatile main pair; stable as fallback) ----
    velo = {}
    for name, stable in (("volatile", False), ("stable", True)):
        r, err = call(VELO_FACTORY, sel("getPool(address,address,bool)") +
                      encode(["address", "address", "bool"], [WETH, USDC_E, stable]).hex(),
                      "velo_getPool_" + name)
        velo[name] = {"pool": dec_addr(r), "error": err}
    out["velo_pools"] = velo
    target = None
    for name in ("volatile", "stable"):
        if velo[name]["pool"]:
            target = (name, velo[name]["pool"])
            break
    if target:
        name, paddr = target
        item = {"name": name, "address": paddr, **code(paddr, "code_velo_pool")}
        for fld, sig in (("token0", "token0()"), ("token1", "token1()")):
            r, _ = call(paddr, sel(sig), "velo_" + fld)
            item[fld] = dec_addr(r)
        r, _ = call(paddr, sel("getReserves()"), "velo_reserves")
        if r:
            try:
                r0, r1, ts = decode(["uint112", "uint112", "uint32"], bytes.fromhex(strip(r)))
                item["reserves"] = {"reserve0": str(r0), "reserve1": str(r1), "ts": ts}
            except Exception as ex:
                item["reserves_decode_error"] = repr(ex)
        r, _ = call(VELO_FACTORY, sel("isPaused(address)") +
                    encode(["address"], [paddr]).hex(), "velo_isPaused")
        item["isPaused"] = bool(int(r, 16)) if r else None
        r, _ = call(VELO_FACTORY, sel("getFee(address)") +
                    encode(["address"], [paddr]).hex(), "velo_getFee")
        item["getFee_raw"] = str(int(r, 16)) if r else None
        # getAmountOut sample quotes
        for amt, label in ((10**18, "1WETH"), (10 * 10**18, "10WETH")):
            data = sel("getAmountOut(uint256,address)") + encode(
                ["uint256", "address"], [amt, WETH]).hex()
            r, err = call(paddr, data, "velo_out_" + label)
            item["quote_" + label] = {"amount_out": str(int(r, 16)) if r else None,
                                      "error": err}
        data = sel("getAmountOut(uint256,address)") + encode(
            ["uint256", "address"], [1000 * 10**6, USDC_E]).hex()
        r, err = call(paddr, data, "velo_out_1000USDCe")
        item["quote_1000USDCe"] = {"amount_out": str(int(r, 16)) if r else None, "error": err}
        out["velo_pool_state"] = item

    # ---- Uniswap V3 pools for WETH/USDC.e ----
    uni = {}
    for fee in (100, 500, 3000):
        r, err = call(UNI_FACTORY, sel("getPool(address,address,uint24)") +
                      encode(["address", "address", "uint24"], [WETH, USDC_E, fee]).hex(),
                      f"uni_getPool_{fee}")
        uni[str(fee)] = {"pool": dec_addr(r), "error": err}
    out["uni_pools"] = uni
    uni_detail = {}
    for fee, item in uni.items():
        paddr = item.get("pool")
        if not paddr:
            continue
        det = {"fee": int(fee), "address": paddr, **code(paddr, "code_uni_pool_" + fee)}
        for fld, sig in (("token0", "token0()"), ("token1", "token1()"),
                         ("fee", "fee()"), ("liquidity", "liquidity()")):
            r, _ = call(paddr, sel(sig), f"uni_{fee}_{fld}")
            if fld in ("token0", "token1"):
                det[fld] = dec_addr(r)
            elif fld == "fee":
                det[fld] = int(r, 16) if r else None
            elif fld == "liquidity":
                det[fld] = str(int(r, 16)) if r else None
        r, _ = call(paddr, sel("slot0()"), f"uni_{fee}_slot0")
        if r:
            try:
                v = decode(["uint160", "int24", "uint16", "uint16", "uint16",
                            "uint32", "bool"], bytes.fromhex(strip(r)))
                det["slot0"] = {"sqrtPriceX96": str(v[0]), "tick": v[1]}
            except Exception:
                pass
        # quote 1 WETH -> USDC.e for this pool
        data = sel("quoteExactInputSingle(address,address,uint24,uint256,uint160)") + encode(
            ["address", "address", "uint24", "uint256", "uint160"],
            [WETH, USDC_E, int(fee), 10**18, 0]).hex()
        r, err = call(UNI_QUOTER_V1, data, f"uni_quote_1WETH_{fee}")
        det["quote_1WETH"] = {"amount_out": str(int(r, 16)) if r else None, "error": err}
        uni_detail[fee] = det
    out["uni_pool_details"] = uni_detail

    # ---- reference: Uniswap V3 WETH/native USDC 500 quote ----
    r, _ = call(UNI_FACTORY, sel("getPool(address,address,uint24)") +
                encode(["address", "address", "uint24"], [WETH, USDC, 500]).hex(),
                "uni_ref_getPool")
    ref_pool = dec_addr(r)
    out["reference_pool"] = ref_pool
    if ref_pool:
        data = sel("quoteExactInputSingle(address,address,uint24,uint256,uint160)") + encode(
            ["address", "address", "uint24", "uint256", "uint160"],
            [WETH, USDC, 500, 10**18, 0]).hex()
        r, err = call(UNI_QUOTER_V1, data, "uni_ref_quote_1WETH")
        out["reference_1WETH_to_nativeUSDC"] = {
            "amount_out": str(int(r, 16)) if r else None, "error": err}
        data = sel("quoteExactInputSingle(address,address,uint24,uint256,uint160)") + encode(
            ["address", "address", "uint24", "uint256", "uint160"],
            [USDC, WETH, 500, 1000 * 10**6, 0]).hex()
        r, err = call(UNI_QUOTER_V1, data, "uni_ref_quote_1000USDC")
        out["reference_1000USDC_to_WETH"] = {
            "amount_out": str(int(r, 16)) if r else None, "error": err}

    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeB-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeB.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("SAVED; requests:", out["request_count_this_script"])
    print(json.dumps(out, ensure_ascii=False, indent=1)[:9000])


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        sys.exit(0 if self_check() else 1)
    main()
