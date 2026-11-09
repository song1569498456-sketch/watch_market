"""补充验证（尝试2）：从 stETH 代理的 Aragon AppStorage KERNEL_POSITION 读 kernel，再 Kernel.getApp。"""
import json
import requests
from Crypto.Hash import keccak

RUN_ID = "live-20261109T141903Z"
OUT = rf"D:\ds-arb-test\watch_market\evidence\M00\{RUN_ID}"
RPC = "https://ethereum-rpc.publicnode.com"
STETH = "0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84"
PROXY = "http://127.0.0.1:7897"

s = requests.Session()
s.trust_env = False
s.proxies = {"http": PROXY, "https": PROXY}


def rpc(m, p):
    r = s.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": m, "params": p}, timeout=40)
    j = r.json()
    if "error" in j:
        raise RuntimeError(f"{m} -> {j['error']}")
    return j["result"]


def keccak_hex(data):
    k = keccak.new(digest_bits=256)
    k.update(data if isinstance(data, bytes) else data.encode())
    return "0x" + k.hexdigest()


def sel(sig):
    return keccak_hex(sig.encode())[:10]


gate = json.load(open(OUT + r"\single-market-gate.json", encoding="utf-8"))
lido = json.load(open(OUT + r"\lido-deployed-mainnet.json", encoding="utf-8"))
pinned = hex(gate["block_number"])
app_id = lido["app:lido"]["aragonApp"]["id"]
official_impl = lido["app:lido"]["implementation"]["address"]

candidates = {
    "aragonOS.appStorage.kernel": keccak_hex("aragonOS.appStorage.kernel"),
    "aragonOS.appStorage.appBase": keccak_hex("aragonOS.appStorage.appBase"),
    "aragonOS.appStorage.proxyAppAddress": keccak_hex("aragonOS.appStorage.proxyAppAddress"),
}
probe = {}
for name, slot in candidates.items():
    val = rpc("eth_getStorageAt", [STETH, slot, pinned])
    probe[name] = {"slot": slot, "value": val}

result = {"pinned_block": gate["block_number"], "storage_probe": probe}
kernel_addr = None
for name, p in probe.items():
    addr = "0x" + p["value"][-40:]
    if int(p["value"], 16) != 0 and rpc("eth_getCode", [addr, pinned]) != "0x":
        kcode = rpc("eth_getCode", [addr, pinned])
        result.setdefault("candidate_kernels", []).append({"source": name, "address": addr, "code_bytes": (len(kcode) - 2) // 2})
        kernel_addr = addr

if kernel_addr:
    try:
        res = rpc("eth_call", [{"to": kernel_addr, "data": sel("getApp(bytes32)") + app_id[2:]}, pinned])
        onchain = "0x" + res[-40:]
        result.update({
            "kernel_used": kernel_addr,
            "onchain_getApp_result": onchain,
            "official_deployment_json_implementation": official_impl,
            "match": onchain.lower() == official_impl.lower(),
        })
    except Exception as e:  # noqa: BLE001
        result["getApp_error"] = str(e)
else:
    result["kernel_not_found"] = True

with open(OUT + r"\proxy-verification.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print(json.dumps(result, ensure_ascii=False, indent=1)[:3000])
