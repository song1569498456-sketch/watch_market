import json, time, datetime, hashlib
import requests
from eth_utils import keccak
from eth_abi import encode

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\ARB04\live-20261109T141903Z\raw"
sess = requests.Session(); sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [500]


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def throttle(h):
    n = time.time()
    if h in last and n - last[h] < 0.3:
        time.sleep(0.3 - (n - last[h]))
    last[h] = time.time()


def http_get(url, tag, host):
    throttle(host); count[0] += 1
    e = {"n": count[0], "kind": "GET", "host": host, "tag": tag, "url": url,
         "at_utc": utcnow()}
    try:
        r = sess.get(url, timeout=25)
        e["http_status"] = r.status_code
        e["sha256"] = hashlib.sha256(r.content).hexdigest()
        log.append(e)
        return r.status_code, r.json()
    except Exception as ex:
        e["error"] = repr(ex); log.append(e); return None, None


def rpc(method, params, tag):
    throttle("arb1"); _id[0] += 1; count[0] += 1
    e = {"n": count[0], "kind": "POST", "host": "arb1", "tag": tag,
         "rpc_method": method, "at_utc": utcnow()}
    try:
        r = sess.post("https://arb1.arbitrum.io/rpc",
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
    UNI_FACTORY = "0x1F98431c8aD98523631AE4a59f267346ea31F984"
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

    # Beefy official list (now a LIST of vaults)
    st, j = http_get("https://api.beefy.finance/vaults", "beefy_list", "api.beefy.finance")
    cands = []
    if isinstance(j, list):
        for v in j:
            if not isinstance(v, dict):
                continue
            ch = v.get("chain")
            tok = str(v.get("token", ""))
            if ch != "arbitrum":
                continue
            if "USD" not in tok.upper():
                continue
            if v.get("status") != "active":
                continue
            cands.append({"id": v.get("id"), "name": v.get("name"), "token": tok,
                          "tokenAddress": v.get("tokenAddress"),
                          "tokenDecimals": v.get("tokenDecimals"),
                          "earnContractAddress": v.get("earnContractAddress"),
                          "earnedTokenAddress": v.get("earnedTokenAddress"),
                          "platformId": v.get("platformId")})
    out["beefy"] = {"http_status": st, "arbitrum_usd_candidates": cands[:8],
                    "count": len(cands)}
    vault = None
    if cands:
        # prefer USDC exact tokens
        usdc = [c for c in cands if str(c.get("token", "")).upper() in
                ("USDC", "USDC.E", "USDT")]
        vault = (usdc or cands)[0]
    out["chosen_beefy_vault"] = vault

    sec = {}
    if vault:
        vaddr = vault.get("earnedTokenAddress")
        want = vault.get("tokenAddress")
        item = {"api": vault, "address": vaddr}
        for fld, sig, kind in (("want", "want()", "addr"), ("strategy", "strategy()", "addr"),
                               ("totalSupply", "totalSupply()", "int"),
                               ("balance", "balance()", "int"),
                               ("available", "available()", "int"),
                               ("getPricePerFullShare", "getPricePerFullShare()", "int")):
            r, err = call(vaddr, sel(sig), "beefy_" + fld)
            if kind == "int":
                item[fld] = str(int(r, 16)) if r else None
            else:
                item[fld] = "0x" + strip(r)[24:] if r else None
            item[fld + "_error"] = err
        # strategy balance if available
        if item.get("strategy"):
            r, err = call(item["strategy"], sel("balanceOf()"), "beefy_strategy_balance")
            item["strategy_balance"] = str(int(r, 16)) if r else None
            item["strategy_balance_error"] = err
        # Uniswap V3 secondary pools for moo token vs want token
        item["uniswap_v3"] = {}
        for fee in (100, 500, 3000, 10000):
            r, err = call(UNI_FACTORY, sel("getPool(address,address,uint24)") +
                          encode(["address", "address", "uint24"],
                                 [vaddr, want, fee]).hex(), f"uni_{fee}")
            pool = "0x" + strip(r)[24:] if r and int(r, 16) else None
            item["uniswap_v3"][str(fee)] = {"pool": pool, "error": err}
        sec["beefy_vault"] = item
        # dexscreener discovery for moo token
        st2, j2 = http_get("https://api.dexscreener.com/latest/dex/tokens/" + vaddr,
                           "ds_beefy_moo", "api.dexscreener.com")
        pairs = []
        if isinstance(j2, dict):
            for p in (j2.get("pairs") or [])[:5]:
                pairs.append({"chainId": p.get("chainId"), "dexId": p.get("dexId"),
                              "pairAddress": p.get("pairAddress"),
                              "liquidityUsd": (p.get("liquidity") or {}).get("usd")})
        sec["dexscreener"] = {"http_status": st2, "pairs": pairs}
    out["secondary_check"] = sec

    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeD-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeD.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:7000])


if __name__ == "__main__":
    main()
