import json, time, datetime, hashlib, os
import requests
from eth_utils import keccak
from eth_abi import encode, decode

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\BNB01\live-20261109T141903Z\raw"
os.makedirs(OUT, exist_ok=True)
sess = requests.Session(); sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [100]


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
    try:
        r = sess.get(url, timeout=timeout, headers=headers)
        e["http_status"] = r.status_code; e["bytes"] = len(r.content)
        e["sha256"] = hashlib.sha256(r.content).hexdigest(); log.append(e)
        try:
            return r.status_code, r.json(), e
        except Exception:
            return r.status_code, r.text, e
    except Exception as ex:
        e["error"] = repr(ex); log.append(e); return None, None, e


def rpc(method, params, tag, timeout=25):
    throttle("bsc-dataseed.bnbchain.org"); _id[0] += 1; count[0] += 1
    e = {"n": count[0], "kind": "POST", "host": "bsc-dataseed.bnbchain.org",
         "tag": tag, "rpc_method": method, "at_utc": utcnow()}
    try:
        r = sess.post("https://bsc-dataseed.bnbchain.org",
                      json={"jsonrpc": "2.0", "id": _id[0], "method": method,
                            "params": params}, timeout=timeout)
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
        return {"address": addr, "bytes": (len(c) - 2) // 2 if c else 0,
                "sha256": hashlib.sha256(bytes.fromhex(strip(c))).hexdigest() if c else None,
                "code_hex": c}

    def dec_addr(res):
        return "0x" + strip(res)[24:] if res else None

    LISUSD = "0x0782b6d8c4551B9760e74c0545a9bCD90bdc41E5"
    LISUSD_IMPL = "0xf5bd9b192092517d60e90c9af17b69b134c4d7f8"
    INTERACTION_IMPL = "0xce338985a4b241605955dd77c917aa040e110ed3"
    USDT = "0x55d398326f99059fF775485246999027B3197955"
    QUOTER = "0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997"

    out["lisUSD_impl"] = {k: v for k, v in code(LISUSD_IMPL, "code_lisUSD_impl").items() if k != "code_hex"}
    out["interaction_impl"] = {k: v for k, v in code(INTERACTION_IMPL, "code_interaction_impl").items() if k != "code_hex"}

    # selector inventory of impl bytecodes (PUSH4 pattern) and negative test for redemption names
    def selectors(code_hex):
        b = bytes.fromhex(strip(code_hex)) if code_hex else b""
        found = set()
        for i in range(len(b) - 4):
            if b[i] == 0x63:  # PUSH4
                found.add("0x" + b[i + 1:i + 5].hex())
        return sorted(found)
    lis_sel = selectors(out["lisUSD_impl"].get("code_hex"))
    int_sel = selectors(out["interaction_impl"].get("code_hex"))
    out["lisUSD_impl"]["selector_count"] = len(lis_sel)
    out["interaction_impl"]["selector_count"] = len(int_sel)
    redeem_like = {
        "redeem(uint256)": sel("redeem(uint256)"),
        "redeem()": sel("redeem()"),
        "burn(uint256)": sel("burn(uint256)"),
        "swap(address,address,uint256)": sel("swap(address,address,uint256)"),
        "exchange(uint256)": sel("exchange(uint256)"),
        "exit(uint256)": sel("exit(uint256)"),
        "withdraw(uint256)": sel("withdraw(uint256)"),
        "mint(address,uint256)": sel("mint(address,uint256)"),
        "repay(uint256)": sel("repay(uint256)"),
        "repay(address,uint256)": sel("repay(address,uint256)"),
        "owner()": sel("owner()"),
        "paused()": sel("paused()"),
        "guardian()": sel("guardian()"),
    }
    out["selector_negative_test"] = {
        "lisUSD_impl": {k: (v in lis_sel) for k, v in redeem_like.items()},
        "interaction_impl": {k: (v in int_sel) for k, v in redeem_like.items()},
        "lisUSD_impl_selectors_sample": lis_sel[:60],
        "interaction_impl_selectors_sample": int_sel[:80],
    }

    # deep lisUSD/USDT pool identified via dexscreener (27.9M USD)
    DEEP = "0x8b94363fbBbBcdae25832807BE39e8e2c60a6e15"
    deep = {"address": DEEP}
    c = code(DEEP, "code_deep_pool")
    deep["code_bytes"] = c["bytes"]; deep["code_sha256"] = c["sha256"]
    for fld, sig in (("token0", "token0()"), ("token1", "token1()")):
        r, err = call(DEEP, sel(sig), f"deep_{fld}")
        deep[fld] = dec_addr(r); deep[fld + "_error"] = err
    for fld, sig in (("slot0", "slot0()"), ("fee", "fee()"),
                     ("getReserves", "getReserves()"),
                     ("coins0", "coins(uint256)"), ("get_dy", "get_dy(int128,int128,uint256)")):
        data = sel(sig)
        if "coins" in sig:
            data += encode(["uint256"], [0]).hex()
        r, err = call(DEEP, data, f"deep_{fld}")
        deep[fld] = {"raw": r, "error": err}
    out["deep_pool"] = deep

    # Pancake V3 lisUSD/USDT pool 0x12E79eb2...: identity, fee tier, slot0, quote 1000 USDT->lisUSD & reverse
    V3POOL = "0x12E79eb21dCc5852F9c6AC1736d977312925da33"
    v3 = {"address": V3POOL}
    c = code(V3POOL, "code_v3pool")
    v3["code_bytes"] = c["bytes"]; v3["code_sha256"] = c["sha256"]
    for fld, sig in (("token0", "token0()"), ("token1", "token1()"),
                     ("fee", "fee()"), ("slot0", "slot0()")):
        r, err = call(V3POOL, sel(sig), f"v3pool_{fld}")
        v3[fld] = {"raw": r, "error": err}
        if fld in ("token0", "token1"):
            v3[fld] = dec_addr(r)
        if fld == "fee" and r:
            v3["fee_dec"] = int(r, 16)
        if fld == "slot0" and r:
            try:
                s0 = decode(["uint160", "int24", "uint16", "uint16", "uint16",
                             "uint32", "bool"], bytes.fromhex(strip(r)))
                v3["slot0_decoded"] = {"sqrtPriceX96": str(s0[0]), "tick": s0[1]}
            except Exception as ex:
                v3["slot0_decode_error"] = repr(ex)
    out["pancake_v3_pool"] = v3

    # real quotes on Pancake V3 (lisUSD/USDT) at pinned block
    fee = v3.get("fee_dec", 100)
    quotes = []
    for label, tin, tout, amt in (
            ("1000USDT_to_lisUSD_fee%d" % fee, USDT, LISUSD, 1000 * 10**18),
            ("1000lisUSD_to_USDT_fee%d" % fee, LISUSD, USDT, 1000 * 10**18)):
        data = sel("quoteExactInputSingle((address,address,uint256,uint24,uint160))") + encode(
            ["(address,address,uint256,uint24,uint160)"], [(tin, tout, amt, fee, 0)]).hex()
        r, err = call(QUOTER, data, "quote_" + label)
        item = {"label": label, "token_in": tin, "token_out": tout,
                "amount_in": str(amt), "fee": fee, "block": out["pinned_block"],
                "raw": r, "error": err}
        if r:
            try:
                vals = decode(["uint256", "uint160", "uint32", "uint256"],
                              bytes.fromhex(strip(r)))
                item.update({"amount_out": str(vals[0]), "gasEstimate": str(vals[3])})
            except Exception as ex:
                item["decode_error"] = repr(ex)
        quotes.append(item)
    out["pancake_v3_quotes"] = quotes

    # docs: current official addresses + price stability text
    for tag, url in (
            ("doc_smart_contracts_addresses",
             "https://raw.githubusercontent.com/lista-dao/gitbook/main/for-developers/smart-contracts-addresses.md"),
            ("doc_price_stability",
             "https://raw.githubusercontent.com/lista-dao/gitbook/main/tokens/price-stability.md"),
            ("doc_obtaining_lisusd",
             "https://raw.githubusercontent.com/lista-dao/gitbook/main/get-started/using-binance-web3-wallet/obtaining-lisusd.md")):
        st, txt, e = http_get(url, tag, host="raw.githubusercontent.com")
        out[tag] = {"http_status": st, "sha256": e.get("sha256"),
                    "text": txt[:4000] if isinstance(txt, str) else None}

    # repo trees: find Interaction source and any PSM
    for tag, repo in (("tree_lista_dao_contracts", "lista-dao-contracts"),
                      ("tree_lista_new_contracts", "lista-new-contracts")):
        st, j, e = http_get(
            f"https://api.github.com/repos/lista-dao/{repo}/git/trees/main?recursive=1",
            tag, host="api.github.com", headers={"Accept": "application/vnd.github+json"})
        item = {"http_status": st, "error": e.get("error"), "paths": []}
        if isinstance(j, dict) and isinstance(j.get("tree"), list):
            item["paths"] = [x.get("path") for x in j["tree"]
                             if isinstance(x.get("path"), str)]
        out[tag] = item

    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeB-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeB.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    summary = {k: out[k] for k in ("head_block", "head_block_time_utc", "pinned_block",
                                   "lisUSD_impl", "interaction_impl",
                                   "selector_negative_test", "deep_pool",
                                   "pancake_v3_pool", "pancake_v3_quotes",
                                   "request_count_this_script")}
    print(json.dumps(summary, ensure_ascii=False, indent=1)[:8500])


if __name__ == "__main__":
    main()
