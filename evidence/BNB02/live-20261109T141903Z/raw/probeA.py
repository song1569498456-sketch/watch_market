import json, time, datetime, hashlib, os, re
import requests
from eth_utils import keccak
from eth_abi import encode, decode

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\BNB02\live-20261109T141903Z\raw"
os.makedirs(OUT, exist_ok=True)
sess = requests.Session(); sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [0]
RPCS = [("bsc-dataseed", "https://bsc-dataseed.bnbchain.org"),
        ("bsc-publicnode", "https://bsc-rpc.publicnode.com")]


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


def main():
    out = {"started_at_utc": utcnow()}
    VAI = "0x4BD17003473389A42DAF6a0a729f6Fdb328BbBd7"
    USDT = "0x55d398326f99059fF775485246999027B3197955"
    WBNB = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
    PANCAKE_V2_FACTORY = "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"
    PANCAKE_V2_ROUTER = "0x10ED43C718714eb63d5aA57B78B54704E256024E"
    PANCAKE_V3_FACTORY = "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865"
    PANCAKE_V3_QUOTER = "0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997"
    IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"

    # official Venus deployment JSONs
    st, txt = http_get(
        "https://raw.githubusercontent.com/VenusProtocol/venus-protocol/develop/deployments/bscmainnet/VAI.json",
        "venus_vai_json", "raw.githubusercontent.com")
    out["venus_vai_json"] = {"http_status": st, "chars": len(txt or ""),
                             "sha256": hashlib.sha256((txt or "").encode()).hexdigest()}
    vai_candidates = {}
    if txt:
        try:
            j = json.loads(txt)
            for k, v in j.items():
                if isinstance(v, str) and re.fullmatch(r"0x[0-9a-fA-F]{40}", v):
                    vai_candidates[k] = v
        except Exception as ex:
            out["venus_vai_json"]["parse_error"] = repr(ex)
    out["venus_vai_json"]["fields"] = vai_candidates

    st, txt2 = http_get(
        "https://raw.githubusercontent.com/VenusProtocol/venus-protocol/develop/deployments/bscmainnet/VAIController.json",
        "venus_vai_controller_json", "raw.githubusercontent.com")
    ctrl_candidates = {}
    if txt2:
        try:
            j = json.loads(txt2)
            for k, v in j.items():
                if isinstance(v, str) and re.fullmatch(r"0x[0-9a-fA-F]{40}", v):
                    ctrl_candidates[k] = v
        except Exception as ex:
            out["venus_vai_controller_json"] = {"parse_error": repr(ex)}
    out["venus_vai_controller_json"] = {
        "http_status": st, "chars": len(txt2 or ""),
        "sha256": hashlib.sha256((txt2 or "").encode()).hexdigest(),
        "fields": ctrl_candidates}

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

    # VAI token identity + find controller getter
    vai = {"address": VAI}
    c, _ = rpc("eth_getCode", [VAI, "latest"], "code_vai")
    vai["code_bytes"] = (len(c) - 2) // 2 if c else 0
    vai["code_sha256"] = hashlib.sha256(bytes.fromhex(strip(c))).hexdigest() if c else None
    for fld, sig in (("name", "name()"), ("symbol", "symbol()"), ("decimals", "decimals()"),
                     ("totalSupply", "totalSupply()")):
        r, err = call(VAI, sel(sig), "vai_" + fld)
        if fld in ("name", "symbol"):
            vai[fld] = dec_str(r)
        else:
            vai[fld] = str(int(r, 16)) if r else None
        vai[fld + "_error"] = err
    # try controller getters on VAI token
    ctrl_from_token = {}
    for fld, sig in (("vaiController", "vaiController()"), ("controller", "controller()"),
                     ("comptroller", "comptroller()")):
        r, err = call(VAI, sel(sig), "vai_getter_" + fld)
        if r:
            ctrl_from_token[fld] = "0x" + strip(r)[24:]
        else:
            ctrl_from_token[fld + "_error"] = err
    vai["controller_getters"] = ctrl_from_token
    out["vai"] = vai

    # pick VAI controller: from JSON fields / token getter / known proxy hint
    cands = []
    for d in (ctrl_candidates, vai_candidates):
        for k, v in d.items():
            if "controller" in k.lower() or "vaiunitroller" in k.lower() or len(k) == 0:
                cands.append(v)
    for k, v in ctrl_from_token.items():
        if not k.endswith("_error") and isinstance(v, str):
            cands.append(v)
    cands = list(dict.fromkeys(cands))
    out["controller_candidates"] = cands

    ctrl = None
    for addr in cands:
        c, _ = rpc("eth_getCode", [addr, "latest"], "code_ctrl_" + addr[:8])
        if c and (len(c) - 2) // 2 > 100:
            ctrl = addr
            out["controller_choice"] = {"address": addr,
                                        "code_bytes": (len(c) - 2) // 2,
                                        "code_sha256": hashlib.sha256(bytes.fromhex(strip(c))).hexdigest()}
            break
    if ctrl:
        reads = [
            ("comptroller", "comptroller()"),
            ("treasuryFee", "treasuryFee()"),
            ("vaiMintCap", "vaiMintCap()"),
            ("getVAIRepayRate", "getVAIRepayRate()"),
            ("getMintableVAI_zero", "getMintableVAI(address)"),
            ("getVAIRepayAmount_zero", "getVAIRepayAmount(address)"),
            ("vaiMintEnabled", "vaiMintEnabled()"),
            ("paused", "paused()"),
            ("admin", "admin()"),
        ]
        cstate = {}
        for fld, sig in reads:
            data = sel(sig)
            if "address" in sig:
                data += encode(["address"], ["0x0000000000000000000000000000000000000001"]).hex()
            r, err = call(ctrl, data, "ctrl_" + fld)
            cstate[fld] = {"raw": r, "error": err}
            if r:
                try:
                    cstate[fld]["uint"] = str(int(r, 16))
                except Exception:
                    pass
        cstate["impl_slot"], _ = rpc("eth_getStorageAt", [ctrl, IMPL_SLOT, "latest"],
                                     "ctrl_impl_slot")
        out["controller_state"] = cstate
        comp = None
        r = cstate.get("comptroller", {}).get("raw")
        if r:
            comp = "0x" + strip(r)[24:]
        out["comptroller"] = {"address": comp}
        if comp:
            for label, token in (("USDT", USDT), ("WBNB", WBNB), ("VAI", VAI)):
                rr, err = call(comp, sel("markets(address)") + encode(["address"], [token]).hex(),
                               "comp_markets_" + label)
                item = {"raw": rr, "error": err}
                if rr:
                    try:
                        is_listed, cf, is_comp = decode(["bool", "uint256", "bool"],
                                                        bytes.fromhex(strip(rr)))
                        item.update({"isListed": is_listed,
                                     "collateralFactorMantissa": str(cf),
                                     "isComptroller": is_comp})
                    except Exception as ex:
                        item["decode_error"] = repr(ex)
                out["comptroller"][label] = item
            for fld, sig in (("oracle", "oracle()"), ("closeFactor", "closeFactorMantissa()"),
                             ("liquidationIncentive", "liquidationIncentiveMantissa()")):
                rr, err = call(comp, sel(sig), "comp_" + fld)
                if fld == "oracle":
                    out["comptroller"][fld] = "0x" + strip(rr)[24:] if rr else None
                else:
                    out["comptroller"][fld] = {"raw": rr, "error": err,
                                               "uint": str(int(rr, 16)) if rr else None}

    # DEX pools: Pancake V2 & V3 for VAI/USDT
    dex = {}
    for label, (a, b) in {"VAI_USDT": (VAI, USDT), "VAI_WBNB": (VAI, WBNB)}.items():
        rr, err = call(PANCAKE_V2_FACTORY, sel("getPair(address,address)") +
                       encode(["address", "address"], [a, b]).hex(), "v2_getPair_" + label)
        pair = "0x" + strip(rr)[24:] if rr and int(rr, 16) else None
        dex[label] = {"v2_pair": pair, "v2_error": err}
        if pair:
            rr2, _ = call(pair, sel("getReserves()"), "v2_reserves_" + label)
            if rr2:
                r0, r1, ts = decode(["uint112", "uint112", "uint32"], bytes.fromhex(strip(rr2)))
                dex[label]["v2_reserves"] = {"reserve0": str(r0), "reserve1": str(r1), "ts": ts}
            for fld, sig in (("token0", "token0()"), ("token1", "token1()")):
                rr3, _ = call(pair, sel(sig), "v2_" + label + "_" + fld)
                dex[label][fld] = "0x" + strip(rr3)[24:] if rr3 else None
    for label, (a, b) in {"VAI_USDT": (VAI, USDT)}.items():
        dex[label]["v3_pools"] = {}
        for fee in (100, 500, 2500, 10000):
            rr, err = call(PANCAKE_V3_FACTORY, sel("getPool(address,address,uint24)") +
                           encode(["address", "address", "uint24"], [a, b, fee]).hex(),
                           f"v3_getPool_{label}_{fee}")
            dex[label]["v3_pools"][str(fee)] = {
                "pool": "0x" + strip(rr)[24:] if rr and int(rr, 16) else None,
                "error": err}
    out["dex_pools"] = dex

    # same-block quotes at pinned block
    quotes = []
    def v2_quote(tin, tout, amt, tag):
        data = sel("getAmountsOut(uint256,address[])") + encode(
            ["uint256", "address[]"], [amt, [tin, tout]]).hex()
        r, err = call(PANCAKE_V2_ROUTER, data, tag)
        val = None
        if r:
            try:
                val = int(decode(["uint256[]"], bytes.fromhex(strip(r)))[0][-1])
            except Exception as ex:
                err = repr(ex)
        return {"token_in": tin, "token_out": tout, "amount_in": str(amt),
                "amount_out": str(val) if val is not None else None, "error": err}
    for amt in (100, 1000):
        quotes.append({"label": f"v2_sell_{amt}VAI_USDT",
                       "block": out["pinned_block"],
                       **v2_quote(VAI, USDT, amt * 10**18, f"v2_sell_{amt}")})
    if quotes and quotes[0].get("amount_out"):
        back_in = int(quotes[0]["amount_out"])
        quotes.append({"label": "v2_buyback_with_sell_proceeds",
                       "block": out["pinned_block"],
                       **v2_quote(USDT, VAI, back_in, "v2_buyback")})
    # V3 quotes for 1000 VAI -> USDT across existing pools
    for fee_s, item in dex.get("VAI_USDT", {}).get("v3_pools", {}).items():
        if not item.get("pool"):
            continue
        data = sel("quoteExactInputSingle((address,address,uint256,uint24,uint160))") + encode(
            ["(address,address,uint256,uint24,uint160)"],
            [(VAI, USDT, 1000 * 10**18, int(fee_s), 0)]).hex()
        r, err = call(PANCAKE_V3_QUOTER, data, f"v3_quote_1000VAI_fee{fee_s}")
        item_q = {"label": f"v3_sell_1000VAI_fee{fee_s}", "pool": item["pool"],
                  "block": out["pinned_block"], "amount_in": str(1000 * 10**18),
                  "amount_out": None, "error": err}
        if r:
            try:
                v = decode(["uint256", "uint160", "uint32", "uint256"],
                           bytes.fromhex(strip(r)))
                item_q["amount_out"] = str(v[0]); item_q["gasEstimate"] = str(v[3])
            except Exception as ex:
                item_q["decode_error"] = repr(ex)
        quotes.append(item_q)
    out["quotes"] = quotes

    # dexscreener discovery for VAI pairs
    st, txt = http_get("https://api.dexscreener.com/latest/dex/tokens/" + VAI,
                       "ds_vai_pairs", "api.dexscreener.com")
    pairs = []
    try:
        j = json.loads(txt)
        for p in (j.get("pairs") or [])[:10]:
            pairs.append({"chainId": p.get("chainId"), "dexId": p.get("dexId"),
                          "pairAddress": p.get("pairAddress"),
                          "baseToken": (p.get("baseToken") or {}).get("address"),
                          "quoteToken": (p.get("quoteToken") or {}).get("address"),
                          "priceUsd": p.get("priceUsd"),
                          "liquidityUsd": (p.get("liquidity") or {}).get("usd")})
    except Exception as ex:
        out["ds_parse_error"] = repr(ex)
    out["dexscreener_vai"] = {"http_status": st, "pairs": pairs}

    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeA-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeA.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps({k: out[k] for k in (
        "chain_id", "head_block", "head_block_time_utc", "pinned_block",
        "venus_vai_json", "venus_vai_controller_json", "vai", "controller_candidates",
        "controller_choice", "controller_state", "comptroller", "dex_pools",
        "quotes", "dexscreener_vai", "request_count_this_script")},
        ensure_ascii=False, indent=1)[:9000])


if __name__ == "__main__":
    main()
