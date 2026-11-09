import json, time, datetime, hashlib, sys
import requests
from eth_utils import keccak
from eth_abi import encode, decode

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\ETH02\live-20261109T141903Z\raw"
RPC = "https://ethereum-rpc.publicnode.com"
sess = requests.Session(); sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [200]

USDC = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
USDT = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
LUSD = "0x5f98805A4E8be255a32880FDeC7F6728C6568bA0"
UNI_FACTORY = "0x1F98431c8aD98523631AE4a59f267346ea31F984"
QUOTER_V2 = "0x61fFE014bA17989E743c5F6cB21bF9697530B21e"
CURVE_POOL = "0x7ED17e037B7d88A8270c89B3aFA9C38e5218F12b"


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def throttle(h):
    n = time.time()
    if h in last and n - last[h] < 0.35:
        time.sleep(0.35 - (n - last[h]))
    last[h] = time.time()


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
    ok = True
    out = {}
    out["quote_selector"] = sel("quoteExactInputSingle((address,address,uint256,uint24,uint160))")
    ok = ok and out["quote_selector"] == "0xc6a5026a"
    out["getPool_selector"] = sel("getPool(address,address,uint24)")
    ok = ok and out["getPool_selector"] == "0x1698ee82"
    out["get_dy_int128_selector"] = sel("get_dy(int128,int128,uint256)")
    out["get_dy_uint256_selector"] = sel("get_dy(uint256,uint256,uint256)")
    out["coins_selector"] = sel("coins(uint256)")
    enc = encode(["address", "address", "uint256", "uint24", "uint160"],
                 [USDC, LUSD, 1000 * 10**6, 3000, 0])
    out["encode_len"] = len(enc)
    ok = ok and len(enc) == 160
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

    def pool_info(label, pool):
        item = {"pool": pool}
        c, _ = rpc("eth_getCode", [pool, "latest"], "code_" + label)
        item["code_bytes"] = (len(c) - 2) // 2 if c else 0
        item["code_sha256"] = hashlib.sha256(bytes.fromhex(strip(c))).hexdigest() if c else None
        for fld, sig in (("token0", "token0()"), ("token1", "token1()"),
                         ("fee", "fee()"), ("slot0", "slot0()"),
                         ("liquidity", "liquidity()")):
            r, err = call(pool, sel(sig), label + "_" + fld)
            if fld in ("token0", "token1"):
                item[fld] = "0x" + strip(r)[24:] if r else None
            elif fld == "fee":
                item[fld] = int(r, 16) if r else None
            elif fld == "slot0" and r:
                try:
                    v = decode(["uint160", "int24", "uint16", "uint16", "uint16",
                                "uint32", "bool"], bytes.fromhex(strip(r)))
                    item["slot0"] = {"sqrtPriceX96": str(v[0]), "tick": v[1]}
                except Exception as ex:
                    item["slot0_error"] = repr(ex)
            elif fld == "liquidity" and r:
                item["liquidity"] = str(int(r, 16))
            item[fld + "_error"] = err
        return item

    def qv2(tin, tout, amt, fee, tag):
        data = sel("quoteExactInputSingle((address,address,uint256,uint24,uint160))") + encode(
            ["(address,address,uint256,uint24,uint160)"],
            [(tin, tout, amt, fee, 0)]).hex()
        r, err = call(QUOTER_V2, data, tag)
        item = {"amount_in": str(amt), "fee": fee, "amount_out": None, "error": err}
        if r:
            try:
                v = decode(["uint256", "uint160", "uint32", "uint256"],
                           bytes.fromhex(strip(r)))
                item.update({"amount_out": str(v[0]), "gasEstimate": str(v[3]),
                             "ticksCrossed": v[2]})
            except Exception as ex:
                item["decode_error"] = repr(ex)
        return item

    uni = {}
    uni["LUSD_USDC_3000"] = pool_info("uni3000", "0x9902affdd3b8ef60304958c60377110c6d6ab1df")
    uni["LUSD_USDT_500"] = pool_info("uniusdt500", "0x67e887913b13e280538c169f13d169a659a203de")
    out["uniswap_pools"] = uni
    out["buy_quotes"] = [
        {"label": "buy_1000USDC_to_LUSD_fee3000", "block": out["pinned_block"],
         **qv2(USDC, LUSD, 1000 * 10**6, 3000, "buy3000")},
        {"label": "buy_1000USDT_to_LUSD_fee500", "block": out["pinned_block"],
         **qv2(USDT, LUSD, 1000 * 10**6, 500, "buyusdt")},
    ]

    # Curve pool: identity + coin indices + a couple of get_dy attempts (tolerant)
    curve = {"pool": CURVE_POOL}
    c, _ = rpc("eth_getCode", [CURVE_POOL, "latest"], "code_curve")
    curve["code_bytes"] = (len(c) - 2) // 2 if c else 0
    curve["code_sha256"] = hashlib.sha256(bytes.fromhex(strip(c))).hexdigest() if c else None
    coins = {}
    for i in (0, 1):
        r, err = call(CURVE_POOL, sel("coins(uint256)") + encode(["uint256"], [i]).hex(),
                      f"curve_coins_{i}")
        coins[str(i)] = {"raw": r, "address": "0x" + strip(r)[24:] if r else None,
                         "error": err}
    curve["coins"] = coins
    for tag, sig, args in (
            ("curve_get_dy_int128", "get_dy(int128,int128,uint256)",
             ["int128", "int128", "uint256"], [0, 1, 1000 * 10**18]),
            ("curve_get_dy_uint256", "get_dy(uint256,uint256,uint256)",
             ["uint256", "uint256", "uint256"], [0, 1, 1000 * 10**18])):
        r, err = call(CURVE_POOL, sel(sig) + encode(args, args and [0, 1, 1000 * 10**18]).hex(), tag)
        curve[tag] = {"raw": r, "uint": str(int(r, 16)) if r else None, "error": err}
    out["curve_pool"] = curve

    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeB-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeB.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("SAVED; requests:", out["request_count_this_script"])
    print(json.dumps(out, ensure_ascii=False, indent=1)[:8000])


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        sys.exit(0 if self_check() else 1)
    main()
