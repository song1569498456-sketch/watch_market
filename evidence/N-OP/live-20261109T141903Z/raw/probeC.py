import json, time, datetime, hashlib, os, re
import requests
from eth_utils import keccak
from eth_abi import encode, decode

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\N-OP\live-20261109T141903Z\raw"
sess = requests.Session(); sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [300]
RPCS = [("optimism-mainnet", "https://mainnet.optimism.io")]


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
        e["http_status"] = r.status_code
        e["sha256"] = hashlib.sha256(r.content).hexdigest()
        log.append(e)
        return r.status_code, r.text
    except Exception as ex:
        e["error"] = repr(ex); log.append(e); return None, ""


def rpc(method, params, tag):
    host, url = RPCS[0]
    throttle(host); _id[0] += 1; count[0] += 1
    e = {"n": count[0], "kind": "POST", "host": host, "tag": tag,
         "rpc_method": method, "at_utc": utcnow()}
    try:
        r = sess.post(url, json={"jsonrpc": "2.0", "id": _id[0],
                                 "method": method, "params": params}, timeout=25)
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
    POOL = "0x794a61358D6845594F94dc1DB02A252b5b4814aD"

    # find assets file in aave-address-book repo
    st, txt = http_get(
        "https://api.github.com/repos/bgd-labs/aave-address-book/git/trees/main?recursive=1",
        "gh_aave_book_tree", host="api.github.com",
        headers={"Accept": "application/vnd.github+json"})
    paths = []
    try:
        j = json.loads(txt)
        paths = [x["path"] for x in j.get("tree", []) if isinstance(x.get("path"), str)]
    except Exception as ex:
        out["tree_error"] = repr(ex)
    out["tree_paths_count"] = len(paths)
    cand = [p for p in paths if "Optimism" in p and "Asset" in p]
    out["assets_path_candidates"] = cand[:10]

    book = []
    if cand:
        st, txt2 = http_get(
            "https://raw.githubusercontent.com/bgd-labs/aave-address-book/main/" + cand[0],
            "aave_op_assets_real")
        out["assets_file"] = {"path": cand[0], "http_status": st,
                             "chars": len(txt2 or ""),
                             "sha256": hashlib.sha256((txt2 or "").encode()).hexdigest()}
        open(OUT + r"\aave_op_assets_real.txt", "w", encoding="utf-8").write(txt2 or "")
        for m in re.finditer(r"address internal constant (\w+)\s*=\s*(0x[0-9a-fA-F]{40})", txt2 or ""):
            book.append({"name": m.group(1), "address": m.group(2)})
    out["book_assets"] = book
    out["book_asset_count"] = len(book)

    # on-chain reserve list
    rl, err = rpc("eth_call", [{"to": POOL, "data": sel("getReservesList()")}, "latest"],
                  "reserves_list")
    reserves = []
    if rl:
        try:
            reserves = [a for a in decode(["address[]"], bytes.fromhex(strip(rl)))[0]]
        except Exception as ex:
            out["decode_error"] = repr(ex)
    out["onchain_reserves"] = reserves
    out["onchain_reserve_count"] = len(reserves)

    book_set = {a["address"].lower(): a["name"] for a in book}
    on_set = {a.lower() for a in reserves}
    extras = [a for a in reserves if a.lower() not in book_set]
    missing = [a for a in book if a["address"].lower() not in on_set]
    out["onchain_not_in_book"] = extras
    out["book_not_onchain"] = missing[:20]

    # for extras, read symbol/decimals and aToken via getReserveData head
    meta = []
    for a in extras[:4]:
        item = {"address": a}
        for fld, sig in (("symbol", "symbol()"), ("decimals", "decimals()")):
            r, e2 = rpc("eth_call", [{"to": a, "data": sel(sig)}, "latest"],
                        f"extra_{fld}")
            if fld == "symbol" and r:
                b = bytes.fromhex(strip(r))
                try:
                    off = int.from_bytes(b[:32], "big")
                    ln = int.from_bytes(b[off:off + 32], "big")
                    item["symbol"] = b[off + 32:off + 32 + ln].decode("utf-8", "replace")
                except Exception:
                    item["symbol_raw"] = r
            elif fld == "decimals" and r:
                item["decimals"] = int(strip(r)[-2:], 16) if len(strip(r)) <= 64 else int(r, 16)
        # getReserveData returns struct; aToken at word 8 (0-based) per Aave V3 layout
        r, e3 = rpc("eth_call", [{"to": POOL, "data": sel("getReserveData(address)") +
                                  encode(["address"], [a]).hex()}, "latest"],
                    "extra_reserve_data")
        item["getReserveData_error"] = e3
        if r:
            words = [r[2:][i:i + 64] for i in range(0, len(r[2:]), 64)]
            item["reserve_data_words"] = len(words)
            item["reserve_data_word0_15"] = words[:16]
        meta.append(item)
    out["extra_asset_meta"] = meta

    bn, _ = rpc("eth_blockNumber", [], "head")
    out["head_block"] = int(bn, 16) if bn else None
    if bn:
        b, _ = rpc("eth_getBlockByNumber", [bn, False], "headBlock")
        if b:
            out["head_block_time_utc"] = datetime.datetime.fromtimestamp(
                int(b["timestamp"], 16), datetime.timezone.utc).isoformat()
    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeC-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeC.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:8000])


if __name__ == "__main__":
    main()
