import json, time, datetime, hashlib, sys
import requests
from eth_utils import keccak
from eth_abi import encode

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\ETH02\live-20261109T141903Z\raw"
RPC = "https://ethereum-rpc.publicnode.com"
COIN0 = "0x6440f144b7e50d6a8439336510312d2f54beb01d"
CURVE_POOL = "0x7ED17e037B7d88A8270c89B3aFA9C38e5218F12b"

sess = requests.Session(); sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [700]


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def throttle(h):
    n = time.time()
    if h in last and n - last[h] < 0.35:
        time.sleep(0.35 - (n - last[h]))
    last[h] = time.time()


def rpc(method, params, tag):
    throttle("ethereum-rpc.publicnode.com"); _id[0] += 1; count[0] += 1
    e = {"n": count[0], "kind": "POST", "host": "ethereum-rpc.publicnode.com",
         "tag": tag, "rpc_method": method, "at_utc": utcnow()}
    try:
        r = sess.post(RPC, json={"jsonrpc": "2.0", "id": _id[0],
                                 "method": method, "params": params}, timeout=30)
        e["http_status"] = r.status_code
        j = r.json(); log.append(e)
        if "error" in j:
            e["rpc_error"] = j["error"]; return None, j["error"]
        return j.get("result"), None
    except Exception as ex:
        e["error"] = repr(ex); log.append(e); return None, repr(ex)


def sel(s):
    return "0x" + keccak(text=s)[:4].hex()


def strip(h):
    return h[2:] if isinstance(h, str) and h.startswith("0x") else h


def dec_str(r):
    if not r:
        return None
    b = bytes.fromhex(strip(r))
    try:
        off = int.from_bytes(b[:32], "big"); ln = int.from_bytes(b[off:off + 32], "big")
        return b[off + 32:off + 32 + ln].decode("utf-8", "replace")
    except Exception:
        return None


def self_check():
    out = {"get_dy_selector": sel("get_dy(int128,int128,uint256)"),
           "symbol_selector": sel("symbol()")}
    ok = out["get_dy_selector"] == "0x5e0d443f" and out["symbol_selector"] == "0x95d89b41"
    print(json.dumps({"self_check_ok": ok, "out": out}, indent=1))
    return ok


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

    coin = {"address": COIN0}
    for fld, sig in (("symbol", "symbol()"), ("name", "name()"), ("decimals", "decimals()")):
        r, err = call(COIN0, sel(sig), "coin0_" + fld)
        if fld in ("symbol", "name"):
            coin[fld] = dec_str(r)
        else:
            coin[fld] = int(r, 16) if r else None
        coin[fld + "_error"] = err
    out["curve_coin0"] = coin
    # both directions at 1000 units on Curve pool (int128 ABI)
    dy = {}
    for tag, i, j in (("coin0_to_LUSD_1000", 0, 1), ("LUSD_to_coin0_1000", 1, 0)):
        data = sel("get_dy(int128,int128,uint256)") + encode(
            ["int128", "int128", "uint256"], [i, j, 1000 * 10**18]).hex()
        r, err = call(CURVE_POOL, data, tag)
        dy[tag] = {"raw": r, "uint": str(int(r, 16)) if r else None, "error": err}
    out["curve_get_dy"] = dy
    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeD-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeD.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("SAVED; requests:", out["request_count_this_script"])
    print(json.dumps(out, ensure_ascii=False, indent=1)[:5000])


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        sys.exit(0 if self_check() else 1)
    main()
