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
PROGRAMS = {
    "kamino_klend": "KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD",
    "solend": "So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpAo",
    "marginfi_v2": "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA",
}


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def throttle(h):
    n = time.time()
    if h in last and n - last[h] < 0.35:
        time.sleep(0.35 - (n - last[h]))
    last[h] = time.time()


def b58decode(s):
    n = 0
    for ch in s:
        n = n * 58 + B58.index(ch)
    b = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + b


def b58encode(b):
    n = int.from_bytes(b, "big"); out = ""
    while n:
        n, r = divmod(n, 58); out = B58[r] + out
    pad = len(b) - len(b.lstrip(b"\x00"))
    return "1" * pad + out


def http_get(url, tag, host, save_as=None):
    throttle(host); count[0] += 1
    e = {"n": count[0], "kind": "GET", "host": host, "tag": tag, "url": url, "at_utc": utcnow()}
    try:
        r = sess.get(url, timeout=25)
        e["http_status"] = r.status_code
        e["sha256"] = hashlib.sha256(r.content).hexdigest()
        e["bytes"] = len(r.content)
        log.append(e)
        if save_as and r.status_code == 200:
            open(OUT + "\\" + save_as, "w", encoding="utf-8").write(r.text)
        return r.status_code, r.text
    except Exception as ex:
        e["error"] = repr(ex); log.append(e); return None, ""


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
    checks = {}
    for name, pid in PROGRAMS.items():
        raw = b58decode(pid)
        checks[name] = {"len": len(raw), "roundtrip": b58encode(raw) == pid}
        ok = ok and len(raw) == 32 and checks[name]["roundtrip"]
    raw = b58decode("4UpD2fh7xH3VP9QQaXtsS1YY3bxzWhtfpks7FatyKvdY")
    ok = ok and len(raw) == 32
    # decode program state layout (36 bytes): u32 disc + 32B programdata
    fake = (2).to_bytes(4, "little") + bytes(raw)
    checks["program_state_parse"] = {"disc": int.from_bytes(fake[:4], "little"),
                                     "programdata_len": len(b58encode(fake[4:36]))}
    ok = ok and checks["program_state_parse"]["disc"] == 2
    print(json.dumps({"self_check_ok": ok, "checks": checks}, indent=1))
    return ok


def main():
    out = {"started_at_utc": utcnow()}
    slot, _ = sol_rpc("getSlot", [], "slot")
    out["slot"] = slot
    ei, _ = sol_rpc("getEpochInfo", [], "epochInfo")
    out["epoch_info"] = ei

    # 1) program accounts without dataSlice (36 bytes on-chain state)
    progs = {}
    for name, pid in PROGRAMS.items():
        info, err = sol_rpc("getAccountInfo", [pid, {"encoding": "base64"}], "acct_" + name)
        item = {"program_id": pid, "error": err}
        if info and info.get("value"):
            v = info["value"]
            item.update({"owner": v.get("owner"), "executable": v.get("executable"),
                         "lamports": v.get("lamports"), "space": v.get("space")})
            data = v.get("data") or []
            if isinstance(data, list) and data and data[0] == "base64":
                raw = base64.b64decode(data[1])
                item["data_len"] = len(raw)
                item["discriminant"] = int.from_bytes(raw[:4], "little") if len(raw) >= 4 else None
                if len(raw) >= 36:
                    item["programdata"] = b58encode(raw[4:36])
        progs[name] = item
    # 2) ProgramData accounts (dataSlice 48) -> upgrade authority + last deploy slot
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
            data = v.get("data") or []
            if isinstance(data, list) and data and data[0] == "base64":
                raw = base64.b64decode(data[1])
                item["discriminant"] = int.from_bytes(raw[:4], "little") if len(raw) >= 4 else None
                item["last_deploy_slot"] = int.from_bytes(raw[4:12], "little") if len(raw) >= 12 else None
                if len(raw) >= 13:
                    tag = raw[12]
                    item["upgrade_authority_option"] = tag
                    item["upgrade_authority"] = b58encode(raw[13:45]) if (tag == 1 and len(raw) >= 45) else None
        p["programdata_info"] = item
    out["programs"] = progs

    # 3) Solend official config APIs (fresh, saved)
    st, txt = http_get("https://api.solend.fi/v1/markets/configs?scope=all&deployment=production",
                       "solend_markets_configs", "api.solend.fi", "solend_markets_configs.json")
    st2, txt2 = http_get("https://api.solend.fi/v1/reserves?scope=all&deployment=production&limit=1000",
                         "solend_reserves_1000", "api.solend.fi", "solend_reserves_1000.json")
    out["solend_api"] = {"markets_http": st, "reserves_http": st2}
    # parse configs locally
    markets = []
    try:
        markets = json.loads(txt)
    except Exception as ex:
        out["markets_parse_error"] = repr(ex)
    summary = []
    chosen = None
    for m in markets if isinstance(markets, list) else []:
        reserves = m.get("reserves") or []
        summary.append({"name": m.get("name"), "address": m.get("address"),
                        "reserves": len(reserves)})
        if chosen is None and reserves:
            chosen = m
    out["markets_summary"] = summary
    if chosen:
        market = {"name": chosen.get("name"), "address": chosen.get("address"),
                  "authorityAddress": chosen.get("authorityAddress"),
                  "reserves": []}
        # pick reserves with config fields, prefer largest availableAmount if present
        for r in (chosen.get("reserves") or [])[:8]:
            cfg = r.get("config") or {}
            market["reserves"].append({
                "reserve_address": r.get("reserve") or r.get("address"),
                "liquidityToken": (r.get("liquidityToken") or {}).get("symbol") or r.get("liquidityToken"),
                "config_keys": list(cfg.keys()) if isinstance(cfg, dict) else None,
                "config": cfg,
            })
        out["chosen_solend_market"] = market
        # on-chain verify market/reserve/oracle accounts
        addrs = []
        if market["address"]:
            addrs.append(market["address"])
        for r in market["reserves"][:2]:
            if r.get("reserve_address"):
                addrs.append(r["reserve_address"])
            cfg = r.get("config") or {}
            for k in ("pythOracle", "switchboardOracle", "oracle"):
                v = cfg.get(k)
                if isinstance(v, str) and len(v) > 30 and v not in addrs:
                    addrs.append(v)
        addrs = addrs[:10]
        ma, err = sol_rpc("getMultipleAccounts", [addrs, {"encoding": "base64"}],
                          "multiple_accounts")
        ver = {}
        if isinstance(ma, dict) and isinstance(ma.get("value"), list):
            for addr, v in zip(addrs, ma["value"]):
                ver[addr] = ({"exists": False} if v is None else
                             {"exists": True, "owner": v.get("owner"),
                              "executable": v.get("executable"), "lamports": v.get("lamports"),
                              "space": v.get("space")})
        out["onchain_account_verification"] = {"addresses": addrs, "result": ver, "error": err}

    out["slot_after"] = sol_rpc("getSlot", [], "slot_after")[0]
    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeB-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeB.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("SAVED; requests:", out["request_count_this_script"])
    print(json.dumps(out, ensure_ascii=False, indent=1)[:9000])


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        sys.exit(0 if self_check() else 1)
    main()
