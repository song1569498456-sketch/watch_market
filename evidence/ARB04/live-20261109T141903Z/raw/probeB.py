import json, time, datetime, hashlib
import requests
from eth_utils import keccak
from eth_abi import encode, decode

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\ARB04\live-20261109T141903Z\raw"
sess = requests.Session(); sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [100]
RPCS = [("arb1", "https://arb1.arbitrum.io/rpc"),
        ("arb-publicnode", "https://arbitrum-one-rpc.publicnode.com")]


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


def topic(s):
    return "0x" + keccak(text=s).hex()


def main():
    out = {"started_at_utc": utcnow()}
    STATA = "0x7F6501d3B98eE91f9b9535E4b0ac710Fb0f9e0bc"
    STATIC_A = "0x7CFaDFD5645B50bE87d546f42699d863648251ad"
    USDC = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
    UNI_FACTORY = "0x1F98431c8aD98523631AE4a59f267346ea31F984"
    SUSHI_FACTORY = "0xc35DADB65012eC5796536bD9864eD8773aBc74C4"

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

    def dec_addr(r):
        return "0x" + strip(r)[24:] if r and int(r, 16) else None

    # secondary market existence on Uniswap V3 & Sushi V2 for STATA and old STATIC_A
    sec = {}
    for label, tok in (("stata_waArbUSDCn", STATA), ("static_a_token", STATIC_A)):
        entry = {"token": tok, "uniswap_v3": {}, "sushi": None}
        for fee in (100, 500, 3000, 10000):
            r, err = call(UNI_FACTORY, sel("getPool(address,address,uint24)") +
                          encode(["address", "address", "uint24"], [tok, USDC, fee]).hex(),
                          f"uni_{label}_{fee}")
            entry["uniswap_v3"][str(fee)] = {"pool": dec_addr(r), "error": err}
        r, err = call(SUSHI_FACTORY, sel("getPair(address,address)") +
                      encode(["address", "address"], [tok, USDC]).hex(), f"sushi_{label}")
        entry["sushi"] = {"pair": dec_addr(r), "error": err}
        sec[label] = entry
    out["secondary_markets_onchain"] = sec

    # dexscreener discovery for the share tokens (aggregator = discovery only)
    for label, tok in (("stata", STATA), ("static_a", STATIC_A)):
        st, j = http_get("https://api.dexscreener.com/latest/dex/tokens/" + tok,
                         "ds_" + label, "api.dexscreener.com")
        pairs = []
        if isinstance(j, dict):
            for p in (j.get("pairs") or [])[:8]:
                pairs.append({"chainId": p.get("chainId"), "dexId": p.get("dexId"),
                              "pairAddress": p.get("pairAddress"),
                              "baseToken": (p.get("baseToken") or {}).get("address"),
                              "quoteToken": (p.get("quoteToken") or {}).get("address"),
                              "priceUsd": p.get("priceUsd"),
                              "liquidityUsd": (p.get("liquidity") or {}).get("usd")})
        out["dexscreener_" + label] = {"http_status": st, "pairs": pairs}

    # recent Transfer recipient of STATA -> read balance/maxRedeem at fixed block
    TR = topic("Transfer(address,address,uint256)")
    r, err = rpc("eth_getLogs", [{"address": STATA,
                                  "fromBlock": hex(out["head_block"] - 5000),
                                  "toBlock": hex(out["head_block"]),
                                  "topics": [TR]}], "stata_transfer_logs")
    holder = None
    lg = {"count": None, "error": err, "sample": []}
    if r is not None:
        lg["count"] = len(r)
        holders = []
        for e in r[-10:]:
            to = "0x" + e["topics"][2][24:]
            amount = int(e["data"], 16) if e.get("data") not in (None, "0x") else 0
            lg["sample"].append({"block": int(e["blockNumber"], 16), "to": to,
                                 "amount": str(amount)})
            holders.append(to)
        if holders:
            holder = holders[-1]
    out["stata_transfer_logs"] = lg
    out["holder_sample"] = holder
    if holder:
        h = {}
        r, err = call(STATA, sel("balanceOf(address)") + encode(["address"], [holder]).hex(),
                      "holder_balance")
        h["balance_raw"] = str(int(r, 16)) if r else None
        h["balance_error"] = err
        for fld, sig in (("maxRedeem", "maxRedeem(address)"),
                         ("maxWithdraw", "maxWithdraw(address)")):
            r, err = call(STATA, sel(sig) + encode(["address"], [holder]).hex(),
                          "holder_" + fld)
            h[fld] = str(int(r, 16)) if r else None
            h[fld + "_error"] = err
        # previewRedeem of holder's actual balance (if >0)
        if h.get("balance_raw") and int(h["balance_raw"]) > 0:
            r, err = call(STATA, sel("previewRedeem(uint256)") +
                          encode(["uint256"], [int(h["balance_raw"])]).hex(),
                          "holder_previewRedeem")
            h["previewRedeem_balance"] = str(int(r, 16)) if r else None
            h["previewRedeem_error"] = err
        out["holder_state"] = h

    # Beefy API structure check (why 0 arbitrum USDC vaults)
    st, j = http_get("https://api.beefy.finance/vaults", "beefy_vaults_recheck",
                     "api.beefy.finance")
    bf = {"http_status": st, "kind": type(j).__name__, "total_entries": None,
          "chains": {}, "sample_keys": None, "arbitrum_usdc": []}
    if isinstance(j, dict):
        bf["total_entries"] = len(j)
        chains = {}
        for k, v in j.items():
            if not isinstance(v, dict):
                continue
            ch = v.get("chain")
            chains[ch] = chains.get(ch, 0) + 1
            if ch == "arbitrum" and "USD" in str(v.get("token", "")).upper():
                bf["arbitrum_usdc"].append({"id": k, "token": v.get("token"),
                                            "earnedTokenAddress": v.get("earnedTokenAddress"),
                                            "status": v.get("status")})
        bf["chains"] = chains
        first = next(iter(j.values()))
        bf["sample_keys"] = list(first.keys())[:25] if isinstance(first, dict) else None
    elif isinstance(j, list):
        bf["total_entries"] = len(j)
        bf["sample_keys"] = list(j[0].keys())[:25] if j and isinstance(j[0], dict) else None
    out["beefy_recheck"] = bf

    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeB-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeB.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:8000])


if __name__ == "__main__":
    main()
