import json, time, datetime, hashlib, sys
import requests
from eth_utils import keccak
from eth_abi import encode, decode

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\R-BASE\live-20261109T141903Z\raw"
RPC = "https://mainnet.base.org"
sess = requests.Session(); sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [400]

MORPHO = "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"
MARKETS = [
    "0x9103c3b4e834476c9a62ea009ba2c884ee42e94e6e314a26f04d312434191836",
    "0x8793cf302b8ffd655ab97bd1c695dbd967807e8367a65cb2f4edaf1380ba1bda",
    "0x1c21c59df9db44bf6f645d854ee710a8ca17b479451447e9f56758aee10a2fad",
    "0xdba352d93a64b17c71104cbddc6aef85cd432322a1446b5b65163cbbc615cd0c",
]


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def throttle(h):
    n = time.time()
    if h in last and n - last[h] < 0.3:
        time.sleep(0.3 - (n - last[h]))
    last[h] = time.time()


def rpc(method, params, tag):
    throttle("mainnet.base.org"); _id[0] += 1; count[0] += 1
    e = {"n": count[0], "kind": "POST", "host": "mainnet.base.org", "tag": tag,
         "rpc_method": method, "at_utc": utcnow()}
    try:
        r = sess.post(RPC, json={"jsonrpc": "2.0", "id": _id[0],
                                 "method": method, "params": params}, timeout=25)
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
    out = {"idToMarketParams": sel("idToMarketParams(bytes32)"),
           "market": sel("market(bytes32)")}
    ok = True
    enc = encode(["bytes32"], [bytes(32)])
    ok = ok and len(enc) == 32
    print(json.dumps({"self_check_ok": ok, "out": out}, indent=1))
    return ok


def main():
    out = {"started_at_utc": utcnow(), "markets": {}}
    bn, _ = rpc("eth_blockNumber", [], "head")
    out["head_block"] = int(bn, 16) if bn else None
    if bn:
        b, _ = rpc("eth_getBlockByNumber", [bn, False], "headBlock")
        if b:
            out["head_block_time_utc"] = datetime.datetime.fromtimestamp(
                int(b["timestamp"], 16), datetime.timezone.utc).isoformat()
    pinned = hex(out["head_block"] - 2) if out["head_block"] else "latest"
    out["pinned_block"] = out["head_block"] - 2 if out["head_block"] else None

    def addr(r):
        return "0x" + strip(r)[24:] if r and int(r, 16) else None

    for mid in MARKETS:
        data = sel("idToMarketParams(bytes32)") + strip(mid)
        r, err = rpc("eth_call", [{"to": MORPHO, "data": data}, pinned], "params_" + mid[:10])
        item = {"raw": r, "error": err}
        if r:
            try:
                vals = decode(["address", "address", "address", "address", "uint256"],
                              bytes.fromhex(strip(r)))
                item.update({"loanToken": vals[0], "collateralToken": vals[1],
                             "oracle": vals[2], "irm": vals[3], "lltv": str(vals[4])})
            except Exception as ex:
                item["decode_error"] = repr(ex)
        out["markets"][mid] = item
        if item.get("oracle"):
            oc, _ = rpc("eth_getCode", [item["oracle"], "latest"], "oracle_code_" + mid[:8])
            item["oracle_code_bytes"] = (len(oc) - 2) // 2 if oc else 0
            item["oracle_code_sha256"] = hashlib.sha256(bytes.fromhex(strip(oc))).hexdigest() if oc else None

    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeB-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeB.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("SAVED; requests:", out["request_count_this_script"])
    print(json.dumps(out, ensure_ascii=False, indent=1)[:6000])


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        sys.exit(0 if self_check() else 1)
    main()
