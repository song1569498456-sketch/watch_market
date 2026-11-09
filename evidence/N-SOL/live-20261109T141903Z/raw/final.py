import json, time, re, hashlib, base64, datetime
import requests

PROXY = "http://127.0.0.1:7897"
BASE = r"D:\ds-arb-test\watch_market\evidence\N-SOL\live-20261109T141903Z\raw"
RPC = "https://api.mainnet-beta.solana.com"
s = requests.Session(); s.trust_env = False
s.proxies = {"http": PROXY, "https": PROXY}
s.headers.update({"User-Agent": "watch_market-readonly-research/1.0"})
now = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
reqs = []

def save(name, obj):
    json.dump(obj, open(BASE + "\\" + name, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

def http_get(url, name):
    t0 = time.time()
    try:
        r = s.get(url, timeout=30)
        reqs.append({"url": url, "name": name, "http_status": r.status_code,
                     "retrieved_at_utc": now(), "bytes": len(r.content),
                     "sha256": hashlib.sha256(r.content).hexdigest(),
                     "elapsed_s": round(time.time()-t0, 3)})
        return r
    except Exception as e:
        reqs.append({"url": url, "name": name, "error": repr(e), "retrieved_at_utc": now()})
        return None

fails = {"n": 0}
def rpc(method, params, name, retries=1):
    for attempt in range(retries + 1):
        t0 = time.time()
        try:
            r = s.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=30)
            j = r.json()
            reqs.append({"url": RPC, "name": name, "method": method, "http_status": r.status_code,
                         "retrieved_at_utc": now(), "bytes": len(r.content),
                         "sha256": hashlib.sha256(r.content).hexdigest(),
                         "elapsed_s": round(time.time()-t0, 3)})
            if isinstance(j, dict) and j.get("error", {}).get("code") == 429 and attempt < retries:
                time.sleep(3.0); continue
            if "result" in j:
                fails["n"] = 0
            else:
                fails["n"] += 1
            return j
        except Exception as e:
            reqs.append({"url": RPC, "name": name, "method": method, "error": repr(e), "retrieved_at_utc": now()})
            fails["n"] += 1
            if fails["n"] >= 3:
                return {"error": "consecutive_failure_limit", "detail": repr(e)}
            time.sleep(2.0)
    return {"error": "no result"}

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
def b58(b):
    n = int.from_bytes(b, "big"); out = ""
    while n:
        n, r = divmod(n, 58); out = B58[r] + out
    pad = sum(1 for x in b if x == 0) if b else 0
    return "1" * pad + out

out = {"started_at_utc": now()}
sleep = lambda t=0.7: time.sleep(t)

# --- official Raydium mainnet constants (top exported consts only) ---
txt = open(BASE + r"\raydium_programId.ts.txt", encoding="utf-8").read()
mainnet = dict(re.findall(r'export const ([A-Za-z0-9_]+) = new PublicKey\("([1-9A-HJ-NP-Za-km-z]{32,44})"\)', txt))
save("raydium_programId.mainnet.json", {"url": "https://raw.githubusercontent.com/raydium-io/raydium-sdk-V2/master/src/common/programId.ts",
     "retrieved_at_utc": "2026-11-09T14:27:01+00:00", "mainnet_exported_consts": mainnet})
out["raydium_mainnet_consts"] = {k: mainnet.get(k) for k in ["AMM_V4", "AMM_STABLE", "CLMM_PROGRAM_ID", "CREATE_CPMM_POOL_PROGRAM", "CLMM_LOCK_PROGRAM_ID", "Router"]}
orca_readme = json.load(open(BASE + r"\orca_readme.extract.json", encoding="utf-8"))
out["orca_readme_ids"] = orca_readme.get("candidate_ids")

WHIRL = "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc"
TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
progs = [
    {"protocol": "Raydium", "key": "CLMM_PROGRAM_ID", "program_id": mainnet.get("CLMM_PROGRAM_ID"), "official_source": "raydium-sdk-V2 programId.ts (fetched 2026-11-09T14:27:01Z)"},
    {"protocol": "Raydium", "key": "CREATE_CPMM_POOL_PROGRAM", "program_id": mainnet.get("CREATE_CPMM_POOL_PROGRAM"), "official_source": "raydium-sdk-V2 programId.ts"},
    {"protocol": "Raydium", "key": "AMM_V4", "program_id": mainnet.get("AMM_V4"), "official_source": "raydium-sdk-V2 programId.ts"},
    {"protocol": "Orca Whirlpools", "key": "WHIRLPOOL_PROGRAM", "program_id": WHIRL, "official_source": "orca-so/whirlpools README (fetched 2026-11-09T14:27Z)"},
    {"protocol": "SPL Token-2022", "key": "TOKEN_2022_PROGRAM", "program_id": TOKEN_2022, "official_source": "NOT_FETCHED_THIS_ROUND; widely documented ID"},
    {"protocol": "SPL Token (classic)", "key": "TOKEN_PROGRAM", "program_id": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "official_source": "NOT_FETCHED_THIS_ROUND; widely documented ID"},
]

# --- Stage 1: program accounts ---
ids = [p["program_id"] for p in progs]
res = rpc("getMultipleAccounts", [ids, {"encoding": "base64", "commitment": "finalized"}], "rpc_programs_multi")
save("rpc_programs_multi.json", res)
ctx_slot = (res.get("result") or {}).get("context", {}).get("slot") if "result" in res else None
vals = (res.get("result") or {}).get("value") if "result" in res else []
programdata = {}
for p, v in zip(progs, vals or []):
    if not v:
        p["identity_status"] = "NOT_FOUND"; continue
    p.update({"owner": v.get("owner"), "executable": v.get("executable"), "lamports": v.get("lamports"),
              "space": v.get("space"), "rpc_slot": ctx_slot})
    p["identity_status"] = "ONCHAIN_EXECUTABLE" if v.get("executable") else "NOT_EXECUTABLE"
    raw = base64.b64decode(v["data"][0])
    if len(raw) >= 36 and int.from_bytes(raw[0:4], "little") == 2:
        p["programdata_address"] = b58(raw[4:36]); programdata[p["program_id"]] = p["programdata_address"]
    else:
        p["loader_state"] = "NOT_UPGRADEABLE_LOADER_STATE" if len(raw) >= 4 else "EMPTY"
out["programs"] = progs
out["slot_from_program_reads"] = ctx_slot
sleep()

# --- Stage 2: programdata accounts -> last deploy slot ---
if programdata:
    pd_items = list(programdata.items())
    res = rpc("getMultipleAccounts", [[a for _, a in pd_items], {"encoding": "base64", "commitment": "finalized"}], "rpc_programdata_multi")
    save("rpc_programdata_multi.json", res)
    pd_vals = (res.get("result") or {}).get("value") if "result" in res else []
    out["programdata_rpc_slot"] = (res.get("result") or {}).get("context", {}).get("slot") if "result" in res else None
    upgrades = []
    for (pid, addr), v in zip(pd_items, pd_vals or []):
        entry = {"program_id": pid, "programdata_address": addr}
        if v and v.get("data"):
            raw = base64.b64decode(v["data"][0])
            if len(raw) >= 13 and int.from_bytes(raw[0:4], "little") == 3:
                entry["last_deploy_slot"] = int.from_bytes(raw[4:12], "little")
                entry["has_upgrade_authority"] = raw[12] == 1
                entry["upgrade_authority"] = b58(raw[13:45]) if raw[12] == 1 and len(raw) >= 45 else None
                entry["data_len"] = len(raw)
            else:
                entry["decode_error"] = "unexpected layout"
        else:
            entry["error"] = "no data"
        upgrades.append(entry)
    out["program_upgrades"] = upgrades
    sleep()

    # --- Stage 3: block times for upgrades (individual calls, spaced) ---
    for u in out["program_upgrades"]:
        sl = u.get("last_deploy_slot")
        if not sl: continue
        r = rpc("getBlockTime", [sl], f"getBlockTime_{sl}")
        bt = r.get("result")
        u["last_deploy_time_utc"] = (datetime.datetime.fromtimestamp(bt, datetime.timezone.utc).isoformat()
                                     if isinstance(bt, int) else None)
        sleep()
    cur = out.get("slot_from_program_reads")
    if cur:
        r = rpc("getBlockTime", [max(0, cur - 2)], "getBlockTime_current")
        bt = r.get("result")
        out["current_blocktime_utc"] = (datetime.datetime.fromtimestamp(bt, datetime.timezone.utc).isoformat()
                                        if isinstance(bt, int) else None)
        out["current_slot"] = cur
        out["current_slot_note"] = f"getBlockTime({cur-2})"
        for u in out["program_upgrades"]:
            if u.get("last_deploy_slot"):
                u["age_slots"] = cur - u["last_deploy_slot"]
                u["within_7d_slots"] = u["age_slots"] <= 1512000
                u["within_30d_slots"] = u["age_slots"] <= 6480000
        sleep()

# --- Stage 4: verify Orca top pools on-chain (already saved list) ---
orca = json.load(open(BASE + r"\orca_pools.json", encoding="utf-8"))
pools2 = orca["pools"][:2]
mints = sorted({p["tokenMintA"] for p in pools2} | {p["tokenMintB"] for p in pools2})
res = rpc("getMultipleAccounts", [[p["address"] for p in pools2] + mints,
                                  {"encoding": "base64", "commitment": "finalized"}], "rpc_pools_mints_multi")
save("rpc_pools_mints_multi.json", res)
vals = (res.get("result") or {}).get("value") if "result" in res else []
out["pool_mint_rpc_slot"] = (res.get("result") or {}).get("context", {}).get("slot") if "result" in res else None
pool_checks = []; mint_checks = {}
for i, (addr_or_mint, v) in enumerate(zip([p["address"] for p in pools2] + mints, vals or [])):
    rec = {"address": addr_or_mint, "owner": v.get("owner") if v else None,
           "executable": v.get("executable") if v else None,
           "space": v.get("space") if v else None}
    if i < len(pools2):
        rec["is_orca_whirlpool_program_owned"] = bool(v and v.get("owner") == WHIRL)
        rec["data_bytes"] = len(base64.b64decode(v["data"][0])) if v and v.get("data") else None
        pool_checks.append(rec)
    else:
        mint_checks[addr_or_mint] = rec
out["pool_checks"] = pool_checks
out["mint_checks"] = mint_checks
out["orca_pools_verified"] = [{**p, "onchain": next((c for c in pool_checks if c["address"] == p["address"]), None),
                               "mintA_owner": (mint_checks.get(p["tokenMintA"]) or {}).get("owner"),
                               "mintB_owner": (mint_checks.get(p["tokenMintB"]) or {}).get("owner")}
                              for p in pools2]
sleep()

# --- Stage 5: recent signatures on verified Orca pool (7-day activity evidence) ---
if pools2:
    r = rpc("getSignaturesForAddress", [pools2[0]["address"], {"limit": 10, "commitment": "finalized"}], "rpc_signatures")
    save("rpc_signatures.json", r)
    sigs = r.get("result") or []
    out["recent_signatures"] = [{"signature": x.get("signature"), "slot": x.get("slot"),
                                 "blockTime_utc": (datetime.datetime.fromtimestamp(x["blockTime"], datetime.timezone.utc).isoformat()
                                                   if x.get("blockTime") else None),
                                 "err": bool(x.get("err"))} for x in sigs]
    out["signature_read_at_utc"] = now()
    sleep()

# --- Stage 6: Raydium official pool list (discovery entry) + verify one CLMM pool on-chain ---
r = http_get("https://api-v3.raydium.io/pools/info/list?poolType=all&poolSortField=default&sortType=desc&pageSize=10&page=1", "raydium_pool_list")
ray_pools = []
if r is not None and r.status_code == 200:
    try:
        j = r.json()
        arr = ((j.get("data") or {}).get("data")) or []
        for p in arr[:10]:
            ray_pools.append({
                "id": p.get("id"), "type": p.get("type"), "programId": p.get("programId"),
                "mintA": (p.get("mintA") or {}).get("address"), "mintB": (p.get("mintB") or {}).get("address"),
                "tvl": p.get("tvl"), "day_volume": (p.get("day") or {}).get("volume"),
                "feeRate": p.get("feeRate"), "createdAt": p.get("createdAt") or p.get("openTime")})
        save("raydium_pools.json", {"url": r.url, "http_status": r.status_code, "retrieved_at_utc": now(), "pools": ray_pools})
    except Exception as e:
        out["raydium_parse_error"] = repr(e)
    out["raydium_pools"] = ray_pools
    sleep()
    if ray_pools:
        pick = ray_pools[0]
        addrs = [pick["id"], pick["mintA"], pick["mintB"]]
        res = rpc("getMultipleAccounts", [addrs, {"encoding": "base64", "commitment": "finalized"}], "rpc_raydium_pool_multi")
        save("rpc_raydium_pool_multi.json", res)
        vals = (res.get("result") or {}).get("value") if "result" in res else []
        checks = []
        for a, v in zip(addrs, vals or []):
            checks.append({"address": a, "owner": v.get("owner") if v else None,
                           "executable": v.get("executable") if v else None,
                           "space": v.get("space") if v else None})
        out["raydium_pool_checks"] = checks
        out["raydium_pool_rpc_slot"] = (res.get("result") or {}).get("context", {}).get("slot") if "result" in res else None
        if checks:
            out["raydium_pool_owner_matches_program"] = (checks[0]["owner"] == pick.get("programId"))
        sleep()

out["finished_at_utc"] = now()
out["requests"] = reqs
out["request_count"] = len(reqs)
save("summary.json", out)
print(json.dumps({k: out.get(k) for k in ["started_at_utc", "finished_at_utc", "current_slot", "current_blocktime_utc",
    "raydium_mainnet_consts", "programs", "program_upgrades", "orca_pools_verified", "mint_checks",
    "recent_signatures", "raydium_pools", "raydium_pool_checks", "raydium_pool_owner_matches_program",
    "request_count"]}, ensure_ascii=False, indent=1)[:14000])
