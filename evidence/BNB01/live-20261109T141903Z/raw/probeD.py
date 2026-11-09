import json, time, datetime, hashlib, os, re
import requests
from eth_utils import keccak
from eth_abi import encode

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\BNB01\live-20261109T141903Z\raw"
sess = requests.Session(); sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [500]


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
            e["http_status"] = r.status_code; e["bytes"] = len(r.content)
            e["sha256"] = hashlib.sha256(r.content).hexdigest(); log.append(e)
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


PSM = "0xaa57F36DD5Ef2aC471863ec46277f976f272eC0c"
LISUSD = "0x0782b6d8c4551B9760e74c0545a9bCD90bdc41E5"
USDT = "0x55d398326f99059fF775485246999027B3197955"
VAULT = "0x5763DDeB60c82684F3D0098aEa5076C0Da972ec7"
VENUS_ADAPTER = "0xf76D9cFD08dF91491680313B1A5b44307129CDa9"
POOLSET = "0x37DB1AE9B24055D1F9fE973Aea40B7EB2995D0Bf"
EARNPOOL = "0x66dE07893Db7492B56bA88503B4cC99bAb1796F3"
IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"


def main():
    out = {"started_at_utc": utcnow(), "psm_address": PSM}
    st, src = http_get(
        "https://raw.githubusercontent.com/lista-dao/lista-dao-contracts/main/contracts/psm/PSM.sol",
        "psm_sol_full")
    out["psm_source"] = {"http_status": st, "chars": len(src),
                         "sha256": hashlib.sha256(src.encode()).hexdigest()}
    open(OUT + r"\lista_PSM.sol", "w", encoding="utf-8").write(src)
    lines = [ln.rstrip() for ln in src.splitlines()]
    interesting = []
    capture = False
    for i, ln in enumerate(lines):
        s = ln.strip()
        if re.match(r"(function\s+(sell|buy|checkBuyLimit|checkAndUpdateBuyUsed|"
                    r"getTotalBuyLimit|getTotalSellLimit|getDayBuyLeft|getDay|"
                    r"pause|unpause|_authorizeUpgrade)\b|"
                    r"(uint256|address|bool|uint24|mapping)\s+public|"
                    r"modifier\s+\w+|"
                    r"event\s+\w+|"
                    r"uint256\s+(public\s+)?(sellFee|buyFee|dailyLimit|minSell|minBuy|"
                    r"totalSell|dayBuyUsed|daySellUsed)\b)", s):
            interesting.append(s)
    out["psm_source_key_lines"] = interesting[:120]
    out["psm_source_has_whitelist_words"] = [w for w in
        ("whitelist", "whitelisted", "allowlist", "kyc", "onlyRole", "blacklist")
        if w.lower() in src.lower()]
    # number of role-gated modifiers found in key lines
    out["psm_source_role_gated_functions"] = ([ln for ln in interesting
                                                if "onlyRole" in ln][:20])

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

    def code(addr, tag):
        c, _ = rpc("eth_getCode", [addr, "latest"], tag)
        return (len(c) - 2) // 2 if c else 0, (
            hashlib.sha256(bytes.fromhex(strip(c))).hexdigest() if c else None)

    contracts = {}
    for name, addr in (("PSM", PSM), ("VaultManager", VAULT),
                       ("VenusAdapter", VENUS_ADAPTER),
                       ("LisUSDPoolSet", POOLSET), ("EarnPool", EARNPOOL)):
        cbytes, chash = code(addr, "code_" + name)
        contracts[name] = {"address": addr, "code_bytes": cbytes,
                           "code_sha256": chash}
    out["contracts"] = contracts
    out["PSM_impl_slot"], _ = rpc("eth_getStorageAt", [PSM, IMPL_SLOT, "latest"],
                                  "psm_impl_slot")

    # PSM state reads: include public variable getters and explicit view functions
    state = {}
    reads = [
        ("paused", "paused()"), ("sellFee", "sellFee()"), ("buyFee", "buyFee()"),
        ("dailyLimit", "dailyLimit()"), ("minSell", "minSell()"),
        ("minBuy", "minBuy()"), ("feeReceiver", "feeReceiver()"),
        ("token", "token()"), ("lisUSD", "lisUSD()"),
        ("vaultManager", "vaultManager()"),
        ("getTotalBuyLimit", "getTotalBuyLimit()"),
        ("getTotalSellLimit", "getTotalSellLimit()"),
        ("getDayBuyLeft", "getDayBuyLeft()"), ("getDay", "getDay()"),
    ]
    for tag, sig in reads:
        r, err = call(PSM, sel(sig), "psm_" + tag)
        state[tag] = {"raw": r, "error": err}
        if r:
            try:
                state[tag]["uint"] = str(int(r, 16))
            except Exception:
                pass
    out["psm_state"] = state

    def token_balance(token, holder, tag):
        r, err = call(token, sel("balanceOf(address)") +
                      encode(["address"], [holder]).hex(), tag)
        return {"raw": r, "value": str(int(r, 16)) if r else None, "error": err}

    out["balances"] = {
        "USDT_in_PSM": token_balance(USDT, PSM, "usdt_bal_psm"),
        "lisUSD_in_PSM": token_balance(LISUSD, PSM, "lisusd_bal_psm"),
        "USDT_in_VaultManager": token_balance(USDT, VAULT, "usdt_bal_vault"),
        "USDT_in_VenusAdapter": token_balance(USDT, VENUS_ADAPTER, "usdt_bal_adapter"),
        "USDT_in_LisUSDPoolSet": token_balance(USDT, POOLSET, "usdt_bal_poolset"),
        "lisUSD_in_LisUSDPoolSet": token_balance(LISUSD, POOLSET, "lisusd_bal_poolset"),
    }
    # checkBuyLimit(1000e18) view test and checkSell? (source may have checkSellLimit)
    for tag, sig, amt in (
            ("checkBuyLimit_1000", "checkBuyLimit(uint256)", 1000 * 10**18),
            ("checkSellLimit_1000", "checkSellLimit(uint256)", 1000 * 10**18)):
        r, err = call(PSM, sel(sig) + encode(["uint256"], [amt]).hex(), "psm_" + tag)
        out[tag] = {"raw": r, "error": err,
                    "bool_or_uint": (str(int(r, 16)) if r else None)}
    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeD-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeD.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:9000])


if __name__ == "__main__":
    main()
