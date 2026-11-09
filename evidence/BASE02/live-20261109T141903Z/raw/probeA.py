import json, time, datetime, hashlib, os, re
import requests
from eth_utils import keccak
from eth_abi import encode, decode

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\BASE02\live-20261109T141903Z\raw"
os.makedirs(OUT, exist_ok=True)
sess = requests.Session(); sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [0]
RPCS = [("base-mainnet", "https://mainnet.base.org"),
        ("base-publicnode", "https://base-rpc.publicnode.com")]


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def throttle(h):
    n = time.time()
    if h in last and n - last[h] < 0.3:
        time.sleep(0.3 - (n - last[h]))
    last[h] = time.time()


def http_get(url, tag, host=None):
    host = host or url.split("/")[2]
    throttle(host); count[0] += 1
    e = {"n": count[0], "kind": "GET", "host": host, "tag": tag, "url": url,
         "at_utc": utcnow()}
    try:
        r = sess.get(url, timeout=25)
        e["http_status"] = r.status_code
        e["sha256"] = hashlib.sha256(r.content).hexdigest()
        e["bytes"] = len(r.content)
        log.append(e)
        return r.status_code, r.text
    except Exception as ex:
        e["error"] = repr(ex); log.append(e); return None, ""


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


def dec_str(r):
    if not r:
        return None
    b = bytes.fromhex(strip(r))
    try:
        off = int.from_bytes(b[:32], "big"); ln = int.from_bytes(b[off:off + 32], "big")
        return b[off + 32:off + 32 + ln].decode("utf-8", "replace")
    except Exception:
        return None


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
    IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"

    # official Uniswap SDK addresses (find BASE section)
    st, txt = http_get(
        "https://raw.githubusercontent.com/Uniswap/sdks/main/sdks/sdk-core/src/addresses.ts",
        "uni_sdk_addresses", "raw.githubusercontent.com")
    base_sec = None
    if txt:
        m = re.search(r"const BASE_ADDRESSES[^}]*\}", txt, re.S)
        base_sec = m.group(0) if m else None
    out["uni_sdk_base"] = {"http_status": st, "section": base_sec,
                           "sha256": hashlib.sha256((txt or "").encode()).hexdigest()}
    factory = None
    quoter = None
    if base_sec:
        mf = re.search(r"v3CoreFactoryAddress:\s*'(0x[0-9a-fA-F]{40})'", base_sec)
        mq = re.search(r"quoterAddress:\s*'(0x[0-9a-fA-F]{40})'", base_sec)
        mq2 = re.search(r"quoterV2Address:\s*'(0x[0-9a-fA-F]{40})'", base_sec)
        factory = mf.group(1) if mf else None
        quoter = (mq2 or mq).group(1) if (mq2 or mq) else None
    out["uni_sdk_base_factory"] = factory
    out["uni_sdk_base_quoter"] = quoter

    cid, _ = rpc("eth_chainId", [], "chainId")
    out["chain_id"] = int(cid, 16) if cid else None
    bn, _ = rpc("eth_blockNumber", [], "blockNumber")
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

    def token_meta(addr, label, extra=()):
        meta = {"address": addr}
        c, _ = rpc("eth_getCode", [addr, "latest"], "code_" + label)
        meta["code_bytes"] = (len(c) - 2) // 2 if c else 0
        meta["code_sha256"] = hashlib.sha256(bytes.fromhex(strip(c))).hexdigest() if c else None
        meta["impl_slot"], _ = rpc("eth_getStorageAt", [addr, IMPL_SLOT, "latest"],
                                   label + "_impl_slot")
        for fld, sig in (("name", "name()"), ("symbol", "symbol()"),
                         ("decimals", "decimals()")):
            r, err = call(addr, sel(sig), f"{label}_{fld}")
            meta[fld] = dec_str(r) if fld in ("name", "symbol") else (
                int(strip(r), 16) if r else None)
            meta[fld + "_error"] = err
        for fld, sig in extra:
            data = sel(sig)
            r, err = call(addr, data, f"{label}_{fld}")
            meta[fld] = str(int(r, 16)) if r else None
            meta[fld + "_error"] = err
        return meta

    out["cbETH"] = token_meta(CBETH, "cbeth", extra=[
        ("exchangeRate", "exchangeRate()"),
        ("totalSupply", "totalSupply()"),
        ("l1Token", "l1Token()"),
        ("bridge", "bridge()"),
    ])
    impl = None
    if out["cbETH"].get("impl_slot") and int(out["cbETH"]["impl_slot"], 16):
        impl = "0x" + strip(out["cbETH"]["impl_slot"])[24:]
        c, _ = rpc("eth_getCode", [impl, "latest"], "cbeth_impl_code")
        sels = selectors_from_code(c)
        out["cbETH"]["impl"] = impl
        out["cbETH"]["impl_code_bytes"] = (len(c) - 2) // 2 if c else 0
        out["cbETH"]["impl_code_sha256"] = hashlib.sha256(bytes.fromhex(strip(c))).hexdigest() if c else None
        out["cbETH"]["selector_presence"] = {
            k: (v in sels) for k, v in {
                "exchangeRate()": sel("exchangeRate()"),
                "redeem(uint256)": sel("redeem(uint256)"),
                "unwrap(uint256)": sel("unwrap(uint256)"),
                "burn(address,uint256)": sel("burn(address,uint256)"),
                "mint(address,uint256)": sel("mint(address,uint256)"),
                "l1Token()": sel("l1Token()"), "bridge()": sel("bridge()"),
                "l2Bridge()": sel("l2Bridge()"),
            }.items()}
    out["wstETH"] = token_meta(WSTETH, "wsteth", extra=[
        ("stEthPerToken", "stEthPerToken()"),
        ("getWstETHByStEth_1e18", "getWstETHByStEth(uint256)"),
        ("l1Token", "l1Token()"),
    ])
    out["rETH"] = token_meta(RETH, "reth")
    out["ezETH"] = token_meta(EZETH, "ezeth")

    # dex discovery on Base for cbETH
    st, txt = http_get("https://api.dexscreener.com/latest/dex/tokens/" + CBETH,
                       "ds_cbeth_pairs", "api.dexscreener.com")
    pairs = []
    try:
        j = json.loads(txt)
        for p in (j.get("pairs") or [])[:10]:
            pairs.append({"chainId": p.get("chainId"), "dexId": p.get("dexId"),
                          "pairAddress": p.get("pairAddress"),
                          "baseToken": (p.get("baseToken") or {}).get("address"),
                          "quoteToken": (p.get("quoteToken") or {}).get("address"),
                          "priceUsd": p.get("priceUsd"),
                          "priceNative": p.get("priceNative"),
                          "liquidityUsd": (p.get("liquidity") or {}).get("usd"),
                          "labels": p.get("labels"),
                          "pairCreatedAt": p.get("pairCreatedAt")})
    except Exception as ex:
        out["ds_parse_error"] = repr(ex)
    out["dexscreener_cbeth"] = {"http_status": st, "pairs": pairs}

    # Uniswap V3 on Base: factory + pools for cbETH/WETH
    uni = {"factory": factory, "quoter": quoter}
    if factory:
        c, _ = rpc("eth_getCode", [factory, "latest"], "code_uni_factory")
        uni["factory_code_bytes"] = (len(c) - 2) // 2 if c else 0
        uni["factory_code_sha256"] = hashlib.sha256(bytes.fromhex(strip(c))).hexdigest() if c else None
        uni["pools"] = {}
        for fee in (100, 500, 3000, 10000):
            r, err = call(factory, sel("getPool(address,address,uint24)") +
                          encode(["address", "address", "uint24"], [CBETH, WETH, fee]).hex(),
                          f"uni_getPool_{fee}")
            uni["pools"][str(fee)] = {"pool": "0x" + strip(r)[24:] if r and int(r, 16) else None,
                                      "error": err}
    if quoter:
        c, _ = rpc("eth_getCode", [quoter, "latest"], "code_quoter")
        uni["quoter_code_bytes"] = (len(c) - 2) // 2 if c else 0
    out["uniswap_v3"] = uni

    # pick uniswap pool for cbETH/WETH and read state
    pool = None
    if factory:
        for fee, item in uni.get("pools", {}).items():
            if item.get("pool"):
                pool = item["pool"]; out["chosen_pool_fee"] = fee; break
    pool_state = {"address": pool}
    if pool:
        c, _ = rpc("eth_getCode", [pool, "latest"], "code_pool")
        pool_state["code_bytes"] = (len(c) - 2) // 2 if c else 0
        pool_state["code_sha256"] = hashlib.sha256(bytes.fromhex(strip(c))).hexdigest() if c else None
        for fld, sig in (("token0", "token0()"), ("token1", "token1()"), ("fee", "fee()"),
                         ("slot0", "slot0()"), ("liquidity", "liquidity()")):
            r, err = call(pool, sel(sig), "pool_" + fld)
            if fld in ("token0", "token1"):
                pool_state[fld] = "0x" + strip(r)[24:] if r else None
            elif fld == "fee":
                pool_state[fld] = int(r, 16) if r else None
            elif fld == "slot0" and r:
                try:
                    v = decode(["uint160", "int24", "uint16", "uint16", "uint16",
                                "uint32", "bool"], bytes.fromhex(strip(r)))
                    pool_state["slot0"] = {"sqrtPriceX96": str(v[0]), "tick": v[1]}
                except Exception as ex:
                    pool_state["slot0_error"] = repr(ex)
            elif fld == "liquidity" and r:
                pool_state["liquidity"] = str(int(r, 16))
            pool_state[fld + "_error"] = err
    out["pool_state"] = pool_state

    # real quotes via Uniswap QuoterV2 on Base (if quoter address present)
    quotes = []
    if quoter and pool:
        fee = int(out.get("chosen_pool_fee", 500))
        for label, tin, tout, amt in (
                ("10cbETH_to_WETH", CBETH, WETH, 10 * 10**18),
                ("100cbETH_to_WETH", CBETH, WETH, 100 * 10**18),
                ("1cbETH_to_WETH", CBETH, WETH, 10**18),
                ("10WETH_to_cbETH", WETH, CBETH, 10 * 10**18)):
            data = sel("quoteExactInputSingle((address,address,uint256,uint24,uint160))") + encode(
                ["(address,address,uint256,uint24,uint160)"],
                [(tin, tout, amt, fee, 0)]).hex()
            r, err = call(quoter, data, "quote_" + label)
            item = {"label": label, "token_in": tin, "token_out": tout,
                    "amount_in": str(amt), "fee": fee, "block": out["pinned_block"],
                    "amount_out": None, "error": err}
            if r:
                try:
                    v = decode(["uint256", "uint160", "uint32", "uint256"],
                               bytes.fromhex(strip(r)))
                    item["amount_out"] = str(v[0]); item["gasEstimate"] = str(v[3])
                except Exception as ex:
                    item["decode_error"] = repr(ex)
            quotes.append(item)
    out["quotes"] = quotes

    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeA-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeA.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:9000])


if __name__ == "__main__":
    main()
