import json, time, datetime, hashlib, os, sys
import requests

PROXY = "http://127.0.0.1:7897"
OUT = r"D:\ds-arb-test\watch_market\evidence\SOL03\live-20261109T141903Z\raw"
os.makedirs(OUT, exist_ok=True)
RPC = "https://api.mainnet-beta.solana.com"
sess = requests.Session(); sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}
sess.headers.update({"User-Agent": "watch_market-research/1.0"})
log = []; count = [0]; last = {}; _id = [0]

GENESIS_EXPECT = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"
PROGRAMS = {
    "kamino_klend": "KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD",
    "solend": "So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpAo",
    "marginfi_v2": "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA",
}
B58_ALPHA = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


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
        idx = B58_ALPHA.find(ch)
        if idx < 0:
            raise ValueError("bad base58 char")
        n = n * 58 + idx
    b = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = 0
    for ch in s:
        if ch == "1":
            pad += 1
        else:
            break
    return b"\x00" * pad + b


def b58encode(b):
    n = int.from_bytes(b, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = B58_ALPHA[r] + out
    pad = 0
    for x in b:
        if x == 0:
            pad += 1
        else:
            break
    return "1" * pad + out


def http_get(url, tag, host):
    throttle(host); count[0] += 1
    e = {"n": count[0], "kind": "GET", "host": host, "tag": tag, "url": url,
         "at_utc": utcnow()}
    try:
        r = sess.get(url, timeout=25)
        e["http_status"] = r.status_code
        e["sha256"] = hashlib.sha256(r.content).hexdigest()
        log.append(e)
        return r.status_code, r.text
    except Exception as ex:
        e["error"] = repr(ex); log.append(e); return None, ""


def sol_rpc(method, params, tag):
    throttle("api.mainnet-beta.solana.com"); _id[0] += 1; count[0] += 1
    e = {"n": count[0], "kind": "POST", "host": "api.mainnet-beta.solana.com",
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


def self_check():
    ok = True
    checks = {}
    # base58 roundtrip on program ids (32-byte pubkeys)
    for name, pid in PROGRAMS.items():
        try:
            raw = b58decode(pid)
            checks[name] = {"len": len(raw), "roundtrip": b58encode(raw) == pid}
            ok = ok and len(raw) == 32 and checks[name]["roundtrip"]
        except Exception as ex:
            checks[name] = {"error": repr(ex)}
            ok = False
    checks["genesis_len"] = len(b58decode(GENESIS_EXPECT))
    ok = ok and checks["genesis_len"] == 32
    print(json.dumps({"self_check_ok": ok, "checks": checks}, indent=1))
    return ok


def parse_program_data(program_name, prog_info):
    """program account data: u32 discriminant(=2) + programdata pubkey(32)."""
    info = {"program": program_name}
    if not prog_info or "value" not in prog_info or prog_info["value"] is None:
        info["error"] = "program account not found"
        return info
    v = prog_info["value"]
    info["owner"] = v.get("owner")
    info["executable"] = v.get("executable")
    info["lamports"] = v.get("lamports")
    info["space"] = v.get("space")
    data = v.get("data") or []
    if isinstance(data, list) and data and data[0] == "base64":
        raw = __import__("base64").b64decode(data[1])
        info["data_len"] = len(raw)
        info["discriminant"] = int.from_bytes(raw[:4], "little") if len(raw) >= 4 else None
        if len(raw) >= 36:
            info["programdata"] = None
            from_pk = b58encode(raw[4:36])
            info["programdata"] = from_pk
    return info


def main():
    out = {"started_at_utc": utcnow()}
    gh, _ = sol_rpc("getGenesisHash", [], "genesisHash")
    out["genesis_hash"] = gh
    slot, _ = sol_rpc("getSlot", [], "slot")
    out["slot"] = slot
    bh, _ = sol_rpc("getBlockHeight", [], "blockHeight")
    out["block_height"] = bh
    ei, _ = sol_rpc("getEpochInfo", [], "epochInfo")
    out["epoch_info"] = ei
    ver, _ = sol_rpc("getVersion", [], "version")
    out["version"] = ver

    # program accounts (executable + owner + programdata)
    progs = {}
    for name, pid in PROGRAMS.items():
        info, _ = sol_rpc("getAccountInfo", [pid, {"encoding": "base64",
                                                   "dataSlice": {"offset": 0, "length": 36}}],
                          "acct_" + name)
        progs[name] = {"program_id": pid, **parse_program_data(name, info)}
    # ProgramData accounts -> upgrade authority + last deploy slot
    for name, p in progs.items():
        pd = p.get("programdata")
        if not pd:
            continue
        info, _ = sol_rpc("getAccountInfo", [pd, {"encoding": "base64",
                                                   "dataSlice": {"offset": 0, "length": 48}}],
                          "acct_pd_" + name)
        item = {"address": pd}
        if info and info.get("value"):
            v = info["value"]
            item["owner"] = v.get("owner")
            item["executable"] = v.get("executable")
            data = v.get("data") or []
            if isinstance(data, list) and data and data[0] == "base64":
                raw = __import__("base64").b64decode(data[1])
                item["discriminant"] = int.from_bytes(raw[:4], "little") if len(raw) >= 4 else None
                if len(raw) >= 12:
                    item["slot"] = int.from_bytes(raw[4:12], "little")
                if len(raw) >= 13:
                    tag = raw[12]
                    item["upgrade_authority_option"] = tag
                    if tag == 1 and len(raw) >= 45:
                        item["upgrade_authority"] = b58encode(raw[13:45])
        p["programdata_info"] = item
    out["programs"] = progs

    # Solend official config API (params: LTV / liquidation threshold / bonus / oracle)
    solend = {}
    for tag, url in (
            ("solend_markets_configs",
             "https://api.solend.fi/v1/markets/configs?scope=all&deployment=production"),
            ("solend_reserves",
             "https://api.solend.fi/v1/reserves?scope=all&deployment=production")):
        st, txt = http_get(url, tag, "api.solend.fi")
        parsed = None
        try:
            parsed = json.loads(txt) if txt else None
        except Exception:
            parsed = None
        solend[tag] = {"http_status": st,
                       "keys": (list(parsed.keys()) if isinstance(parsed, dict) else type(parsed).__name__),
                       "raw_text_prefix": (txt or "")[:500]}
        if isinstance(parsed, dict):
            open(OUT + "\\" + tag + ".json", "w", encoding="utf-8").write(txt or "")
    out["solend_api"] = solend

    out["finished_at_utc"] = utcnow()
    out["request_count_this_script"] = count[0]
    json.dump(log, open(OUT + r"\probeA-log.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(out, open(OUT + r"\probeA.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("SAVED; requests:", out["request_count_this_script"])
    print(json.dumps(out, ensure_ascii=False, indent=1)[:9000])


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        sys.exit(0 if self_check() else 1)
    main()
