import json, time, datetime, hashlib, os, sys
import requests
from eth_utils import keccak
from eth_abi import encode, decode

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\R-BASE\live-20261109T141903Z\raw"
os.makedirs(OUT, exist_ok=True)
RPCS = [("base-mainnet", "https://mainnet.base.org"),
        ("base-publicnode", "https://base-rpc.publicnode.com")]
sess = requests.Session(); sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [0]

VAULT_A = "0xeE8F4eC5672F09119b96Ab6fB59C27E1b7e44b61"  # Gauntlet USDC Prime (BASE03 verified)
VAULT_B = "0x7BfA7C4f149E7415b73bdeDfe609237e29CBF34A"  # Spark USDC Vault (BASE03 verified)
MORPHO = "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
AAVE_POOL = "0xA238Dd80C259a72e81d7e4664a9801593F98d1c5"
STATA = "0xC768c589647798a6EE01A91FdE98EF2ed046DBD6"


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def throttle(h):
    n = time.time()
    if h in last and n - last[h] < 0.3:
        time.sleep(0.3 - (n - last[h]))
    last[h] = time.time()


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


def sel(s):
    return "0x" + keccak(text=s)[:4].hex()


def strip(h):
    return h[2:] if isinstance(h, str) and h.startswith("0x") else h


def self_check():
    ok = True
    out = {}
    known = {
        "totalAssets()": "0x01e1d114",
        "totalSupply()": "0x18160ddd",
        "asset()": "0x38d52e0f",
        "convertToAssets(uint256)": None,
        "previewRedeem(uint256)": None,
        "withdrawQueueLength()": None,
        "withdrawQueue(uint256)": None,
        "market(bytes32)": None,
        "balanceOf(address)": "0x70a08231",
        "getReserveData(address)": "0x35ea6a75",
        "decimals()": "0x313ce567",
    }
    for sig, exp in known.items():
        got = sel(sig)
        out[sig] = got
        if exp is not None and got != exp:
            ok = False
    enc = encode(["uint256"], [2])
    ok = ok and len(enc) == 32
    print(json.dumps({"self_check_ok": ok, "selectors": out}, indent=1))
    return ok


def main():
    out = {"started_at_utc": utcnow()}
    cid, _ = rpc("eth_chainId", [], "chainId")
    out["chain_id"] = int(cid, 16) if cid else None
    bn, _ = rpc("eth_blockNumber", [], "blockNumber")
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

    def code(addr, tag):
        c, _ = rpc("eth_getCode", [addr, "latest"], tag)
        return {"address": addr, "bytes": (len(c) - 2) // 2 if c else 0,
                "sha256": hashlib.sha256(bytes.fromhex(strip(c))).hexdigest() if c else None}

    def u(r):
        return int(r, 16) if r else None

    def addr(r):
        return "0x" + strip(r)[24:] if r and int(r, 16) else None

    out["contracts"] = {
        "morpho_blue": code(MORPHO, "code_morpho"),
        "usdc": code(USDC, "code_usdc"),
        "aave_pool": code(AAVE_POOL, "code_aave_pool"),
        "stata": code(STATA, "code_stata"),
    }
    morpho_usdc_balance = u(call(USDC, sel("balanceOf(address)") +
                               encode(["address"], [MORPHO]).hex(), "morpho_usdc_balance")[0])
    out["morpho_blue_usdc_balance"] = str(morpho_usdc_balance) if morpho_usdc_balance is not None else None

    # ---- MetaMorpho vaults: queue + market-level liquidity ----
    vaults = {}
    all_markets = {}
    for label, vaddr in (("gauntlet_usdc_prime", VAULT_A), ("spark_usdc", VAULT_B)):
        v = {"address": vaddr, **code(vaddr, "code_" + label)}
        for fld, sig in (("name", "name()"), ("symbol", "symbol()"),
                         ("decimals", "decimals()"), ("asset", "asset()"),
                         ("totalAssets", "totalAssets()"),
                         ("totalSupply", "totalSupply()"),
                         ("curator", "curator()"), ("owner", "owner()")):
            r, err = call(vaddr, sel(sig), label + "_" + fld)
            item = {"raw": r, "error": err}
            if fld in ("name", "symbol"):
                b = bytes.fromhex(strip(r)) if r else b""
                try:
                    off = int.from_bytes(b[:32], "big"); ln = int.from_bytes(b[off:off + 32], "big")
                    item["value"] = b[off + 32:off + 32 + ln].decode("utf-8", "replace")
                except Exception:
                    item["value"] = None
            elif fld in ("asset", "curator", "owner"):
                item["value"] = addr(r)
            else:
                item["value"] = str(int(r, 16)) if r else None
            v[fld] = item
        idle = u(call(USDC, sel("balanceOf(address)") + encode(["address"], [vaddr]).hex(),
                      label + "_usdc_balance")[0])
        v["idle_usdc"] = str(idle) if idle is not None else None
        # withdrawQueue
        r, _ = call(vaddr, sel("withdrawQueueLength()"), label + "_wq_len")
        n = int(r, 16) if r else 0
        v["withdrawQueueLength"] = n
        ids = []
        for i in range(n if n and n <= 8 else 0):
            rr, err = call(vaddr, sel("withdrawQueue(uint256)") + encode(["uint256"], [i]).hex(),
                           f"{label}_wq_{i}")
            if rr:
                hid = strip(rr)
                ids.append("0x" + hid)
                all_markets["0x" + hid] = None
        v["withdrawQueue"] = ids
        vaults[label] = v
    out["vaults"] = vaults

    # ---- Morpho Blue market states (dedup across vaults) ----
    markets = {}
    for mid in all_markets:
        r, err = call(MORPHO, sel("market(bytes32)") + strip(mid), "market_" + mid[:10])
        item = {"raw": r, "error": err}
        if r:
            try:
                vals = decode(["uint128", "uint128", "uint128", "uint128", "uint128", "uint128"],
                              bytes.fromhex(strip(r)))
                item.update({
                    "totalSupplyAssets": str(vals[0]), "totalSupplyShares": str(vals[1]),
                    "totalBorrowAssets": str(vals[2]), "totalBorrowShares": str(vals[3]),
                    "lastUpdate": str(vals[4]), "fee": str(vals[5]),
                    "availableAssets": str(vals[0] - vals[2]) if vals[0] >= vals[2] else "0",
                    "utilization_pct": round(vals[2] * 100 / vals[0], 2) if vals[0] else None,
                })
            except Exception as ex:
                item["decode_error"] = repr(ex)
        markets[mid] = item
    out["morpho_markets"] = markets

    # ---- per-vault withdrawable upper bound ----
    calc = {}
    for label, v in vaults.items():
        ids = v.get("withdrawQueue", [])
        per_market = []
        sum_min = 0
        sum_avail = 0
        for mid in ids:
            m = markets.get(mid) or {}
            if "availableAssets" not in m:
                per_market.append({"id": mid, "error": "market unreadable"})
                continue
            avail = int(m["availableAssets"])
            supply = int(m["totalSupplyAssets"])
            borrow = int(m["totalBorrowAssets"])
            withdrawable = min(supply, min(supply - borrow if supply > borrow else 0,
                                          morpho_usdc_balance or 0))
            sum_min += withdrawable
            sum_avail += avail
            per_market.append({"id": mid, "supplyAssets": str(supply),
                               "borrowAssets": str(borrow),
                               "utilization_pct": m.get("utilization_pct"),
                               "availableAssets": str(avail),
                               "withdrawable_bound": str(withdrawable)})
        ta = int((v.get("totalAssets") or {}).get("value") or 0)
        ts = int((v.get("totalSupply") or {}).get("value") or 0)
        idle = int(v.get("idle_usdc") or 0)
        redeemable_upper = idle + min(sum_min, morpho_usdc_balance or 0)
        calc[label] = {
            "totalAssets": str(ta), "totalSupply": str(ts), "idle_usdc": str(idle),
            "morpho_blue_usdc_balance_shared": str(morpho_usdc_balance),
            "sum_available_assets_upper": str(sum_min),
            "redeemable_upper_bound": str(redeemable_upper),
            "nav_per_share_1e18": str(ta * 10**18 // ts) if ts else None,
            "immediate_redeemable_per_share_1e18": (
                str(redeemable_upper * 10**18 // ts) if ts else None),
            "gap_pct_of_nav": round((ta - redeemable_upper) * 100 / ta, 4) if ta else None,
            "markets": per_market,
        }
    out["vault_liquidity_analysis"] = calc

    # ---- Aave Base USDC STATA (reference cross-check) ----
    stata = {"address": STATA}
    for fld, sig in (("name", "name()"), ("symbol", "symbol()"),
                     ("decimals", "decimals()"), ("asset", "asset()"),
                     ("totalAssets", "totalAssets()"), ("totalSupply", "totalSupply()")):
        r, err = call(STATA, sel(sig), "stata_" + fld)
        item = {"raw": r, "error": err}
        if fld in ("name", "symbol"):
            b = bytes.fromhex(strip(r)) if r else b""
            try:
                off = int.from_bytes(b[:32], "big"); ln = int.from_bytes(b[off:off + 32], "big")
                item["value"] = b[off + 32:off + 32 + ln].decode("utf-8", "replace")
            except Exception:
                item["value"] = None
        elif fld == "asset":
            item["value"] = addr(r)
        else:
            item["value"] = str(int(r, 16)) if r else None
        stata[fld] = item
    for fld, sig, arg in (("previewRedeem_1share", "previewRedeem(uint256)", 10**18),
                          ("maxRedeem_dead", "maxRedeem(address)",
                           "0x000000000000000000000000000000000000dEaD")):
        data = sel(sig) + (encode(["uint256"], [arg]).hex() if sig.startswith("previewRedeem")
                           else encode(["address"], [arg]).hex())
        r, err = call(STATA, data, "stata_" + fld)
        stata[fld] = {"value": str(int(r, 16)) if r else None, "error": err}
    r, _ = call(AAVE_POOL, sel("getReserveData(address)") + encode(["address"], [USDC]).hex(),
                "aave_reserve_usdc")
    reserve = {}
    if r:
        words = [strip(r)[i:i + 64] for i in range(0, len(strip(r)), 64)]
        try:
            reserve["aToken"] = "0x" + words[8][24:]
            reserve["stableDebtToken"] = "0x" + words[9][24:]
            reserve["variableDebtToken"] = "0x" + words[10][24:]
        except Exception as ex:
            reserve["decode_error"] = repr(ex)
    for fld in ("aToken", "stableDebtToken", "variableDebtToken"):
        if reserve.get(fld):
            rr, err = call(reserve[fld], sel("totalSupply()"), "aave_" + fld + "_supply")
            reserve[fld + "_totalSupply"] = str(int(rr, 16)) if rr else None
            reserve[fld + "_error"] = err
    out["aave_base_usdc_reserve"] = reserve
    if reserve.get("aToken_totalSupply"):
        a = int(reserve["aToken_totalSupply"])
        v_ = int(reserve.get("variableDebtToken_totalSupply") or 0)
        s_ = int(reserve.get("stableDebtToken_totalSupply") or 0)
        out["aave_usdc_withdrawable"] = str(max(a - v_ - s_, 0))
    out["stata"] = stata

    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeA-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeA.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("SAVED; requests:", out["request_count_this_script"])
    print(json.dumps({k: out.get(k) for k in (
        "chain_id", "head_block", "head_block_time_utc", "pinned_block", "morpho_blue_usdc_balance",
        "vault_liquidity_analysis", "aave_usdc_withdrawable", "contracts")},
        ensure_ascii=False, indent=1)[:9000])


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        sys.exit(0 if self_check() else 1)
    main()
