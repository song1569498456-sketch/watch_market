import json, time, datetime, hashlib, os, re
import requests
from eth_utils import keccak
from eth_abi import encode, decode

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\N-OP\live-20261109T141903Z\raw"
os.makedirs(OUT, exist_ok=True)
sess = requests.Session(); sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [0]

RPCS = [("optimism-mainnet", "https://mainnet.optimism.io"),
        ("optimism-publicnode", "https://optimism-rpc.publicnode.com")]


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def throttle(h):
    n = time.time()
    if h in last and n - last[h] < 0.35:
        time.sleep(0.35 - (n - last[h]))
    last[h] = time.time()


def http_get(url, tag, host=None, headers=None, timeout=25):
    host = host or url.split("/")[2]
    throttle(host); count[0] += 1
    e = {"n": count[0], "kind": "GET", "host": host, "tag": tag, "url": url,
         "at_utc": utcnow()}
    for attempt in range(3):
        try:
            r = sess.get(url, timeout=timeout, headers=headers)
            e["http_status"] = r.status_code
            e["bytes"] = len(r.content)
            e["sha256"] = hashlib.sha256(r.content).hexdigest()
            log.append(e)
            return r.status_code, r.text
        except Exception as ex:
            e["error_attempt_%d" % attempt] = repr(ex)
            time.sleep(0.5)
    log.append(e)
    return None, ""


def rpc(method, params, tag, timeout=25):
    err_last = None
    for host, url in RPCS:
        throttle(host); _id[0] += 1; count[0] += 1
        e = {"n": count[0], "kind": "POST", "host": host, "tag": tag,
             "rpc_method": method, "at_utc": utcnow()}
        try:
            r = sess.post(url, json={"jsonrpc": "2.0", "id": _id[0],
                                     "method": method, "params": params},
                          timeout=timeout)
            e["http_status"] = r.status_code
            j = r.json(); log.append(e)
            if "error" in j:
                e["rpc_error"] = j["error"]; err_last = j["error"]
                continue
            return j.get("result"), None
        except Exception as ex:
            e["error"] = repr(ex); err_last = repr(ex); log.append(e)
            continue
    return None, err_last


def strip(h):
    return h[2:] if isinstance(h, str) and h.startswith("0x") else h


def sel(s):
    return "0x" + keccak(text=s)[:4].hex()


def topic(s):
    return "0x" + keccak(text=s).hex()


def main():
    out = {"started_at_utc": utcnow()}
    CHAIN = "10"
    WETH = "0x4200000000000000000000000000000000000006"
    USDC = "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85"
    USDC_E = "0x7F5c764cBc14f9669B88837ca1490cCa17c31607"
    USDT = "0x94b008aA00579c1307B0EF2c499aD98a8ce58e58"
    OP = "0x4200000000000000000000000000000000000042"
    AAVE_POOL = "0x794a61358D6845594F94dc1DB02A252b5b4814aD"
    AAVE_PROVIDER = "0xa97684ead0e402dC232d5A977953DF7ECBaB3CDb"
    UNI_FACTORY = "0x1F98431c8aD98523631AE4a59f267346ea31F984"
    IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
    ADMIN_SLOT = "0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103"

    cid, _ = rpc("eth_chainId", [], "chainId")
    out["chain_id"] = int(cid, 16) if cid else None
    bn, _ = rpc("eth_blockNumber", [], "blockNumber")
    out["head_block"] = int(bn, 16) if bn else None
    if bn:
        b, _ = rpc("eth_getBlockByNumber", [bn, False], "headBlock")
        if b:
            out["head_block_info"] = {k: b.get(k) for k in
                                      ("number", "timestamp", "hash", "gasLimit", "baseFeePerGas")}
            out["head_block_time_utc"] = datetime.datetime.fromtimestamp(
                int(b["timestamp"], 16), datetime.timezone.utc).isoformat()
    out["pinned_block"] = out["head_block"] - 2 if out["head_block"] else None
    pinned = hex(out["pinned_block"]) if out["pinned_block"] else "latest"

    def call(to, data, tag, block="latest"):
        return rpc("eth_call", [{"to": to, "data": data}, block], tag)

    def code(addr, tag):
        c, _ = rpc("eth_getCode", [addr, "latest"], tag)
        return {"address": addr,
                "bytes": (len(c) - 2) // 2 if c else 0,
                "sha256": hashlib.sha256(bytes.fromhex(strip(c))).hexdigest() if c else None}

    # --- HTTP official sources ---
    docs = {}
    urls = {
        "uni_deploys": "https://raw.githubusercontent.com/Uniswap/v3-periphery/main/deploys.md",
        "aave_op_addrbook": "https://raw.githubusercontent.com/bgd-labs/aave-address-book/main/src/AaveV3Optimism.sol",
        "aave_op_assets": "https://raw.githubusercontent.com/bgd-labs/aave-address-book/main/src/AaveV3OptimismAssets.sol",
        "superchain_op_toml": "https://raw.githubusercontent.com/ethereum-optimism/superchain-registry/main/superchain/configs/mainnet/op.toml",
        "op_releases_atom": "https://github.com/ethereum-optimism/optimism/releases.atom",
    }
    for key, url in urls.items():
        st, txt = http_get(url, key)
        docs[key] = {"http_status": st, "chars": len(txt or ""),
                     "sha256": hashlib.sha256((txt or "").encode()).hexdigest()}
        open(OUT + "\\" + key + ".txt", "w", encoding="utf-8").write(txt or "")

    # extract Uniswap OP addresses from deploys.md
    uni = open(OUT + r"\uni_deploys.txt", encoding="utf-8", errors="replace").read()
    out["uni_op_addresses"] = {}
    for m in re.finditer(r"\|[^|\n]*\|\s*(0x[0-9a-fA-F]{40})[^|\n]*\|", uni):
        pass
    op_sec = None
    idx = uni.find("Optimism")
    if idx >= 0:
        op_sec = uni[idx:idx + 4000]
    if op_sec:
        for line in op_sec.splitlines()[:80]:
            mm = re.findall(r"0x[0-9a-fA-F]{40}", line)
            if mm:
                out["uni_op_addresses"].setdefault("lines", []).append(
                    {"line": line.strip()[:160], "addresses": mm[:3]})

    # --- Aave identity ---
    out["aave_pool_proxy"] = code(AAVE_POOL, "code_aave_pool")
    out["aave_pool_impl"], _ = rpc("eth_getStorageAt", [AAVE_POOL, IMPL_SLOT, "latest"],
                                   "aave_impl_slot")
    out["aave_pool_admin"], _ = rpc("eth_getStorageAt", [AAVE_POOL, ADMIN_SLOT, "latest"],
                                    "aave_admin_slot")
    gp, _ = call(AAVE_PROVIDER, sel("getPool()"), "aave_provider_getPool")
    out["aave_provider_getPool"] = "0x" + strip(gp)[24:] if gp else None
    rl, err = call(AAVE_POOL, sel("getReservesList()"), "aave_reservesList")
    reserves = []
    if rl:
        try:
            reserves = ["0x" + a.lower() for a in decode(["address[]"],
                                                         bytes.fromhex(strip(rl)))[0]]
        except Exception as ex:
            out["aave_reservesList_decode_error"] = repr(ex)
    out["aave_reserves"] = reserves
    out["aave_reserves_count"] = len(reserves)

    # --- Uniswap V3 factory identity ---
    out["uni_factory"] = code(UNI_FACTORY, "code_uni_factory")
    owner, _ = call(UNI_FACTORY, sel("owner()"), "uni_owner")
    out["uni_owner"] = "0x" + strip(owner)[24:] if owner else None
    fees = {}
    for fee in (100, 500, 3000, 10000):
        r, err = call(UNI_FACTORY, sel("feeAmountTickSpacing(uint24)") +
                      encode(["uint24"], [fee]).hex(), f"uni_fee_{fee}", pinned)
        sp = None
        if r:
            try:
                sp = decode(["int256"], bytes.fromhex(strip(r)))[0]
            except Exception as ex:
                err = repr(ex)
        fees[fee] = {"tickSpacing": sp, "error": err}
    out["uni_fee_tiers"] = fees
    pools = {}
    for label, (a, b, fee) in {
        "WETH_USDC_500": (WETH, USDC, 500),
        "WETH_USDCe_500": (WETH, USDC_E, 500),
        "USDC_USDT_100": (USDC, USDT, 100),
        "OP_WETH_3000": (OP, WETH, 3000),
    }.items():
        r, err = call(UNI_FACTORY, sel("getPool(address,address,uint24)") +
                      encode(["address", "address", "uint24"], [a, b, fee]).hex(),
                      "uni_getPool_" + label, pinned)
        pools[label] = {"tokenA": a, "tokenB": b, "fee": fee,
                        "pool": ("0x" + strip(r)[24:]) if r and int(r, 16) else None,
                        "error": err}
    out["uni_getPool"] = pools

    # --- Uniswap V3 PoolCreated events over recent window ---
    POOLCREATED = topic("PoolCreated(address,address,uint24,int24,address)")
    scan = {"attempts": []}
    got = None
    if out.get("head_block"):
        for span in (5000, 1000, 200):
            frm = out["head_block"] - span
            r, err = rpc("eth_getLogs",
                         [{"address": UNI_FACTORY, "fromBlock": hex(frm),
                           "toBlock": hex(out["head_block"]),
                           "topics": [POOLCREATED]}],
                         f"uni_poolcreated_{span}")
            scan["attempts"].append({"span": span, "from": frm,
                                     "to": out["head_block"],
                                     "count": len(r) if r is not None else None,
                                     "error": err})
            if r is not None:
                got = (frm, out["head_block"], r)
                break
    if got:
        frm, to, logs = got
        scan["success"] = {"from_block": frm, "to_block": to, "count": len(logs)}
        parsed = []
        for lg in logs[-10:]:
            t = lg["topics"]
            fee = int(t[3], 16) & 0xFFFFFF
            data = bytes.fromhex(strip(lg["data"]))
            tick = decode(["int256"], data[:32])[0]
            pool = "0x" + strip(decode(["address"], data[32:64])[0])
            parsed.append({"block": int(lg["blockNumber"], 16),
                           "tx": lg["transactionHash"],
                           "pool": pool,
                           "token0": "0x" + strip(t[1])[24:],
                           "token1": "0x" + strip(t[2])[24:],
                           "fee": fee, "tickSpacing": tick})
        scan["parsed"] = parsed
        # timestamps of window
        tb, _ = rpc("eth_getBlockByNumber", [hex(frm), False], "block_window_start")
        if tb:
            scan["window_start_time_utc"] = datetime.datetime.fromtimestamp(
                int(tb["timestamp"], 16), datetime.timezone.utc).isoformat()
    out["uni_poolcreated_scan"] = scan

    # --- Superchain / releases rule evidence ---
    op_toml = open(OUT + r"\superchain_op_toml.txt", encoding="utf-8",
                   errors="replace").read()
    out["superchain_op_toml_head"] = op_toml[:2500]
    hardforks = {}
    sec = None
    for line in op_toml.splitlines():
        if line.strip().startswith("["):
            sec = line.strip()
        if "hardfork" in line.lower() or (sec and "hardfork" in sec.lower()):
            hardforks.setdefault(sec or "", []).append(line.strip())
    out["superchain_hardfork_lines"] = {k: v[:10] for k, v in hardforks.items()}
    atom = open(OUT + r"\op_releases_atom.txt", encoding="utf-8",
                errors="replace").read()
    releases = []
    for m in re.finditer(r"<entry>(.*?)</entry>", atom, re.S):
        blk = m.group(1)
        t = re.search(r"<title>(.*?)</title>", blk, re.S)
        u = re.search(r'<link[^>]*href="([^"]+)"', blk)
        up = re.search(r"<updated>(.*?)</updated>", blk)
        releases.append({"title": t.group(1) if t else None,
                         "link": u.group(1) if u else None,
                         "updated": up.group(1) if up else None})
    out["op_releases"] = releases[:10]

    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeA-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeA.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:9000])


if __name__ == "__main__":
    main()
