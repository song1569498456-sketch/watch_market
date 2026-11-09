import json, time, datetime, hashlib
import requests
from eth_utils import keccak
from eth_abi import encode, decode

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\BASE02\live-20261109T141903Z\raw"
sess = requests.Session(); sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [100]
RPCS = [("base-mainnet", "https://mainnet.base.org"),
        ("base-publicnode", "https://base-rpc.publicnode.com")]


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


def selectors_from_code(code_hex):
    b = bytes.fromhex(strip(code_hex)) if code_hex else b""
    found = set()
    for i in range(len(b) - 4):
        if b[i] == 0x63:
            found.add("0x" + b[i + 1:i + 5].hex())
    return found


def main():
    out = {"started_at_utc": utcnow()}
    CBETH = "0x2Ae3F1Ec7F1F5012CFEab0185bfc7aa3cf0DEc22"
    WETH = "0x4200000000000000000000000000000000000006"
    WSTETH = "0xc1CBa3fCea344f92D9239c08C0568f6F2F0ee452"
    RETH = "0xB6fe221Fe9EeF5aBa221c348bA20A1Bf5e73624c"
    EZETH = "0x2416092f143378750bb29b79eD961ab195CcEea5"
    UNI_FACTORY = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"
    QUOTER = "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a"

    # decode cbETH bridge fields from probeA values (local, no request)
    pa = json.load(open(OUT + r"\probeA.json", encoding="utf-8"))

    def to_addr(v):
        try:
            n = int(v)
            return "0x%040x" % (n & ((1 << 160) - 1))
        except Exception:
            return None

    out["cbeth_l1_refs"] = {
        "l1Token": to_addr(pa["cbETH"].get("l1Token")),
        "bridge": to_addr(pa["cbETH"].get("bridge")),
        "l2Bridge": to_addr(pa["cbETH"].get("l2Bridge")),
    }

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

    # wstETH impl selector inventory (bridge token? any unwrap/rate?)
    wst = {"impl": "0x69ce2505ce515c0203160450157366f927243309"}
    c, _ = rpc("eth_getCode", [wst["impl"], "latest"], "code_wsteth_impl")
    sels = selectors_from_code(c)
    wst["impl_code_bytes"] = (len(c) - 2) // 2 if c else 0
    wst["impl_code_sha256"] = hashlib.sha256(bytes.fromhex(strip(c))).hexdigest() if c else None
    wst["selector_presence"] = {
        k: (v in sels) for k, v in {
            "stEthPerToken()": sel("stEthPerToken()"),
            "getWstETHByStEth(uint256)": sel("getWstETHByStEth(uint256)"),
            "unwrap(uint256)": sel("unwrap(uint256)"),
            "wrap(uint256)": sel("wrap(uint256)"),
            "l1Token()": sel("l1Token()"), "bridge()": sel("bridge()"),
            "l2Bridge()": sel("l2Bridge()"), "burn(address,uint256)": sel("burn(address,uint256)"),
        }.items()}
    out["wstETH_impl"] = wst

    # rETH: selectors + known rate functions
    c, _ = rpc("eth_getCode", [RETH, "latest"], "code_reth")
    sels = selectors_from_code(c)
    reth = {"selector_presence": {
        k: (v in sels) for k, v in {
            "getExchangeRate()": sel("getExchangeRate()"),
            "getRETHValue(uint256)": sel("getRETHValue(uint256)"),
            "getEthValue(uint256)": sel("getEthValue(uint256)"),
            "burn(uint256)": sel("burn(uint256)"),
            "l1Token()": sel("l1Token()"),
        }.items()}}
    for fld, sig in (("getExchangeRate", "getExchangeRate()"),
                     ("getRETHValue_1e18", "getRETHValue(uint256)")):
        data = sel(sig)
        if "uint256" in sig:
            data += encode(["uint256"], [10 ** 18]).hex()
        r, err = call(RETH, data, "reth_" + fld)
        reth[fld] = str(int(r, 16)) if r else None
        reth[fld + "_error"] = err
    out["rETH"] = reth

    # ezETH: selectors
    ez_impl = "0xb370a0bd64daf1c6b04eaf01c1dedf7c6bce30f7"
    c, _ = rpc("eth_getCode", [ez_impl, "latest"], "code_ezeth_impl")
    sels = selectors_from_code(c)
    out["ezETH_impl"] = {"impl": ez_impl,
                         "impl_code_bytes": (len(c) - 2) // 2 if c else 0,
                         "selector_presence": {
                             k: (v in sels) for k, v in {
                                 "getRate()": sel("getRate()"),
                                 "convertToETH(address,uint256)": sel("convertToETH(address,uint256)"),
                                 "exchangeRate()": sel("exchangeRate()"),
                                 "l1Token()": sel("l1Token()"),
                                 "burn(address,uint256)": sel("burn(address,uint256)"),
                             }.items()}}

    # Uniswap V3 cbETH/WETH fee=500 pool: state + quotes
    def get_pool(a, b, fee, tag):
        r, err = call(UNI_FACTORY, sel("getPool(address,address,uint24)") +
                      encode(["address", "address", "uint24"], [a, b, fee]).hex(), tag)
        return ("0x" + strip(r)[24:] if r and int(r, 16) else None), err

    pools = {}
    for label, (a, b, fee) in {
        "cbETH_WETH_500": (CBETH, WETH, 500),
        "wstETH_WETH_500": (WSTETH, WETH, 500),
        "rETH_WETH_500": (RETH, WETH, 500),
    }.items():
        pool, err = get_pool(a, b, fee, "getpool_" + label)
        pools[label] = {"pool": pool, "error": err}
    out["pools"] = pools

    # state for cbETH fee=500 pool
    pool = pools["cbETH_WETH_500"]["pool"]
    ps = {"address": pool}
    if pool:
        for fld, sig in (("token0", "token0()"), ("token1", "token1()"),
                         ("fee", "fee()"), ("slot0", "slot0()"),
                         ("liquidity", "liquidity()")):
            r, err = call(pool, sel(sig), "pool500_" + fld)
            if fld in ("token0", "token1"):
                ps[fld] = "0x" + strip(r)[24:] if r else None
            elif fld == "fee":
                ps[fld] = int(r, 16) if r else None
            elif fld == "slot0" and r:
                try:
                    v = decode(["uint160", "int24", "uint16", "uint16", "uint16",
                                "uint32", "bool"], bytes.fromhex(strip(r)))
                    ps["slot0"] = {"sqrtPriceX96": str(v[0]), "tick": v[1]}
                except Exception as ex:
                    ps["slot0_error"] = repr(ex)
            elif fld == "liquidity" and r:
                ps["liquidity"] = str(int(r, 16))
            ps[fld + "_error"] = err
    out["cbETH_pool500_state"] = ps

    def quote(tin, tout, amt, fee, tag):
        data = sel("quoteExactInputSingle((address,address,uint256,uint24,uint160))") + encode(
            ["(address,address,uint256,uint24,uint160)"],
            [(tin, tout, amt, fee, 0)]).hex()
        r, err = call(QUOTER, data, tag)
        item = {"amount_in": str(amt), "fee": fee, "amount_out": None, "error": err}
        if r:
            try:
                v = decode(["uint256", "uint160", "uint32", "uint256"],
                           bytes.fromhex(strip(r)))
                item["amount_out"] = str(v[0]); item["gasEstimate"] = str(v[3])
                item["ticks_crossed"] = v[2]
            except Exception as ex:
                item["decode_error"] = repr(ex)
        return item

    qs = {}
    for label, tin, tout, amt, fee in (
            ("1cbETH_to_WETH_500", CBETH, WETH, 10**18, 500),
            ("10cbETH_to_WETH_500", CBETH, WETH, 10 * 10**18, 500),
            ("100cbETH_to_WETH_500", CBETH, WETH, 100 * 10**18, 500),
            ("10WETH_to_cbETH_500", WETH, CBETH, 10 * 10**18, 500),
            ("1wstETH_to_WETH_500", WSTETH, WETH, 10**18, 500),
            ("10wstETH_to_WETH_500", WSTETH, WETH, 10 * 10**18, 500),
            ("1rETH_to_WETH_500", RETH, WETH, 10**18, 500),
            ("10rETH_to_WETH_500", RETH, WETH, 10 * 10**18, 500)):
        qs[label] = quote(tin, tout, amt, fee, "quote_" + label)
    out["quotes"] = qs

    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeB-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeB.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:9000])


if __name__ == "__main__":
    main()
