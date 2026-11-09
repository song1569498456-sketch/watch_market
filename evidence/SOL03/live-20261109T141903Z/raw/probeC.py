import json, time, datetime, hashlib, os, sys, base64
import requests

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\SOL03\live-20261109T141903Z\raw"
RPC = "https://api.mainnet-beta.solana.com"
sess = requests.Session(); sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [0]
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
PROGRAMS = {"kamino_klend": "KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD",
            "solend": "So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpAo"}


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def throttle(h):
    n = time.time()
    if h in last and n - last[h] < 0.35:
        time.sleep(0.35 - (n - last[h]))
    last[h] = time.time()


def b58encode(b):
    n = int.from_bytes(b, "big"); out = ""
    while n:
        n, r = divmod(n, 58); out = B58[r] + out
    pad = len(b) - len(b.lstrip(b"\x00"))
    return "1" * pad + out


def sol_rpc(method, params, tag):
    throttle("api.mainnet-beta.solana.com"); _id[0] += 1; count[0] += 1
    e = {"n": count[0], "kind": "POST", "host": "api.mainnet-beta.solana.com",
         "tag": tag, "rpc_method": method, "at_utc": utcnow()}
    try:
        r = sess.post(RPC, json={"jsonrpc": "2.0", "id": _id[0], "method": method,
                                 "params": params}, timeout=30)
        e["http_status"] = r.status_code
        j = r.json(); log.append(e)
        if "error" in j:
            e["rpc_error"] = j["error"]; return None, j["error"]
        return j.get("result"), None
    except Exception as ex:
        e["error"] = repr(ex); log.append(e); return None, repr(ex)


def self_check():
    ok = True
    out = {}
    # base58 known roundtrip
    for n, pid in PROGRAMS.items():
        raw = int(0)
        for ch in pid:
            raw = raw * 58 + B58.index(ch)
        b = raw.to_bytes((raw.bit_length() + 7) // 8, "big")
        out[n] = b58encode(b) == pid and len(b) == 32
        ok = ok and out[n]
    print(json.dumps({"self_check_ok": ok, "out": out}, indent=1))
    return ok


def main():
    out = {"started_at_utc": utcnow()}
    slot, _ = sol_rpc("getSlot", [], "slot")
    out["slot"] = slot
    progs = {}
    for name, pid in PROGRAMS.items():
        info, err = sol_rpc("getAccountInfo", [pid, {"encoding": "base64"}], "acct_" + name)
        item = {"program_id": pid, "error": err, "raw_result": info}
        if info and info.get("value"):
            v = info["value"]
            item.update({"owner": v.get("owner"), "executable": v.get("executable"),
                         "space": v.get("space"), "lamports": v.get("lamports"),
                         "data_type": type(v.get("data")).__name__})
            data = v.get("data")
            raw = None
            if isinstance(data, list) and len(data) >= 2:
                raw = base64.b64decode(data[0]) if data[1] == "base64" else None
            elif isinstance(data, str):
                try:
                    raw = base64.b64decode(data)
                except Exception:
                    raw = None
            if raw is not None:
                item["data_len"] = len(raw)
                item["data_prefix_hex"] = raw[:80].hex()
                item["discriminant"] = int.from_bytes(raw[:4], "little") if len(raw) >= 4 else None
                if len(raw) >= 36:
                    item["programdata"] = b58encode(raw[4:36])
        progs[name] = item
    # ProgramData
    for name, p in progs.items():
        pd = p.get("programdata")
        if not pd:
            continue
        info, err = sol_rpc("getAccountInfo", [pd, {"encoding": "base64",
                                                    "dataSlice": {"offset": 0, "length": 48}}],
                            "acct_pd_" + name)
        item = {"address": pd, "error": err}
        if info and info.get("value"):
            v = info["value"]
            item.update({"owner": v.get("owner"), "executable": v.get("executable"),
                         "space": v.get("space")})
            data = v.get("data")
            raw = None
            if isinstance(data, list) and len(data) >= 2:
                raw = base64.b64decode(data[0])
            if raw is not None:
                item["data_len_sliced"] = len(raw)
                item["discriminant"] = int.from_bytes(raw[:4], "little") if len(raw) >= 4 else None
                item["last_deploy_slot"] = int.from_bytes(raw[4:12], "little") if len(raw) >= 12 else None
                if len(raw) >= 13:
                    tag = raw[12]
                    item["upgrade_authority_option"] = tag
                    item["upgrade_authority"] = b58encode(raw[13:45]) if (tag == 1 and len(raw) >= 45) else None
        p["programdata_info"] = item
    out["programs"] = progs

    # ---- select main Solend market reserves from saved /v1/reserves pagination page ----
    MAIN = "4UpD2fh7xH3VP9QQaXtsS1YY3bxzWhtfpks7FatyKvdY"
    try:
        res = json.load(open(OUT + "\\solend_reserves_1000.json", encoding="utf-8"))
        rows = res.get("results") or []
        main_rows = [x for x in rows if (x.get("reserve") or {}).get("lendingMarket") == MAIN]
        rows_sel = []
        for x in main_rows:
            rv = x.get("reserve") or {}
            cfg = rv.get("config") or {}
            liq = rv.get("liquidity") or {}
            rows_sel.append({
                "liquidity_mint": liq.get("mintPubkey"),
                "availableAmount": liq.get("availableAmount"),
                "borrowedAmountWads": liq.get("borrowedAmountWads"),
                "pythOracle": liq.get("pythOracle"),
                "switchboardOracle": liq.get("switchboardOracle"),
                "config": {k: cfg.get(k) for k in ("loanToValueRatio", "liquidationBonus",
                                                   "liquidationThreshold", "maxLiquidationBonus",
                                                   "maxLiquidationThreshold", "depositLimit",
                                                   "borrowLimit", "protocolLiquidationFee",
                                                   "protocolTakeRate", "addedBorrowWeightBPS")},
                "lastUpdate": rv.get("lastUpdate"),
            })
        rows_sel.sort(key=lambda z: int(z.get("availableAmount") or 0), reverse=True)
        out["solend_main_market_selection"] = {"main_market": MAIN, "total_rows": len(rows),
                                               "main_rows": len(main_rows),
                                               "selected_rows": rows_sel[:6]}
    except Exception as ex:
        out["solend_selection_error"] = repr(ex)
    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeC-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeC.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("SAVED; requests:", out["request_count_this_script"])
    print(json.dumps(out, ensure_ascii=False, indent=1)[:9000])


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        sys.exit(0 if self_check() else 1)
    main()
