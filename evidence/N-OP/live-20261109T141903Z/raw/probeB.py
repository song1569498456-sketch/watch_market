import json, time, datetime, hashlib, os, re
import requests
from eth_utils import keccak
from eth_abi import encode, decode

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\N-OP\live-20261109T141903Z\raw"
sess = requests.Session(); sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [100]
RPCS = [("optimism-mainnet", "https://mainnet.optimism.io"),
        ("optimism-publicnode", "https://optimism-rpc.publicnode.com")]


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
    err = None
    for host, url in RPCS:
        throttle(host); _id[0] += 1; count[0] += 1
        e = {"n": count[0], "kind": "POST", "host": host, "tag": tag,
             "rpc_method": method, "at_utc": utcnow()}
        try:
            r = sess.post(url, json={"jsonrpc": "2.0", "id": _id[0],
                                     "method": method, "params": params},
                          timeout=25)
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
    from eth_utils import keccak as K

    def topic(s):
        return "0x" + K(text=s).hex()

    out = {"started_at_utc": utcnow()}
    WETH = "0x4200000000000000000000000000000000000006"
    USDC = "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85"
    UNI_FACTORY = "0x1F98431c8aD98523631AE4a59f267346ea31F984"

    # --- local: Uniswap deploys.md OP section ---
    uni = open(OUT + r"\uni_deploys.txt", encoding="utf-8", errors="replace").read()
    op_idx = uni.find("Optimism")
    op_sec = uni[op_idx:op_idx + 5000] if op_idx >= 0 else ""
    deploys_lines = []
    for line in op_sec.splitlines()[:120]:
        if "|" in line and re.search(r"0x[0-9a-fA-F]{40}", line):
            deploys_lines.append(line.strip()[:260])
    out["uni_op_section_lines"] = deploys_lines
    # find QuoterV2 / SwapRouter02 addresses anywhere after OP marker
    out["uni_quoter_candidates"] = re.findall(
        r"QuoterV2[^\n]{0,400}", uni)[:3]

    # --- local: Aave assets file vs on-chain reserves ---
    assets = open(OUT + r"\aave_op_assets.txt", encoding="utf-8", errors="replace").read()
    book = re.findall(r"address internal constant (\w+) = (0x[0-9a-fA-F]{40})", assets)
    out["aave_book_assets"] = [{"name": n, "address": a} for n, a in book]
    out["aave_book_asset_count"] = len(book)

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

    # --- wider Uniswap V3 PoolCreated scan ---
    POOLCREATED = topic("PoolCreated(address,address,uint24,int24,address)")
    scan = {"attempts": []}
    got = None
    if out.get("head_block"):
        for span in (100000, 20000, 5000):
            frm = out["head_block"] - span
            r, err = rpc("eth_getLogs",
                         [{"address": UNI_FACTORY, "fromBlock": hex(frm),
                           "toBlock": hex(out["head_block"]),
                           "topics": [POOLCREATED]}],
                         f"uni_poolcreated_{span}")
            scan["attempts"].append({"span": span, "from": frm, "to": out["head_block"],
                                     "count": len(r) if r is not None else None,
                                     "error": err})
            if r is not None and len(r) > 0:
                got = (frm, out["head_block"], r); break
            if r is not None and span == 5000:
                got = (frm, out["head_block"], r); break
    if got:
        frm, to, logs = got
        tb, _ = rpc("eth_getBlockByNumber", [hex(frm), False], "block_wstart")
        scan["success"] = {"from_block": frm, "to_block": to, "count": len(logs),
                           "window_start_time_utc": datetime.datetime.fromtimestamp(
                               int(tb["timestamp"], 16), datetime.timezone.utc).isoformat() if tb else None}
        parsed = []
        for lg in logs[-8:]:
            t = lg["topics"]
            data = bytes.fromhex(strip(lg["data"]))
            parsed.append({"block": int(lg["blockNumber"], 16),
                           "tx": lg["transactionHash"],
                           "pool": "0x" + strip(decode(["address"], data[32:64])[0]),
                           "token0": "0x" + strip(t[1])[24:],
                           "token1": "0x" + strip(t[2])[24:],
                           "fee": int(t[3], 16) & 0xFFFFFF,
                           "tickSpacing": decode(["int256"], data[:32])[0]})
        scan["parsed"] = parsed
        # verify last 2 pools' state
        ver = []
        for p in parsed[-2:]:
            item = dict(p)
            c, _ = rpc("eth_getCode", [p["pool"], "latest"], "pool_code")
            item["code_bytes"] = (len(c) - 2) // 2 if c else 0
            item["code_sha256"] = hashlib.sha256(bytes.fromhex(strip(c))).hexdigest() if c else None
            for fld, sig in (("token0_", "token0()"), ("token1_", "token1()"),
                             ("fee_", "fee()"), ("slot0", "slot0()"),
                             ("liquidity", "liquidity()")):
                r, err = call(p["pool"], sel(sig), "pool_" + fld)
                item[fld] = r if not r else (("0x" + strip(r)[24:]) if fld.startswith("token") else r)
            ver.append(item)
        scan["verified_pools"] = ver
    out["uni_poolcreated_scan_wide"] = scan

    # --- 30-day rule-change check: superchain op.toml commit history ---
    st, txt = http_get(
        "https://api.github.com/repos/ethereum-optimism/superchain-registry/commits"
        "?path=superchain/configs/mainnet/op.toml&since=2026-10-10T00:00:00Z&per_page=20",
        "gh_superchain_op_commits", host="api.github.com",
        headers={"Accept": "application/vnd.github+json"})
    commits = {"http_status": st, "count": None, "items": [], "error": None}
    try:
        arr = json.loads(txt) if txt else []
        if isinstance(arr, list):
            commits["count"] = len(arr)
            for c in arr[:10]:
                commits["items"].append({"sha": c.get("sha"),
                                         "date": (c.get("commit") or {}).get("committer", {}).get("date"),
                                         "message": ((c.get("commit") or {}).get("message") or "")[:200]})
        else:
            commits["error"] = str(arr)[:300]
    except Exception as ex:
        commits["error"] = repr(ex)
    out["superchain_op_commits_30d"] = commits

    # --- Optimism releases within 30d already fetched; keep ---
    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeB-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeB.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:9000])


if __name__ == "__main__":
    main()
