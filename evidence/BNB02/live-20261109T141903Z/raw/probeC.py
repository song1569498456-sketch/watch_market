import json, time, datetime, hashlib, re
import requests
from eth_utils import keccak
from eth_abi import encode, decode

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\BNB02\live-20261109T141903Z\raw"
sess = requests.Session(); sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [900]
RPCS = [("bsc-dataseed", "https://bsc-dataseed.bnbchain.org"),
        ("bsc-publicnode", "https://bsc-rpc.publicnode.com")]


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def throttle(h):
    n = time.time()
    if h in last and n - last[h] < 0.3:
        time.sleep(0.3 - (n - last[h]))
    last[h] = time.time()


def http_get(url, tag, host=None, headers=None):
    host = host or url.split("/")[2]
    throttle(host); count[0] += 1
    e = {"n": count[0], "kind": "GET", "host": host, "tag": tag, "url": url,
         "at_utc": utcnow()}
    try:
        r = sess.get(url, timeout=25, headers=headers)
        e["http_status"] = r.status_code
        e["sha256"] = hashlib.sha256(r.content).hexdigest()
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


def main():
    out = {"started_at_utc": utcnow()}
    VAI = "0x4BD17003473389A42DAF6a0a729f6Fdb328BbBd7"
    USDT = "0x55d398326f99059fF775485246999027B3197955"
    PANCAKE_V3_QUOTER = "0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997"
    V3POOL = "0xF5B4B24E5808DAA3fBeee11DF27a0994600356b4"
    IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"

    # list Venus deployment files to locate VAI controller JSON
    st, txt = http_get(
        "https://api.github.com/repos/VenusProtocol/venus-protocol/contents/deployments/bscmainnet",
        "gh_venus_deployments", "api.github.com",
        headers={"Accept": "application/vnd.github+json"})
    files = []
    try:
        j = json.loads(txt)
        if isinstance(j, list):
            files = [x.get("name") for x in j if isinstance(x, dict)]
    except Exception as ex:
        out["gh_listing_error"] = repr(ex)
    out["deployments_files"] = {"http_status": st, "count": len(files),
                                "names": [f for f in files if f and
                                          ("VAI" in f or "ai" in f.lower() or "Comptroller" in f)][:30]}
    target = None
    for name in files:
        if not name:
            continue
        low = name.lower()
        if "vaicontroller" in low or "vai_controller" in low or low == "vaiunitroller.json":
            target = name
            break
    out["controller_file"] = target
    ctrl = None
    if target:
        st2, txt2 = http_get(
            "https://raw.githubusercontent.com/VenusProtocol/venus-protocol/develop/deployments/bscmainnet/" + target,
            "venus_ctrl_json", "raw.githubusercontent.com")
        fields = {}
        try:
            j = json.loads(txt2)
            if isinstance(j, dict):
                for k, v in j.items():
                    if isinstance(v, str) and re.fullmatch(r"0x[0-9a-fA-F]{40}", v):
                        fields[k] = v
        except Exception as ex:
            fields = {"parse_error": repr(ex)}
        out["venus_ctrl_json"] = {"http_status": st2, "fields": fields}
        for k, v in fields.items():
            kl = k.lower()
            if "unitroller" in kl or "controller" in kl or k in ("address",):
                ctrl = v
                break
        if not ctrl and "address" in fields:
            ctrl = fields["address"]

    # fallback candidate: read code of known Venus VAI unitroller proxy and use if code exists
    fallback = "0x004065D34C26BE3244f27c8E089CC88863987fbC"
    cands = [c for c in (ctrl, fallback) if c]
    out["controller_candidates"] = list(dict.fromkeys(cands))
    chosen = None
    for addr in out["controller_candidates"]:
        c, _ = rpc("eth_getCode", [addr, "latest"], "code_ctrl_" + addr[:8])
        bn_ = (len(c) - 2) // 2 if c else 0
        if bn_ > 0:
            chosen = addr
            out["controller_choice"] = {"address": addr, "code_bytes": bn_,
                                        "code_sha256": hashlib.sha256(
                                            bytes.fromhex(strip(c))).hexdigest()}
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

    comp = None
    if chosen:
        reads = [("comptroller", "comptroller()"), ("treasuryFee", "treasuryFee()"),
                 ("vaiMintCap", "vaiMintCap()"), ("getVAIRepayRate", "getVAIRepayRate()"),
                 ("vaiMintEnabled", "vaiMintEnabled()"), ("paused", "paused()"),
                 ("admin", "admin()")]
        cstate = {}
        for fld, sig in reads:
            r, err = call(chosen, sel(sig), "ctrl_" + fld)
            item = {"raw": r, "error": err}
            if r:
                try:
                    item["uint"] = str(int(r, 16))
                except Exception:
                    pass
            cstate[fld] = item
        probe = "0x0000000000000000000000000000000000000001"
        for fld, sig in (("getMintableVAI_probe", "getMintableVAI(address)"),
                         ("getVAIRepayAmount_probe", "getVAIRepayAmount(address)")):
            r, err = call(chosen, sel(sig) + encode(["address"], [probe]).hex(),
                          "ctrl_" + fld)
            cstate[fld] = {"raw": r, "error": err,
                           "uint": str(int(r, 16)) if r else None}
        cstate["impl_slot"], _ = rpc("eth_getStorageAt", [chosen, IMPL_SLOT, "latest"],
                                     "ctrl_impl_slot")
        out["controller_state"] = cstate
        r = cstate.get("comptroller", {}).get("raw")
        if r:
            comp = "0x" + strip(r)[24:]
    out["comptroller"] = {"address": comp}
    if comp:
        for label, token in (("USDT", USDT), ("VAI", VAI)):
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
        for fld, sig in (("closeFactor", "closeFactorMantissa()"),
                         ("liquidationIncentive", "liquidationIncentiveMantissa()")):
            rr, err = call(comp, sel(sig), "comp_" + fld)
            out["comptroller"][fld] = {"raw": rr, "error": err,
                                       "uint": str(int(rr, 16)) if rr else None}

    # V3 buyback quotes (USDT -> VAI) on the same pool/block
    buy = []
    for amt in (991548511576302296035, 1000 * 10**18, 1010 * 10**18):
        data = sel("quoteExactInputSingle((address,address,uint256,uint24,uint160))") + encode(
            ["(address,address,uint256,uint24,uint160)"],
            [(USDT, VAI, amt, 100, 0)]).hex()
        r, err = call(PANCAKE_V3_QUOTER, data, f"buyback_{amt}")
        item = {"amount_in_usdt": str(amt), "block": out["pinned_block"],
                "amount_out_vai": None, "error": err}
        if r:
            try:
                v = decode(["uint256", "uint160", "uint32", "uint256"],
                           bytes.fromhex(strip(r)))
                item["amount_out_vai"] = str(v[0]); item["gasEstimate"] = str(v[3])
            except Exception as ex:
                item["decode_error"] = repr(ex)
        buy.append(item)
    out["buyback_quotes"] = buy

    # V3 pool state for capacity
    ps = {"address": V3POOL}
    for fld, sig in (("token0", "token0()"), ("token1", "token1()"), ("fee", "fee()"),
                     ("slot0", "slot0()"), ("liquidity", "liquidity()")):
        r, err = call(V3POOL, sel(sig), "v3pool_" + fld)
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
    out["v3_pool_state"] = ps

    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeC-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeC.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("SAVED; requests:", out["request_count_this_script"])
    print(json.dumps(out, ensure_ascii=False, indent=1)[:9000])


if __name__ == "__main__":
    main()
