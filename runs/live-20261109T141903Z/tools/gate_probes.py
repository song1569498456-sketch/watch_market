"""M00 phase1+2: 共享数据能力复核 + Ethereum Curve stETH/ETH 单市场数据门。

只读 JSON-RPC / HTTP GET；不签名、不广播。产物：
  evidence/M00/live-20261109T141903Z/capability-probes.json
  evidence/M00/live-20261109T141903Z/single-market-gate.json
  evidence/M00/live-20261109T141903Z/raw-selected.json
"""
import json
import time
import datetime
import hashlib
import os

import requests
from Crypto.Hash import keccak

RUN_ID = "live-20261109T141903Z"
REPO = r"D:\ds-arb-test\watch_market"
OUT = os.path.join(REPO, "evidence", "M00", RUN_ID)
os.makedirs(OUT, exist_ok=True)
PROXY = "http://127.0.0.1:7897"
ETH_RPC = "https://ethereum-rpc.publicnode.com"
POOL = "0xDC24316b9AE028F1497c275EB9192a3Ea0f67022"
STETH = "0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84"
TEST_FROM = "0x00000000000000000000000000000000000AbCdE"
DX = 10**16  # 0.01 stETH
FEE_DENOMINATOR = 10**10  # 来自 Curve 官方源码常量（上轮 Q00 已独立复核），只作换算分母

sess = requests.Session()
sess.trust_env = False
sess.proxies = {"http": PROXY, "https": PROXY}

_id = 0
raw_log = []


def rpc(url, method, params, label):
    global _id
    _id += 1
    t0 = time.time()
    r = sess.post(url, json={"jsonrpc": "2.0", "id": _id, "method": method, "params": params}, timeout=40)
    elapsed = round(time.time() - t0, 3)
    body = r.json()
    entry = {"label": label, "url": url, "method": method, "elapsed_s": elapsed,
             "response": body}
    raw_log.append(entry)
    if "error" in body:
        raise RuntimeError(f"{label} -> {body['error']}")
    return body["result"]


def keccak256_hex(data: bytes) -> str:
    k = keccak.new(digest_bits=256)
    k.update(data)
    return "0x" + k.hexdigest()


def selector(sig: str) -> str:
    return keccak256_hex(sig.encode())[:10]


def w_uint(v: int) -> str:
    return f"{v:064x}"


def pad_addr(a: str) -> str:
    return "0" * 24 + a.lower().removeprefix("0x")


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def iso(dt):
    return dt.isoformat()


def bj(ts_unix):
    return datetime.datetime.fromtimestamp(ts_unix, datetime.timezone(datetime.timedelta(hours=8))).isoformat()


# ---------- phase 1: nine-chain capability ----------
CHAINS = [
    ("Ethereum", "ETH", 1, "https://ethereum-rpc.publicnode.com"),
    ("Arbitrum One", "ARB", 42161, "https://arb1.arbitrum.io/rpc"),
    ("Optimism", "OP", 10, "https://mainnet.optimism.io"),
    ("Base", "BASE", 8453, "https://mainnet.base.org"),
    ("Polygon PoS", "POLY", 137, "https://polygon-bor-rpc.publicnode.com"),
    ("BNB Chain", "BNB", 56, "https://bsc-dataseed.bnbchain.org"),
    ("Avalanche C-Chain", "AVAX", 43114, "https://api.avax.network/ext/bc/C/rpc"),
    ("Sonic", "SONIC", 146, "https://rpc.soniclabs.com"),
]
capability = {"probed_at_utc": iso(now_utc()), "evm": [], "solana": None, "http_sources": []}
for name, code, expect, url in CHAINS:
    row = {"chain": code, "name": name, "rpc": url}
    try:
        cid = rpc(url, "eth_chainId", [], f"{code}.chainId")
        row["chain_id_hex"] = cid
        row["chain_id"] = int(cid, 16)
        row["chain_id_ok"] = int(cid, 16) == expect
        bn = rpc(url, "eth_blockNumber", [], f"{code}.blockNumber")
        row["block_number"] = int(bn, 16)
        row["ok"] = row["chain_id_ok"]
    except Exception as e:  # noqa: BLE001
        row["ok"] = False
        row["error"] = str(e)
    capability["evm"].append(row)
    time.sleep(0.4)

# Solana
SOL = "https://api.mainnet-beta.solana.com"
sol = {"chain": "SOL", "name": "Solana mainnet-beta", "rpc": SOL}
try:
    gen = rpc(SOL, "getGenesisHash", [], "SOL.genesis")
    sol["genesis_hash"] = gen
    sol["genesis_ok"] = gen == "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"
    slot = rpc(SOL, "getSlot", [], "SOL.slot")
    sol["slot"] = slot
    sol["ok"] = sol["genesis_ok"]
except Exception as e:  # noqa: BLE001
    sol["ok"] = False
    sol["error"] = str(e)
capability["solana"] = sol

# representative data sources (GET only)
for name, url in [
    ("dexscreener", "https://api.dexscreener.com/latest/dex/search?q=stETH"),
    ("curve-api", "https://api.curve.finance/api/getPools/ethereum/main"),
    ("lido-deploy", "https://raw.githubusercontent.com/lidofinance/core/master/deployed-mainnet.json"),
]:
    t0 = time.time()
    try:
        r = sess.get(url, timeout=40)
        row = {"source": name, "url": url, "http_status": r.status_code,
               "bytes": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(),
               "elapsed_s": round(time.time() - t0, 3), "ok": r.status_code == 200}
    except Exception as e:  # noqa: BLE001
        row = {"source": name, "url": url, "ok": False, "error": str(e)}
    capability["http_sources"].append(row)
    time.sleep(0.5)

with open(os.path.join(OUT, "capability-probes.json"), "w", encoding="utf-8") as f:
    json.dump(capability, f, ensure_ascii=False, indent=2)
print("[phase1]", json.dumps({"evm_ok": sum(1 for r in capability["evm"] if r.get("ok")),
                              "evm_total": len(capability["evm"]),
                              "sol_ok": sol.get("ok"),
                              "http_ok": sum(1 for r in capability["http_sources"] if r.get("ok"))}, ensure_ascii=False))

# ---------- phase 2: single market gate ----------
gate = {
    "verification_id": "ETH-CURVE-STETH-ETH-DATA-GATE",
    "run_id": RUN_ID,
    "status": "IN_PROGRESS",
    "research_grade": "UNVERIFIED",
    "chain": "Ethereum",
    "expected_chain_id": 1,
    "market_id": "1:Curve:steth:0xdc24316b9ae028f1497c275eb9192a3ea0f67022",
    "swap_contract": POOL,
    "measurement_amount": {"human": "0.01", "raw": str(DX), "unit": "stETH"},
    "probe_from_account": TEST_FROM,
    "state_override_note": "只读模拟：用 stateDiff 给测试地址临时注入 shares 与 allowance；不签名、不广播，不代表真实账户余额",
    "started_at_utc": iso(now_utc()),
}

cid = rpc(ETH_RPC, "eth_chainId", [], "gate.chainId")
gate["observed_chain_id"] = int(cid, 16)
latest = int(rpc(ETH_RPC, "eth_blockNumber", [], "gate.blockNumber"), 16)
pinned = latest - 2
pinned_hex = hex(pinned)
blk = rpc(ETH_RPC, "eth_getBlockByNumber", [pinned_hex, False], "gate.block")
blk_ts = int(blk["timestamp"], 16)
gate.update({
    "block_number": pinned,
    "block_hash": blk["hash"],
    "block_timestamp_utc": datetime.datetime.fromtimestamp(blk_ts, datetime.timezone.utc).isoformat(),
    "block_timestamp_beijing": bj(blk_ts),
    "base_fee_per_gas_wei": int(blk["baseFeePerGas"], 16) if blk.get("baseFeePerGas") else None,
    "latest_block_at_probe": latest,
})

# pool code + EIP1967
pool_code = rpc(ETH_RPC, "eth_getCode", [POOL, pinned_hex], "gate.pool.code")
pool_bytes = bytes.fromhex(pool_code[2:])
eip1967 = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
pool_impl_slot = rpc(ETH_RPC, "eth_getStorageAt", [POOL, eip1967, pinned_hex], "gate.pool.eip1967")
gate["code_identity"] = {
    "pool_bytecode_bytes": len(pool_bytes),
    "pool_code_keccak256": keccak256_hex(pool_bytes),
    "pool_eip1967_implementation_slot": pool_impl_slot,
}

# stETH token identity
steth_code = rpc(ETH_RPC, "eth_getCode", [STETH, pinned_hex], "gate.steth.code")
steth_bytes = bytes.fromhex(steth_code[2:])
gate["code_identity"]["steth_bytecode_bytes"] = len(steth_bytes)
gate["code_identity"]["steth_code_keccak256"] = keccak256_hex(steth_bytes)
gate["code_identity"]["steth_eip1967_slot"] = rpc(
    ETH_RPC, "eth_getStorageAt", [STETH, eip1967, pinned_hex], "gate.steth.eip1967")


def call(to, data, label, from_=None, override=None, gas=None, block=pinned_hex):
    tx = {"to": to, "data": data}
    if from_:
        tx["from"] = from_
    if gas:
        tx["gas"] = hex(gas)
    params = [tx, block]
    if override is not None:
        params.append(override)
    return rpc(ETH_RPC, "eth_call", params, label)


def try_call(to, data, label, from_=None, override=None):
    try:
        return {"ok": True, "result": call(to, data, label, from_=from_, override=override)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


# symbol/decimals for stETH
sel_symbol = selector("symbol()")
sel_decimals = selector("decimals()")
sym = try_call(STETH, sel_symbol, "gate.steth.symbol")
dec = try_call(STETH, sel_decimals, "gate.steth.decimals")
gate["asset_in"] = {
    "address": STETH,
    "symbol_onchain": sym.get("result") if sym["ok"] else None,
    "decimals_onchain": int(dec["result"], 16) if dec["ok"] else None,
}
# coins(0/1)
coins = {}
for idx in (0, 1):
    res = call(POOL, selector("coins(uint256)") + w_uint(idx), f"gate.coins.{idx}")
    coins[idx] = "0x" + res[-40:]
gate["code_identity"]["coins_onchain"] = {"0": coins[0], "1": coins[1]}
gate["asset_out"] = {"kind": "native ETH", "registry_sentinel": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"}
gate["coin_identity_check"] = {"coins_1_is_stETH": coins[1].lower() == STETH.lower()}

# fee / fee denominator
fee_raw = int(call(POOL, selector("fee()"), "gate.fee"), 16)
gate["fees"] = {"pool_fee_raw": fee_raw, "fee_denominator": FEE_DENOMINATOR,
                "pool_fee_ratio": fee_raw / FEE_DENOMINATOR,
                "fee_denominator_basis": "Curve 源码常量 FEE_DENOMINATOR=10**10（上轮 Q00 独立复核，本轮只作换算分母）"}

# get_dy quote at pinned block
getdy_sel = selector("get_dy(int128,int128,uint256)")
quote_data = getdy_sel + w_uint(1) + w_uint(0) + w_uint(DX)
quote_time = now_utc()
dy_raw = int(call(POOL, quote_data, "gate.get_dy"), 16)
gate["path"] = {
    "type": "single market stETH to ETH exit",
    "view_call": "get_dy(int128,int128,uint256)",
    "selector": getdy_sel,
    "args": [1, 0, str(DX)],
    "amount_out_raw": str(dy_raw),
    "amount_out_human": f"{dy_raw / 1e18:.9f}",
    "implied_ratio": round(dy_raw / DX, 9),
    "quote_time_utc": iso(quote_time),
    "pinned_block": pinned,
}

# ---- storage layout discovery for state override ----
# StETH(implementation Lido.sol) 的 shares 与 allowances 是常规 storage 变量；
# 源码顺序 constants 不占槽：shares=slot 0，allowances=slot 1（待实测校验）。
pool_shares_slot = keccak256_hex(bytes.fromhex(pad_addr(POOL) + w_uint(0)))
pool_shares_hex = rpc(ETH_RPC, "eth_getStorageAt", [STETH, pool_shares_slot, pinned_hex], "gate.layout.pool_shares")
pool_shares = int(pool_shares_hex, 16)
bal_of_pool = int(call(STETH, selector("balanceOf(address)") + pad_addr(POOL), "gate.layout.balanceOf_pool"), 16)
pooled_from_shares = int(call(STETH, selector("getPooledEthByShares(uint256)") + w_uint(pool_shares),
                             "gate.layout.getPooledEthByShares_pool"), 16)
gate["storage_layout_check"] = {
    "shares_slot_of_pool": pool_shares_slot,
    "pool_shares_raw": str(pool_shares),
    "getPooledEthByShares_of_pool_shares": str(pooled_from_shares),
    "balanceOf_pool": str(bal_of_pool),
    "layout_confirmed": pooled_from_shares == bal_of_pool,
}

# ---- stateDiff override simulation ----
shares_slot_test = keccak256_hex(bytes.fromhex(pad_addr(TEST_FROM) + w_uint(0)))
allow_inner = keccak256_hex(bytes.fromhex(pad_addr(TEST_FROM) + w_uint(1)))
allow_slot_test = keccak256_hex(bytes.fromhex(pad_addr(POOL) + allow_inner[2:]))
override = {STETH: {"stateDiff": {
    shares_slot_test: "0x" + w_uint(10**18),          # 1 share（份额汇率 >1，故余额 >0.01 stETH）
    allow_slot_test: "0x" + w_uint(DX),               # allowance = 0.01 stETH
}}}
bal_test = try_call(STETH, selector("balanceOf(address)") + pad_addr(TEST_FROM),
                    "gate.sim.balanceOf_test", override=override)
shares_test = try_call(STETH, selector("sharesOf(address)") + pad_addr(TEST_FROM),
                       "gate.sim.sharesOf_test", override=override)
allow_test = try_call(STETH, selector("allowance(address,address)") + pad_addr(TEST_FROM) + pad_addr(POOL),
                      "gate.sim.allowance_test", override=override)
gate["simulation"] = {
    "method": "eth_call + geth stateDiff override on stETH shares(slot0)/allowances(slot1)",
    "override": override,
    "balance_of_test_ok": bal_test["ok"],
    "balance_of_test": int(bal_test["result"], 16) if bal_test["ok"] else None,
    "shares_of_test": int(shares_test["result"], 16) if shares_test["ok"] else None,
    "allowance_test": int(allow_test["result"], 16) if allow_test["ok"] else None,
}
exchange_sel = selector("exchange(int128,int128,uint256,uint256)")
ex_data = exchange_sel + w_uint(1) + w_uint(0) + w_uint(DX) + w_uint(0)
sim = try_call(POOL, ex_data, "gate.sim.exchange", from_=TEST_FROM, override=override)
gate["simulation"]["exchange_call_ok"] = sim["ok"]
gate["simulation"]["exchange_call_result"] = sim.get("result")
gate["simulation"]["exchange_call_error"] = sim.get("error")

gas_exchange = None
gas_approve = None
try:
    g = rpc(ETH_RPC, "eth_estimateGas", [{"from": TEST_FROM, "to": POOL, "data": ex_data}, pinned_hex, override],
            "gate.gas.exchange")
    gas_exchange = int(g, 16)
except Exception as e:  # noqa: BLE001
    gate["gas_error_exchange"] = str(e)
approve_data = selector("approve(address,uint256)") + pad_addr(POOL) + w_uint(DX)
try:
    g = rpc(ETH_RPC, "eth_estimateGas", [{"from": TEST_FROM, "to": STETH, "data": approve_data}, pinned_hex, override],
            "gate.gas.approve")
    gas_approve = int(g, 16)
except Exception as e:  # noqa: BLE001
    gate["gas_error_approve"] = str(e)

gas_price = int(rpc(ETH_RPC, "eth_gasPrice", [], "gate.gasPrice"), 16)
priority = None
try:
    priority = int(rpc(ETH_RPC, "eth_maxPriorityFeePerGas", [], "gate.maxPriorityFeePerGas"), 16)
except Exception as e:  # noqa: BLE001
    gate["priority_fee_error"] = str(e)

gas_cost = None
if gas_exchange is not None and priority is not None:
    gas_cost_wei = (gas_exchange + (gas_approve or 0)) * (gate["base_fee_per_gas_wei"] + priority)
    gas_cost = gas_cost_wei / 1e18
gate["fees"]["approval_gas_units"] = gas_approve
gate["fees"]["exchange_gas_units"] = gas_exchange
gate["fees"]["gas_price_wei"] = gas_price
gate["fees"]["priority_fee_wei"] = priority
gate["fees"]["gas_cost_ETH_estimate"] = gas_cost
gate["fees"]["gas_cost_basis"] = "gasPrice 非 EIP-1559 精确；用 pinned baseFee + maxPriority，approve+exchange 两笔合计"

# ---- Lido deployment cross-check (official JSON from this run's fetch) ----
lido_path = os.path.join(OUT, "lido-deployed-mainnet.json")
lido = json.load(open(lido_path, encoding="utf-8")) if os.path.exists(lido_path) else None
if lido:
    app = lido.get("app:lido", {})
    gate["lido_official_crosscheck"] = {
        "steth_proxy_address": app.get("proxy", {}).get("address"),
        "steth_implementation": app.get("implementation", {}).get("address"),
        "withdrawal_queue_proxy": lido.get("withdrawalQueueERC721", {}).get("proxy", {}).get("address"),
        "matches_steth_address": (app.get("proxy", {}).get("address") or "").lower() == STETH.lower(),
    }

gate["network_capability_ref"] = "evidence/M00/%s/capability-probes.json" % RUN_ID
gate["finished_at_utc"] = iso(now_utc())
gate["new_valid_market_finding"] = False
gate["profit_claim"] = False

# gate status logic
checks = {
    "chain_id_ok": gate["observed_chain_id"] == 1,
    "fixed_block": isinstance(gate["block_hash"], str) and len(gate["block_hash"]) == 66,
    "pool_code_present": gate["code_identity"]["pool_bytecode_bytes"] > 0,
    "steth_code_present": gate["code_identity"]["steth_bytecode_bytes"] > 0,
    "coins_match": gate["coin_identity_check"]["coins_1_is_stETH"],
    "layout_confirmed": gate["storage_layout_check"]["layout_confirmed"],
    "quote_obtained": int(gate["path"]["amount_out_raw"]) > 0,
    "simulation_ok": bool(gate["simulation"].get("exchange_call_ok")),
    "gas_estimated": gas_exchange is not None,
}
gate["gate_checks"] = checks
gate["status"] = "PASS" if all(checks.values()) else ("PARTIAL" if sum(checks.values()) >= 6 else "BLOCKED")
gate["research_grade"] = "SIMULATED" if gate["status"] == "PASS" else "UNVERIFIED"

with open(os.path.join(OUT, "single-market-gate.json"), "w", encoding="utf-8") as f:
    json.dump(gate, f, ensure_ascii=False, indent=2)
with open(os.path.join(OUT, "raw-selected.json"), "w", encoding="utf-8") as f:
    json.dump(raw_log, f, ensure_ascii=False, indent=2)

print("[phase2]", json.dumps({
    "status": gate["status"], "checks": checks,
    "block": gate["block_number"], "block_hash": gate["block_hash"],
    "dy_raw": gate["path"]["amount_out_raw"], "dy_human": gate["path"]["amount_out_human"],
    "fee_raw": fee_raw, "layout_confirmed": gate["storage_layout_check"]["layout_confirmed"],
    "sim_exchange": gate["simulation"].get("exchange_call_ok"),
    "gas_exchange": gas_exchange, "gas_cost_ETH": gas_cost,
}, ensure_ascii=False))
