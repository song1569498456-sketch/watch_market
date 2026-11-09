import json, time, datetime, hashlib
import requests

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\BNB01\live-20261109T141903Z\raw"
import os
os.makedirs(OUT, exist_ok=True)

sess = requests.Session()
sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [0]


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def throttle(h):
    n = time.time()
    if h in last and n - last[h] < 0.35:
        time.sleep(0.35 - (n - last[h]))
    last[h] = time.time()


def http_get(url, tag, host=None, timeout=25, headers=None):
    host = host or url.split("/")[2]
    throttle(host)
    count[0] += 1
    e = {"n": count[0], "kind": "GET", "host": host, "tag": tag,
         "url": url, "at_utc": utcnow()}
    try:
        r = sess.get(url, timeout=timeout, headers=headers)
        e["http_status"] = r.status_code
        e["bytes"] = len(r.content)
        e["sha256"] = hashlib.sha256(r.content).hexdigest()
        log.append(e)
        try:
            return r.status_code, r.json(), e
        except Exception:
            return r.status_code, r.text, e
    except Exception as ex:
        e["error"] = repr(ex); log.append(e)
        return None, None, e


def rpc(method, params, tag, timeout=25):
    throttle("bsc-dataseed.bnbchain.org")
    _id[0] += 1
    count[0] += 1
    e = {"n": count[0], "kind": "POST", "host": "bsc-dataseed.bnbchain.org",
         "tag": tag, "rpc_method": method, "at_utc": utcnow()}
    try:
        r = sess.post("https://bsc-dataseed.bnbchain.org",
                      json={"jsonrpc": "2.0", "id": _id[0],
                            "method": method, "params": params}, timeout=timeout)
        e["http_status"] = r.status_code
        j = r.json()
        log.append(e)
        if "error" in j:
            e["rpc_error"] = j["error"]
            return None, j["error"]
        return j.get("result"), None
    except Exception as ex:
        e["error"] = repr(ex); log.append(e)
        return None, repr(ex)


def strip(h):
    return h[2:] if isinstance(h, str) and h.startswith("0x") else h


def dec_str(res):
    if not res:
        return None
    b = bytes.fromhex(strip(res))
    try:
        off = int.from_bytes(b[:32], "big")
        ln = int.from_bytes(b[off:off + 32], "big")
        return b[off + 32:off + 32 + ln].decode("utf-8", "replace")
    except Exception:
        return None


def main():
    from eth_utils import keccak
    from eth_abi import encode, decode

    def sel(s):
        return "0x" + keccak(text=s)[:4].hex()

    def call(to, data, tag, block="latest"):
        return rpc("eth_call", [{"to": to, "data": data}, block], tag)

    out = {"started_at_utc": utcnow(), "agent": "BNB01"}
    cid, _ = rpc("eth_chainId", [], "chainId")
    out["chain_id"] = int(cid, 16) if cid else None
    bn, _ = rpc("eth_blockNumber", [], "blockNumber")
    out["head_block"] = int(bn, 16) if bn else None
    if bn:
        blk, _ = rpc("eth_getBlockByNumber", [bn, False], "headBlock")
        if blk:
            out["head_block_time_utc"] = datetime.datetime.fromtimestamp(
                int(blk["timestamp"], 16), datetime.timezone.utc).isoformat()
    out["pinned_block"] = out["head_block"] - 2 if out["head_block"] else None
    pinned = hex(out["pinned_block"]) if out["pinned_block"] else "latest"

    LISUSD = "0x0782b6d8c4551B9760e74c0545a9bCD90bdc41E5"
    INTERACTION = "0xB68443Ee3e828baD1526b3e0Bdf2Dfc6b1975ec4"
    VAI = "0x4BD17003473389A42DAF6a0a729f6Fdb328BbBd7"
    IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
    ADMIN_SLOT = "0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103"

    def token_meta(addr, label):
        meta = {"address": addr}
        code, _ = rpc("eth_getCode", [addr, "latest"], f"code_{label}")
        meta["code_bytes"] = (len(code) - 2) // 2 if code else None
        meta["code_sha256"] = (
            hashlib.sha256(bytes.fromhex(strip(code))).hexdigest() if code else None)
        for fld, sig, kind in (("name", "name()", "str"), ("symbol", "symbol()", "str"),
                               ("decimals", "decimals()", "int"),
                               ("totalSupply", "totalSupply()", "int")):
            res, err = call(addr, sel(sig), f"{label}_{fld}", pinned)
            if kind == "str":
                meta[fld] = dec_str(res) if res else None
            else:
                meta[fld] = str(int(res, 16)) if res else None
            if err:
                meta[fld + "_error"] = err
        for fld, slot in (("impl_slot", IMPL_SLOT), ("admin_slot", ADMIN_SLOT)):
            res, err = rpc("eth_getStorageAt", [addr, slot, "latest"],
                           f"{label}_{fld}")
            meta[fld] = res
        return meta

    out["lisUSD"] = token_meta(LISUSD, "lisUSD")
    out["interaction"] = {"address": INTERACTION}
    code, _ = rpc("eth_getCode", [INTERACTION, "latest"], "code_interaction")
    out["interaction"]["code_bytes"] = (len(code) - 2) // 2 if code else None
    out["interaction"]["code_sha256"] = (
        hashlib.sha256(bytes.fromhex(strip(code))).hexdigest() if code else None)
    out["interaction"]["impl_slot"], _ = rpc("eth_getStorageAt",
                                             [INTERACTION, IMPL_SLOT, "latest"],
                                             "interaction_impl_slot")
    out["interaction"]["admin_slot"], _ = rpc("eth_getStorageAt",
                                              [INTERACTION, ADMIN_SLOT, "latest"],
                                              "interaction_admin_slot")
    # Interaction's lisUSD balance and its own debt views if any
    for fld, sig in (("balanceOf_lisUSD", "balanceOf(address)") ,):
        data = sel(sig) + encode(["address"], [INTERACTION]).hex()
        res, err = call(LISUSD, data, "interaction_lisUSD_balance", pinned)
        out["interaction"]["lisUSD_balance"] = (
            str(int(res, 16)) if res else None)
    out["vai"] = token_meta(VAI, "vai")

    # discovery: dexscreener lisUSD pairs
    st, j, e = http_get(
        "https://api.dexscreener.com/latest/dex/tokens/" + LISUSD,
        "ds_lisUSD_pairs", host="api.dexscreener.com")
    pairs = {"http_status": st, "error": e.get("error"), "pairs": []}
    if isinstance(j, dict):
        for p in (j.get("pairs") or [])[:10]:
            pairs["pairs"].append({
                "chainId": p.get("chainId"), "dexId": p.get("dexId"),
                "pairAddress": p.get("pairAddress"),
                "baseToken": (p.get("baseToken") or {}).get("address"),
                "quoteToken": (p.get("quoteToken") or {}).get("address"),
                "priceUsd": p.get("priceUsd"),
                "priceNative": p.get("priceNative"),
                "liquidityUsd": (p.get("liquidity") or {}).get("usd"),
                "volume24h": (p.get("volume") or {}).get("h24"),
                "pairCreatedAt": p.get("pairCreatedAt"),
                "labels": p.get("labels")})
    out["dexscreener_lisUSD"] = pairs

    # discovery: Lista org repos + gitbook tree
    st, j, e = http_get("https://api.github.com/orgs/lista-dao/repos?per_page=100",
                        "gh_lista_repos", host="api.github.com",
                        headers={"Accept": "application/vnd.github+json"})
    repos = {"http_status": st, "error": e.get("error"), "names": []}
    if isinstance(j, list):
        repos["names"] = [x.get("name") for x in j]
    elif isinstance(j, dict):
        repos["message"] = j.get("message")
    out["github_lista_repos"] = repos

    st, j, e = http_get(
        "https://api.github.com/repos/lista-dao/gitbook/git/trees/main?recursive=1",
        "gh_gitbook_tree", host="api.github.com",
        headers={"Accept": "application/vnd.github+json"})
    tree = {"http_status": st, "error": e.get("error"), "paths": []}
    if isinstance(j, dict) and isinstance(j.get("tree"), list):
        tree["paths"] = [x.get("path") for x in j["tree"]
                         if isinstance(x.get("path"), str)]
    out["github_gitbook_tree"] = tree

    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeA-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeA.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:9000])


if __name__ == "__main__":
    main()
