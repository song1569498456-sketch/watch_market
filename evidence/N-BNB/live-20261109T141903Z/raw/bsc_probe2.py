import json, time, datetime, hashlib
import requests
from eth_utils import keccak
from eth_abi import encode, decode

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\N-BNB\live-20261109T141903Z\raw"
DS = r"D:\ds-arb-test\watch_market\evidence\N-BNB\live-20261109T141903Z\raw"

sess = requests.Session()
sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})

log = []
count = [0]
last = {}
_id = [100]


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def throttle(host):
    now = time.time()
    if host in last and now - last[host] < 0.35:
        time.sleep(0.35 - (now - last[host]))
    last[host] = time.time()


def record(kind, host, tag, **kw):
    count[0] += 1
    e = {"n": count[0], "kind": kind, "host": host, "tag": tag, "at_utc": utcnow()}
    e.update(kw)
    log.append(e)
    return e


def http_get(url, tag, host, timeout=25):
    throttle(host)
    t0 = time.time()
    e = record("GET", host, tag, url=url)
    try:
        r = sess.get(url, timeout=timeout)
        e["http_status"] = r.status_code
        e["elapsed_s"] = round(time.time() - t0, 3)
        e["bytes"] = len(r.content)
        e["sha256"] = hashlib.sha256(r.content).hexdigest()
        return r.status_code, r, e
    except Exception as ex:
        e["error"] = repr(ex)
        return None, None, e


RPCS = {
    "dataseed": "https://bsc-dataseed.bnbchain.org",
    "publicnode": "https://bsc-rpc.publicnode.com",
}


def rpc(url, host, method, params, tag, timeout=25):
    throttle(host)
    _id[0] += 1
    payload = {"jsonrpc": "2.0", "id": _id[0], "method": method, "params": params}
    t0 = time.time()
    e = record("POST", host, tag, rpc_method=method, rpc_params=params)
    try:
        r = sess.post(url, json=payload, timeout=timeout)
        e["http_status"] = r.status_code
        e["elapsed_s"] = round(time.time() - t0, 3)
        j = r.json()
        if "error" in j:
            e["rpc_error"] = j["error"]
            return None, j["error"]
        return j.get("result"), None
    except Exception as ex:
        e["error"] = repr(ex)
        e["elapsed_s"] = round(time.time() - t0, 3)
        return None, repr(ex)


def sel(sig):
    return "0x" + keccak(text=sig)[:4].hex()


def topic(sig):
    return "0x" + keccak(text=sig).hex()


def call(to, data, tag, block="latest"):
    return rpc(RPCS["dataseed"], "bsc-dataseed.bnbchain.org", "eth_call",
               [{"to": to, "data": data}, block], tag)


def strip(h):
    return h[2:] if isinstance(h, str) and h.startswith("0x") else h


def main():
    out = {"started_at_utc": utcnow()}
    ds0 = json.load(open(DS + r"\bsc-probe.json", encoding="utf-8"))
    head = ds0["head_block"]
    pinned = ds0["pinned_block"]
    blk = hex(pinned)
    FAC = "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865"
    QUOTER = "0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997"
    ROUTER_V2 = "0x10ED43C718714eb63d5aA57B78B54704E256024E"
    FACTORY_V2 = "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"
    WBNB = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
    POOLCREATED = topic("PoolCreated(address,address,uint24,int24,address)")
    PAIRCREATED = topic("PairCreated(address,address,address,uint256)")

    # --- 1) factory event scan on alternate RPC (strict small spans, stop at 3 fails) ---
    out["factory_event_scan"] = {}
    fails = 0
    got = None
    for span in (5000, 1000, 200):
        res, err = rpc(RPCS["publicnode"], "bsc-rpc.publicnode.com",
                       "eth_getLogs",
                       [{"address": FAC, "fromBlock": hex(head - span),
                         "toBlock": hex(head), "topics": [POOLCREATED]}],
                       f"pn_factory_PoolCreated_{span}")
        if res is not None:
            got = {"from_block": head - span, "to_block": head,
                   "count": len(res), "logs": res}
            break
        fails += 1
        out["factory_event_scan"][f"attempt_{span}"] = err
        if fails >= 3:
            break
    if got:
        out["factory_event_scan"]["success"] = {
            "from_block": got["from_block"], "to_block": got["to_block"],
            "count": got["count"]}
        parsed = []
        for lg in got["logs"][-12:]:
            t = lg["topics"]
            fee = int(t[3], 16) & 0xFFFFFF
            data = bytes.fromhex(strip(lg["data"]))
            tick_spacing = decode(["int256"], data[:32])[0]
            pool = "0x" + strip(decode(["address"], data[32:64])[0])
            parsed.append({"block": int(lg["blockNumber"], 16),
                           "tx": lg["transactionHash"],
                           "pool": "0x" + pool, "token0": "0x" + strip(t[1])[24:],
                           "token1": "0x" + strip(t[2])[24:], "fee": fee,
                           "tickSpacing": tick_spacing})
        out["factory_event_scan"]["parsed_pool_created"] = parsed

    # --- 2) V2 PairCreated scan for recent new pairs ---
    out["v2_pair_scan"] = {}
    v2got = None
    for span in (2000, 500):
        res, err = rpc(RPCS["publicnode"], "bsc-rpc.publicnode.com", "eth_getLogs",
                       [{"address": FACTORY_V2, "fromBlock": hex(head - span),
                         "toBlock": hex(head), "topics": [PAIRCREATED]}],
                       f"pn_v2_PairCreated_{span}")
        if res is not None:
            v2got = {"from_block": head - span, "to_block": head,
                     "count": len(res), "logs": res}
            break
        out["v2_pair_scan"][f"attempt_{span}"] = err
    if v2got:
        out["v2_pair_scan"]["success"] = {
            "from_block": v2got["from_block"], "to_block": v2got["to_block"],
            "count": v2got["count"]}
        parsed = []
        for lg in v2got["logs"][-10:]:
            t = lg["topics"]
            data = bytes.fromhex(strip(lg["data"]))
            pair = "0x" + strip(decode(["address"], data[:32])[0])
            parsed.append({"block": int(lg["blockNumber"], 16),
                           "tx": lg["transactionHash"],
                           "pair": pair, "token0": "0x" + strip(t[1])[24:],
                           "token1": "0x" + strip(t[2])[24:]})
        out["v2_pair_scan"]["parsed_pairs"] = parsed

    # --- 3) dexscreener pairs for the two new BSC profile tokens ---
    out["dexscreener_pairs"] = {}
    for tok, label in (("0xf80e4DB5f779788c66E9186E03F5e0C12262ffFF", "fourmeme_sample"),
                       ("0x6E8ECa1cFe793e8f29606a6b969370134431fFfF", "astai")):
        st, r, e = http_get(f"https://api.dexscreener.com/latest/dex/tokens/{tok}",
                            f"ds_pairs_{label}", "api.dexscreener.com")
        item = {"http_status": st, "error": e.get("error"), "pairs": []}
        if r is not None and r.status_code == 200:
            j = r.json()
            for p in (j.get("pairs") or [])[:6]:
                item["pairs"].append({
                    "chainId": p.get("chainId"), "dexId": p.get("dexId"),
                    "pairAddress": p.get("pairAddress"),
                    "baseToken": (p.get("baseToken") or {}).get("address"),
                    "quoteToken": (p.get("quoteToken") or {}).get("address"),
                    "priceUsd": p.get("priceUsd"),
                    "liquidityUsd": (p.get("liquidity") or {}).get("usd"),
                    "fdv": p.get("fdv"), "pairCreatedAt": p.get("pairCreatedAt"),
                    "labels": p.get("labels"),
                })
        out["dexscreener_pairs"][label] = item

    # --- 4) chain-verify V2 pair for four.meme sample token (if any) ---
    out["pair_verification"] = {}
    cand = None
    dp = out["dexscreener_pairs"].get("fourmeme_sample", {}).get("pairs") or []
    for p in dp:
        if str(p.get("chainId")) == "bsc" and str(p.get("dexId")) == "pancakeswap":
            cand = p
            break
    if cand:
        pair_addr = cand["pairAddress"]
        data = sel("getPair(address,address)") + encode(
            ["address", "address"],
            [WBNB, cand["baseToken"]]).hex()
        res, err = rpc(RPCS["dataseed"], "bsc-dataseed.bnbchain.org", "eth_call",
                       [{"to": FACTORY_V2, "data": data}, blk], "v2_getPair_verify")
        out["pair_verification"]["factory_getPair"] = {
            "pair": pair_addr, "what": "getPair(WBNB, baseToken)",
            "raw": res, "match": bool(res and int(res, 16) and
                                      "0x" + strip(res)[24:] == pair_addr.lower())}
        v = {"pair": pair_addr}
        code, _ = rpc(RPCS["dataseed"], "bsc-dataseed.bnbchain.org", "eth_getCode",
                      [pair_addr, "latest"], "v2_pair_code")
        v["code_bytes"] = (len(code) - 2) // 2 if code else None
        v["code_sha256"] = hashlib.sha256(bytes.fromhex(strip(code))).hexdigest() if code else None
        for fld, sig in (("token0", "token0()"), ("token1", "token1()"),
                         ("getReserves", "getReserves()")):
            res, err = rpc(RPCS["dataseed"], "bsc-dataseed.bnbchain.org", "eth_call",
                           [{"to": pair_addr, "data": sel(sig)}, blk],
                           f"v2_pair_{fld}")
            v[fld] = {"raw": res, "error": err}
        try:
            if v["getReserves"]["raw"]:
                r0, r1, ts = decode(["uint112", "uint112", "uint32"],
                                    bytes.fromhex(strip(v["getReserves"]["raw"])))
                v["reserves"] = {"reserve0": str(r0), "reserve1": str(r1),
                                 "blockTimestampLast": ts}
        except Exception as ex:
            v["reserves_error"] = repr(ex)
        out["pair_verification"]["pair_state"] = v
        # V2 real quote: 0.01 BNB -> token at pinned block
        data = sel("getAmountsOut(uint256,address[])") + encode(
            ["uint256", "address[]"], [10**16, [WBNB, cand["baseToken"]]]).hex()
        res, err = rpc(RPCS["dataseed"], "bsc-dataseed.bnbchain.org", "eth_call",
                       [{"to": ROUTER_V2, "data": data}, blk],
                       "v2_getAmountsOut_newpair")
        q = {"block": pinned, "amount_in_wei": str(10**16), "raw": res, "error": err}
        if res:
            try:
                q["amounts_out"] = [str(x) for x in decode(
                    ["uint256[]"], bytes.fromhex(strip(res)))[0]]
            except Exception as ex:
                q["decode_error"] = repr(ex)
        out["pair_verification"]["quote_001BNB_to_token"] = q

    # --- 5) BSC official releases atom (30-day rule window update) ---
    st, r, e = http_get("https://github.com/bnb-chain/bsc/releases.atom",
                        "bsc_releases_atom", "github.com")
    atom = {"http_status": st, "error": e.get("error"), "entries": []}
    if r is not None and r.status_code == 200:
        import re
        txt = r.text
        for m in re.finditer(r"<entry>(.*?)</entry>", txt, re.S):
            block = m.group(1)
            t = re.search(r"<title>(.*?)</title>", block, re.S)
            u = re.search(r'<link[^>]*href="([^"]+)"', block)
            up = re.search(r"<updated>(.*?)</updated>", block)
            atom["entries"].append({"title": t.group(1) if t else None,
                                    "link": u.group(1) if u else None,
                                    "updated": up.group(1) if up else None})
    atom["entries"] = atom["entries"][:8]
    out["bsc_releases_atom"] = atom

    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    with open(OUT + r"\rpc-log2.json", "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=1)
    with open(OUT + r"\bsc-probe2.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({
        "factory_event_scan": {k: (v if k != "success" else v)
                               for k, v in out["factory_event_scan"].items()
                               if k != "parsed_pool_created"},
        "new_pools": out["factory_event_scan"].get("parsed_pool_created"),
        "v2_scan": {k: v for k, v in out["v2_pair_scan"].items() if k != "parsed_pairs"},
        "new_v2_pairs": out["v2_pair_scan"].get("parsed_pairs"),
        "pair_verification": out.get("pair_verification"),
        "releases": [(x["title"], x["updated"]) for x in atom["entries"]],
        "request_count_this_script": count[0],
    }, ensure_ascii=False, indent=1)[:9000])


if __name__ == "__main__":
    main()
