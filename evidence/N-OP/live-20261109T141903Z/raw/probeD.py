import json, time, datetime, hashlib
import requests
from eth_utils import keccak
from eth_abi import encode, decode

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\N-OP\live-20261109T141903Z\raw"
sess = requests.Session(); sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [600]


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def throttle(h):
    n = time.time()
    if h in last and n - last[h] < 0.35:
        time.sleep(0.35 - (n - last[h]))
    last[h] = time.time()


def rpc(method, params, tag):
    throttle("mainnet.optimism.io"); _id[0] += 1; count[0] += 1
    e = {"n": count[0], "kind": "POST", "host": "mainnet.optimism.io",
         "tag": tag, "rpc_method": method, "at_utc": utcnow()}
    try:
        r = sess.post("https://mainnet.optimism.io",
                      json={"jsonrpc": "2.0", "id": _id[0], "method": method,
                            "params": params}, timeout=25)
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


def main():
    out = {"started_at_utc": utcnow()}
    CAND = "0xAfE208a311B21f13EF87E33A90049fC17A7acDE1"
    POOL = "0x1fb3cf6e48f1e7b10213e7b6d87d4c073c7fdb7b"

    # deploys.md header + row context (local)
    uni = open(OUT + r"\uni_deploys.txt", encoding="utf-8", errors="replace").read()
    lines = uni.splitlines()
    head_ctx = []
    for i, ln in enumerate(lines):
        if ln.strip().startswith("| Contract"):
            head_ctx.append({"line_index": i, "line": ln.strip()[:300]})
    out["deploys_table_headers"] = head_ctx[:4]
    # find the row lines containing factory / quoter / swaprouter
    for key in ("UniswapV3Factory", "Quoter", "SwapRouter", "NonfungiblePositionManager"):
        for ln in lines:
            if key in ln and "0x" in ln:
                out.setdefault("deploys_rows", {})[key] = ln.strip()[:400]
                break

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

    c, _ = rpc("eth_getCode", [CAND, "latest"], "code_candidate_factory")
    out["candidate_factory"] = {"address": CAND,
                                "bytes": (len(c) - 2) // 2 if c else 0,
                                "sha256": hashlib.sha256(bytes.fromhex(strip(c))).hexdigest() if c else None}
    for fee in (500, 3000):
        r, err = call(CAND, sel("feeAmountTickSpacing(uint24)") +
                      encode(["uint24"], [fee]).hex(), f"cand_fee_{fee}")
        sp = None
        if r:
            try:
                sp = decode(["int256"], bytes.fromhex(strip(r)))[0]
            except Exception as ex:
                err = repr(ex)
        out["candidate_factory"][f"tickSpacing_{fee}"] = {"value": sp, "error": err}

    # Uniswap V3 WETH/USDC 0.05% pool state snapshot at pinned block
    pool = {"address": POOL}
    c, _ = rpc("eth_getCode", [POOL, "latest"], "code_pool")
    pool["code_bytes"] = (len(c) - 2) // 2 if c else 0
    pool["code_sha256"] = hashlib.sha256(bytes.fromhex(strip(c))).hexdigest() if c else None
    for fld, sig in (("token0", "token0()"), ("token1", "token1()"), ("fee", "fee()"),
                     ("slot0", "slot0()"), ("liquidity", "liquidity()")):
        r, err = call(POOL, sel(sig), "v3pool_" + fld)
        if fld in ("token0", "token1"):
            pool[fld] = "0x" + strip(r)[24:] if r else None
        elif fld == "fee":
            pool[fld] = int(r, 16) if r else None
        elif fld == "slot0" and r:
            try:
                v = decode(["uint160", "int24", "uint16", "uint16", "uint16",
                            "uint32", "bool"], bytes.fromhex(strip(r)))
                pool["slot0_decoded"] = {"sqrtPriceX96": str(v[0]), "tick": v[1],
                                         "observationCardinality": v[3]}
                import decimal
                pr = (decimal.Decimal(v[0]) / decimal.Decimal(2 ** 96)) ** 2
                pool["price_token1_per_token0_raw"] = str(pr)
            except Exception as ex:
                pool["slot0_decode_error"] = repr(ex)
        elif fld == "liquidity" and r:
            pool["liquidity"] = str(int(r, 16))
        pool[fld + "_error"] = err
    out["uniswap_v3_pool_snapshot"] = pool

    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeD-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeD.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:7000])


if __name__ == "__main__":
    main()
