import json, time, datetime, hashlib, os, re
import requests
from eth_utils import keccak
from eth_abi import encode

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\BNB01\live-20261109T141903Z\raw"
sess = requests.Session(); sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [900]

PSM = "0xaa57F36DD5Ef2aC471863ec46277f976f272eC0c"
VAULT = "0x5763DDeB60c82684F3D0098aEa5076C0Da972ec7"
VENUS_ADAPTER = "0xf76D9cFD08dF91491680313B1A5b44307129CDa9"


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def throttle(h):
    n = time.time()
    if h in last and n - last[h] < 0.35:
        time.sleep(0.35 - (n - last[h]))
    last[h] = time.time()


def http_get(url, tag):
    host = url.split("/")[2]
    throttle(host); count[0] += 1
    e = {"n": count[0], "kind": "GET", "host": host, "tag": tag, "url": url,
         "at_utc": utcnow()}
    for attempt in range(3):
        try:
            r = sess.get(url, timeout=25)
            e["http_status"] = r.status_code
            e["sha256"] = hashlib.sha256(r.content).hexdigest()
            log.append(e)
            return r.status_code, r.text
        except Exception as ex:
            e["error_attempt_%d" % attempt] = repr(ex)
            time.sleep(0.5)
    log.append(e)
    return None, ""


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


def sel(s):
    return "0x" + keccak(text=s)[:4].hex()


def funcs_and_vars(src):
    res = []
    for m in re.finditer(r"function\s+(\w+)\s*\(([^)]*)\)([^{;]*)", src):
        name, args, rest = m.group(1), m.group(2), m.group(3)
        types = []; ok = True
        for a in [x.strip() for x in args.split(",") if x.strip()]:
            parts = a.split()
            if len(parts) < 2:
                ok = False; break
            types.append(re.sub(r"\s*(memory|calldata|storage)\s*$", "", parts[0]))
        if ok:
            view = ("view" in rest or "pure" in rest)
            res.append({"sig": f"{name}({','.join(types)})",
                        "selector": sel(f"{name}({','.join(types)})"),
                        "view": view})
    for m in re.finditer(r"(address|uint256|uint128|uint24|bool|int256|uint32)"
                         r"\s+public\s+(?:constant\s+|immutable\s+)?(\w+)", src):
        res.append({"sig": f"{m.group(2)}()",
                    "selector": sel(f"{m.group(2)}()"), "view": True})
    return res


def main():
    out = {"started_at_utc": utcnow()}
    # PSM sell/buy bodies from locally saved source
    psm_src = open(OUT + r"\lista_PSM.sol", encoding="utf-8").read()
    def body(name):
        m = re.search(r"function\s+" + name + r"\s*\([^)]*\)[^{]*\{", psm_src)
        if not m:
            return None
        i = m.end(); depth = 1; j = i
        while j < len(psm_src) and depth:
            if psm_src[j] == "{": depth += 1
            elif psm_src[j] == "}": depth -= 1
            j += 1
        return psm_src[m.start():j]
    out["psm_source_sell"] = body("sell")
    out["psm_source_buy"] = body("buy")
    out["psm_source_total_sell_limit"] = body("getTotalSellLimit")
    out["psm_source_check_buy_limit"] = body("checkBuyLimit")

    # fetch VaultManager + VenusAdapter sources
    for key, fname in (("vault_src", "contracts/psm/VaultManager.sol"),
                       ("adapter_src", "contracts/psm/VenusAdapter.sol"),
                       ("poolset_src", "contracts/psm/LisUSDPoolSet.sol")):
        st, txt = http_get(
            "https://raw.githubusercontent.com/lista-dao/lista-dao-contracts/main/" + fname,
            key)
        out[key] = {"http_status": st, "chars": len(txt or ""),
                    "sha256": hashlib.sha256((txt or "").encode()).hexdigest()}
        open(OUT + "\\" + fname.split("/")[-1], "w", encoding="utf-8").write(txt or "")

    bn, _ = rpc("eth_blockNumber", [], "head")
    out["head_block"] = int(bn, 16) if bn else None
    if bn:
        b, _ = rpc("eth_getBlockByNumber", [bn, False], "headBlock")
        out["head_block_time_utc"] = datetime.datetime.fromtimestamp(
            int(b["timestamp"], 16), datetime.timezone.utc).isoformat()
    out["pinned_block"] = out["head_block"] - 2 if out["head_block"] else None
    pinned = hex(out["pinned_block"]) if out["pinned_block"] else "latest"

    def call(to, data, tag):
        return rpc("eth_call", [{"to": to, "data": data}, pinned], tag)

    # zero-arg view reads on VaultManager / VenusAdapter / PoolSet, selected by name
    want = {
        "VaultManager": ["totalAssets", "token", "psm", "lisUSD", "withdrawDelay",
                         "delay", "totalSupply", "getRate", "duty",
                         "totalSellLimit", "sellLimit"],
        "VenusAdapter": ["totalAssets", "vToken", "token", "psm", "vUSDT",
                         "underlying", "balanceOf", "getCash", "totalSupply"],
        "LisUSDPoolSet": ["totalAssets", "getRate", "totalSupply", "assets",
                          "lisUSD", "token", "maxAmount", "delay",
                          "withdrawDelay"],
    }
    reads = {"VaultManager": [], "VenusAdapter": [], "LisUSDPoolSet": []}
    for fname, key in (("VaultManager.sol", "VaultManager"),
                       ("VenusAdapter.sol", "VenusAdapter"),
                       ("LisUSDPoolSet.sol", "LisUSDPoolSet")):
        path = OUT + "\\" + fname
        if not os.path.exists(path):
            continue
        src = open(path, encoding="utf-8").read()
        names = set()
        for f in funcs_and_vars(src):
            name = f["sig"].split("(")[0]
            if name in want[key] and "()" in f["sig"]:
                names.add((f["sig"], f["selector"]))
        reads[key] = [{"sig": s, "selector": sel_, "raw": None, "error": None}
                      for s, sel_ in sorted(names)]
    addr = {"VaultManager": VAULT, "VenusAdapter": VENUS_ADAPTER,
            "LisUSDPoolSet": "0x37DB1AE9B24055D1F9fE973Aea40B7EB2995D0Bf"}
    for key in reads:
        for item in reads[key]:
            r, err = call(addr[key], item["selector"], f"{key}_{item['sig']}")
            item["raw"] = r; item["error"] = err
            if r:
                try:
                    item["uint"] = str(int(r, 16))
                except Exception:
                    pass
    out["reads"] = reads

    # venus vToken balances: read vToken address from adapter getter if found, then balanceOf
    vtok = None
    for item in reads.get("VenusAdapter", []):
        if item["sig"] in ("vToken()", "vUSDT()") and item.get("raw"):
            vtok = "0x" + strip(item["raw"])[24:]
            break
    out["vToken_candidate"] = vtok
    if vtok:
        vbal = {}
        for holder_name, holder in (("VaultManager", VAULT),
                                    ("VenusAdapter", VENUS_ADAPTER)):
            r, err = call(vtok, sel("balanceOf(address)") +
                          encode(["address"], [holder]).hex(),
                          f"vtoken_bal_{holder_name}")
            vbal[holder_name] = {"vToken": vtok, "raw": r,
                                 "value": str(int(r, 16)) if r else None,
                                 "error": err}
        out["vToken_balances"] = vbal

    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeE-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeE.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:12000])


if __name__ == "__main__":
    main()
