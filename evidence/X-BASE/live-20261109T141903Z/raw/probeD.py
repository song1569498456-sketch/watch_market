import json, time, datetime, sys
import requests
from eth_utils import keccak
from eth_abi import decode

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\X-BASE\live-20261109T141903Z\raw"
RPC = "https://ethereum-rpc.publicnode.com"
sess = requests.Session(); sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [900]
L1_CBETH = "0xBe9895146f7AF43049ca1c1AE358B0541Ea49704"
L1_WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
L1_POOL_500 = "0x840deeef2f115cf50da625f7368c24af6fe74410"
PINNED = 26378203


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def throttle(h):
    n = time.time()
    if h in last and n - last[h] < 0.3:
        time.sleep(0.3 - (n - last[h]))
    last[h] = time.time()


def rpc(method, params, tag):
    throttle("ethereum-rpc.publicnode.com"); _id[0] += 1; count[0] += 1
    e = {"n": count[0], "kind": "POST", "host": "ethereum-rpc.publicnode.com",
         "tag": tag, "rpc_method": method, "at_utc": utcnow()}
    try:
        r = sess.post(RPC, json={"jsonrpc": "2.0", "id": _id[0], "method": method,
                                 "params": params}, timeout=25)
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


def self_check():
    out = {"slot0": sel("slot0()"), "liquidity": sel("liquidity()"),
           "token0": sel("token0()"), "token1": sel("token1()")}
    ok = out["slot0"] == "0x3850c7bd" and out["liquidity"] == "0x1a686502"
    print(json.dumps({"self_check_ok": ok, "out": out}, indent=1))
    return ok


def main():
    out = {"started_at_utc": utcnow(), "pinned_block": PINNED,
           "pool_500": L1_POOL_500}
    b = hex(PINNED)
    for fld, sig in (("slot0", "slot0()"), ("liquidity", "liquidity()")):
        r, err = rpc("eth_call", [{"to": L1_POOL_500, "data": sel(sig)}, b], fld)
        if fld == "slot0" and r and strip(r):
            try:
                v = decode(["uint160", "int24", "uint16", "uint16", "uint16",
                            "uint32", "bool"], bytes.fromhex(strip(r)))
                out["slot0"] = {"sqrtPriceX96": str(v[0]), "tick": v[1]}
            except Exception as ex:
                out["slot0_error"] = repr(ex)
        elif fld == "liquidity" and r and strip(r):
            out["liquidity"] = str(int(r, 16))
        out[fld + "_error"] = err
    if out.get("slot0"):
        out["mid_weth_per_cbeth"] = (int(out["slot0"]["sqrtPriceX96"]) / 2**96) ** 2 * 10**12
    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeD-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeD.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("SAVED; requests:", count[0])
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        sys.exit(0 if self_check() else 1)
    main()
