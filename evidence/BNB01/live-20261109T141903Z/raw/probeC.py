import json, time, datetime, hashlib, os, re
import requests
from eth_utils import keccak
from eth_abi import encode, decode

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\BNB01\live-20261109T141903Z\raw"
sess = requests.Session(); sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [300]


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def throttle(h):
    n = time.time()
    if h in last and n - last[h] < 0.35:
        time.sleep(0.35 - (n - last[h]))
    last[h] = time.time()


def http_get(url, tag, host=None, headers=None):
    host = host or url.split("/")[2]
    throttle(host); count[0] += 1
    e = {"n": count[0], "kind": "GET", "host": host, "tag": tag, "url": url,
         "at_utc": utcnow()}
    try:
        r = sess.get(url, timeout=25, headers=headers)
        e["http_status"] = r.status_code; e["bytes"] = len(r.content)
        e["sha256"] = hashlib.sha256(r.content).hexdigest(); log.append(e)
        return r.status_code, r.text
    except Exception as ex:
        e["error"] = repr(ex); log.append(e); return None, None


def rpc(method, params, tag):
    throttle("bsc-dataseed.bnbchain.org"); _id[0] += 1; count[0] += 1
    e = {"n": count[0], "kind": "POST", "host": "bsc-dataseed.bnbchain.org",
         "tag": tag, "rpc_method": method, "at_utc": utcnow()}
    try:
        r = sess.post("https://bsc-dataseed.bnbchain.org",
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


RAW = "https://raw.githubusercontent.com/lista-dao/lista-dao-contracts/main/"
FILES = {
    "addresses_bsc": RAW + "addresses/bsc.json",
    "contract_address": RAW + "scripts/deploy/contract_address.json",
    "psm_sol": RAW + "contracts/psm/PSM.sol",
    "lisusd_pool_set_sol": RAW + "contracts/psm/LisUSDPoolSet.sol",
    "deploy_psm_js": RAW + "scripts/prod/psm/deploy_psm.js",
    "deploy_poolset_js": RAW + "scripts/prod/psm/deploy_lisUSDPoolSet.js",
    "ilisusd_pool_sol": RAW + "contracts/interfaces/ILisUSDPool.sol",
}


def sig_to_selector(sig):
    return "0x" + keccak(text=sig)[:4].hex()


def funcs_from_source(src):
    out = []
    for m in re.finditer(r"function\s+(\w+)\s*\(([^)]*)\)([^{;]*)", src):
        name, args, rest = m.group(1), m.group(2), m.group(3)
        types = []
        ok = True
        for a in [x.strip() for x in args.split(",") if x.strip()]:
            parts = a.split()
            if len(parts) < 2:
                ok = False; break
            t = parts[0]
            t = re.sub(r"\s*(memory|calldata|storage|indexed)\s*$", "", t)
            types.append(t)
        if not ok:
            continue
        sig = f"{name}({','.join(types)})"
        view = ("view" in rest or "pure" in rest)
        out.append({"sig": sig, "selector": sig_to_selector(sig), "view": view})
    return out


def main():
    out = {"started_at_utc": utcnow()}
    texts = {}
    for k, url in FILES.items():
        st, txt = http_get(url, "raw_" + k, host="raw.githubusercontent.com")
        out[k] = {"http_status": st, "chars": len(txt or ""),
                  "sha256": hashlib.sha256((txt or "").encode()).hexdigest()}
        texts[k] = txt or ""

    # extract candidate deployed addresses from address json + deploy scripts
    addr_hits = {}
    for k in ("addresses_bsc", "contract_address", "deploy_psm_js",
              "deploy_poolset_js", "deploy_psm_js"):
        txt = texts.get(k, "")
        for m in re.finditer(r"([A-Za-z0-9_\.]*(?:PSM|psm|LisUSDPool|VaultManager|"
                             r"EarnPool|VenusAdapter|LisUSDPoolSet)[A-Za-z0-9_\.]*)"
                             r"[\"']?\s*[:=]\s*[\"'](0x[0-9a-fA-F]{40})", txt):
            addr_hits.setdefault(m.group(1), set()).add(m.group(2))
    out["address_hits"] = {k: sorted(v) for k, v in addr_hits.items()}
    # also scan for "0x..." near PSM keywords in json raw
    psm_candidates = sorted({a for v in addr_hits.values() for a in v})
    out["psm_candidates"] = psm_candidates

    # function inventory from PSM / poolset sources
    out["psm_functions"] = funcs_from_source(texts.get("psm_sol", ""))
    out["poolset_functions"] = funcs_from_source(texts.get("lisusd_pool_set_sol", ""))
    out["psm_source_head"] = texts.get("psm_sol", "")[:5000]
    out["poolset_source_head"] = texts.get("lisusd_pool_set_sol", "")[:4000]
    out["deploy_psm_head"] = texts.get("deploy_psm_js", "")[:3000]

    # on-chain check of candidates
    chain = {"candidates": {}}
    impl_slot = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
    for addr in psm_candidates:
        c, _ = rpc("eth_getCode", [addr, "latest"], "code_" + addr[:10])
        item = {"address": addr,
                "code_bytes": (len(c) - 2) // 2 if c else 0,
                "code_sha256": hashlib.sha256(bytes.fromhex(strip(c))).hexdigest() if c else None}
        if item["code_bytes"]:
            item["impl_slot"], _ = rpc("eth_getStorageAt", [addr, impl_slot, "latest"],
                                       "impl_" + addr[:10])
            item["lisUSD_balance"], _ = rpc(
                "eth_call", [{"to": "0x0782b6d8c4551B9760e74c0545a9bCD90bdc41E5",
                              "data": "0x70a08231" + encode(["address"], [addr]).hex()},
                             "latest"], "lisbal_" + addr[:10])
            item["USDT_balance"], _ = rpc(
                "eth_call", [{"to": "0x55d398326f99059fF775485246999027B3197955",
                              "data": "0x70a08231" + encode(["address"], [addr]).hex()},
                             "latest"], "usdtbal_" + addr[:10])
        chain["candidates"][addr] = item
    out["chain"] = chain

    # try zero-arg view functions from PSM source on first PSM candidate with code
    zero_arg_calls = []
    target = None
    for addr in psm_candidates:
        if chain["candidates"].get(addr, {}).get("code_bytes"):
            target = addr; break
    out["psm_target"] = target
    if target:
        for f in out["psm_functions"]:
            if f["view"] and "()" in f["sig"] and "(" in f["sig"]:
                r, err = rpc("eth_call", [{"to": target, "data": f["selector"]}, "latest"],
                             "call_" + f["sig"])
                zero_arg_calls.append({"sig": f["sig"], "selector": f["selector"],
                                       "raw": r, "error": err})
    out["psm_zero_arg_calls"] = zero_arg_calls

    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeC-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeC.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps({k: out[k] for k in (
        "addresses_bsc", "contract_address", "deploy_psm_js", "psm_sol",
        "lisusd_pool_set_sol", "ilisusd_pool_sol", "deploy_poolset_js",
        "address_hits", "psm_candidates", "psm_target", "chain",
        "request_count_this_script")}, ensure_ascii=False, indent=1)[:6000])
    print("---PSM FUNCS---")
    print(json.dumps(out["psm_functions"], ensure_ascii=False)[:2500])
    print("---POOLSET FUNCS---")
    print(json.dumps(out["poolset_functions"], ensure_ascii=False)[:1500])
    print("---PSM ZERO ARG---")
    print(json.dumps(out["psm_zero_arg_calls"], ensure_ascii=False)[:2000])


if __name__ == "__main__":
    main()
