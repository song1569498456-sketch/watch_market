import json, time, datetime, hashlib, os
import requests
from eth_utils import keccak
from eth_abi import encode, decode

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\ARB04\live-20261109T141903Z\raw"
os.makedirs(OUT, exist_ok=True)
sess = requests.Session(); sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [0]
RPCS = [("arb1", "https://arb1.arbitrum.io/rpc"),
        ("arb-publicnode", "https://arbitrum-one-rpc.publicnode.com")]


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def throttle(h):
    n = time.time()
    if h in last and n - last[h] < 0.3:
        time.sleep(0.3 - (n - last[h]))
    last[h] = time.time()


def http_get(url, tag, host):
    throttle(host); count[0] += 1
    e = {"n": count[0], "kind": "GET", "host": host, "tag": tag, "url": url,
         "at_utc": utcnow()}
    try:
        r = sess.get(url, timeout=25)
        e["http_status"] = r.status_code
        e["sha256"] = hashlib.sha256(r.content).hexdigest()
        e["bytes"] = len(r.content)
        log.append(e)
        return r.status_code, r.json()
    except Exception as ex:
        e["error"] = repr(ex); log.append(e); return None, None


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


def strip(h):
    return h[2:] if isinstance(h, str) and h.startswith("0x") else h


def sel(s):
    return "0x" + keccak(text=s)[:4].hex()


def dec_str(r):
    if not r:
        return None
    b = bytes.fromhex(strip(r))
    try:
        off = int.from_bytes(b[:32], "big"); ln = int.from_bytes(b[off:off + 32], "big")
        return b[off + 32:off + 32 + ln].decode("utf-8", "replace")
    except Exception:
        return None


def selectors_from_code(code_hex):
    b = bytes.fromhex(strip(code_hex)) if code_hex else b""
    found = set()
    for i in range(len(b) - 4):
        if b[i] == 0x63:
            found.add("0x" + b[i + 1:i + 5].hex())
    return found


def main():
    out = {"started_at_utc": utcnow()}
    STATA = "0x7F6501d3B98eE91f9b9535E4b0ac710Fb0f9e0bc"
    STATIC_A = "0x7CFaDFD5645B50bE87d546f42699d863648251ad"
    USDC = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
    AAVE_POOL = "0x794a61358D6845594F94dc1DB02A252b5b4814aD"
    IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"

    cid, _ = rpc("eth_chainId", [], "chainId")
    out["chain_id"] = int(cid, 16) if cid else None
    bn, _ = rpc("eth_blockNumber", [], "blockNumber")
    out["head_block"] = int(bn, 16) if bn else None
    if bn:
        b, _ = rpc("eth_getBlockByNumber", [bn, False], "headBlock")
        if b:
            out["head_block_time_utc"] = datetime.datetime.fromtimestamp(
                int(b["timestamp"], 16), datetime.timezone.utc).isoformat()
    out["pinned_block"] = out["head_block"] - 2 if out["head_block"] else None
    pinned = hex(out["pinned_block"]) if out["pinned_block"] else "latest"

    def call(to, data, tag, block=None):
        return rpc("eth_call", [{"to": to, "data": data}, block or pinned], tag)

    # ---------- Beefy official vault list ----------
    st, j = http_get("https://api.beefy.finance/vaults", "beefy_vaults",
                     "api.beefy.finance")
    beefy = {"http_status": st, "arbitrum_usdc_vaults": [], "error": None}
    if isinstance(j, dict):
        for vid, v in j.items():
            try:
                if v.get("chain") != "arbitrum":
                    continue
                token = str(v.get("token", ""))
                if "USDC" not in token.upper() and "USD" not in token.upper():
                    continue
                beefy["arbitrum_usdc_vaults"].append({
                    "id": vid, "name": v.get("name"), "token": token,
                    "tokenAddress": v.get("tokenAddress"),
                    "earnedTokenAddress": v.get("earnedTokenAddress"),
                    "status": v.get("status"), "platform": v.get("platform")})
            except Exception:
                continue
    beefy["count"] = len(beefy["arbitrum_usdc_vaults"])
    out["beefy"] = beefy

    # ---------- STATA identity / ERC-4626 rules ----------
    def code(addr, tag):
        c, _ = rpc("eth_getCode", [addr, "latest"], tag)
        return c

    stata = {"address": STATA}
    c = code(STATA, "code_stata")
    stata["code_bytes"] = (len(c) - 2) // 2 if c else 0
    stata["code_sha256"] = hashlib.sha256(bytes.fromhex(strip(c))).hexdigest() if c else None
    stata["impl_slot"], _ = rpc("eth_getStorageAt", [STATA, IMPL_SLOT, "latest"],
                                "stata_impl_slot")
    impl = "0x" + strip(stata["impl_slot"])[24:] if stata["impl_slot"] else None
    stata["impl"] = impl
    impl_code = code(impl, "code_stata_impl") if impl else None
    stata["impl_code_bytes"] = (len(impl_code) - 2) // 2 if impl_code else 0
    sels = selectors_from_code(impl_code)
    wanted = {
        "asset()": sel("asset()"), "totalAssets()": sel("totalAssets()"),
        "totalSupply()": sel("totalSupply()"), "convertToAssets(uint256)": sel("convertToAssets(uint256)"),
        "previewRedeem(uint256)": sel("previewRedeem(uint256)"),
        "previewWithdraw(uint256)": sel("previewWithdraw(uint256)"),
        "maxRedeem(address)": sel("maxRedeem(address)"),
        "maxWithdraw(address)": sel("maxWithdraw(address)"),
        "redeem(uint256,address,address)": sel("redeem(uint256,address,address)"),
        "withdraw(uint256,address,address)": sel("withdraw(uint256,address,address)"),
        "deposit(uint256,address)": sel("deposit(uint256,address)"),
        "requestRedeem(uint256,address,address)": sel("requestRedeem(uint256,address,address)"),
        "claimRedeem(address)": sel("claimRedeem(address)"),
        "pendingRedeemRequest(address)": sel("pendingRedeemRequest(address)"),
    }
    stata["selector_presence"] = {k: (v in sels) for k, v in wanted.items()}
    stata["selector_count"] = len(sels)
    for fld, sig in (("name", "name()"), ("symbol", "symbol()"),
                     ("decimals", "decimals()"), ("asset", "asset()"),
                     ("totalAssets", "totalAssets()"), ("totalSupply", "totalSupply()")):
        r, err = call(STATA, sel(sig), "stata_" + fld)
        if fld in ("name", "symbol"):
            stata[fld] = dec_str(r)
        elif fld == "decimals":
            stata[fld] = int(strip(r), 16) if r else None
        elif fld == "asset":
            stata[fld] = "0x" + strip(r)[24:] if r else None
        else:
            stata[fld] = str(int(r, 16)) if r else None
        stata[fld + "_error"] = err
    # share -> asset conversions at fixed block
    if stata.get("decimals"):
        one_share = 10 ** stata["decimals"]
        for fld, sig in (("convertToAssets_1", "convertToAssets(uint256)"),
                         ("previewRedeem_1", "previewRedeem(uint256)")):
            r, err = call(STATA, sel(sig) + encode(["uint256"], [one_share]).hex(),
                          "stata_" + fld)
            stata[fld] = str(int(r, 16)) if r else None
            stata[fld + "_error"] = err
    out["stata"] = stata
    # static a token quick check
    static_a = {"address": STATIC_A}
    c = code(STATIC_A, "code_static_a")
    static_a["code_bytes"] = (len(c) - 2) // 2 if c else 0
    for fld, sig in (("name", "name()"), ("symbol", "symbol()"), ("decimals", "decimals()")):
        r, err = call(STATIC_A, sel(sig), "static_a_" + fld)
        static_a[fld] = dec_str(r) if fld in ("name", "symbol") else (
            int(strip(r), 16) if r else None)
    out["static_a_token"] = static_a

    # ---------- Aave USDCn liquidity (real redeem capacity at pool) ----------
    aave = {}
    r, err = call(AAVE_POOL, sel("getReserveData(address)") + encode(["address"], [USDC]).hex(),
                  "aave_reserve_data_usdc")
    aave["getReserveData_error"] = err
    if r:
        words = [strip(r)[i:i + 64] for i in range(0, len(strip(r)), 64)]
        aave["words"] = len(words)
        try:
            aave["aToken"] = "0x" + words[8][24:]
            aave["stableDebtToken"] = "0x" + words[9][24:]
            aave["variableDebtToken"] = "0x" + words[10][24:]
        except Exception as ex:
            aave["decode_error"] = repr(ex)
    for fld in ("aToken", "stableDebtToken", "variableDebtToken"):
        addr = aave.get(fld)
        if addr:
            rr, err2 = call(addr, sel("totalSupply()"), "aave_" + fld + "_supply")
            aave[fld + "_totalSupply"] = str(int(rr, 16)) if rr else None
            aave[fld + "_error"] = err2
    out["aave_usdc"] = aave

    # ---------- Beefy vault on-chain state (first candidate) ----------
    bv = None
    if beefy["arbitrum_usdc_vaults"]:
        # prefer active + USDC token with 'moo' earned token
        cands = [v for v in beefy["arbitrum_usdc_vaults"]
                 if v.get("status") == "active" and v.get("earnedTokenAddress")]
        bv = cands[0] if cands else beefy["arbitrum_usdc_vaults"][0]
    if bv:
        vault = {"api": bv}
        vaddr = bv["earnedTokenAddress"]
        vault["address"] = vaddr
        c = code(vaddr, "code_beefy_vault")
        vault["code_bytes"] = (len(c) - 2) // 2 if c else 0
        vault["code_sha256"] = hashlib.sha256(bytes.fromhex(strip(c))).hexdigest() if c else None
        for fld, sig in (("want", "want()"), ("strategy", "strategy()"),
                         ("totalSupply", "totalSupply()"), ("balance", "balance()"),
                         ("available", "available()"),
                         ("getPricePerFullShare", "getPricePerFullShare()")):
            rr, err = call(vaddr, sel(sig), "beefy_" + fld)
            if fld in ("want", "strategy"):
                vault[fld] = "0x" + strip(rr)[24:] if rr else None
            elif rr:
                vault[fld] = str(int(rr, 16))
            else:
                vault[fld + "_error"] = err
        out["beefy_vault"] = vault
    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeA-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeA.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:9000])


if __name__ == "__main__":
    main()
