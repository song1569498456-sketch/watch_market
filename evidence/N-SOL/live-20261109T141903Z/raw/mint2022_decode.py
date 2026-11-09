import json, time, datetime, base64, hashlib
import requests
BASE = r"D:\ds-arb-test\watch_market\evidence\N-SOL\live-20261109T141903Z\raw"
PROXY = "http://127.0.0.1:7897"
RPC = "https://api.mainnet-beta.solana.com"
s = requests.Session(); s.trust_env = False
s.proxies = {"http": PROXY, "https": PROXY}
s.headers.update({"User-Agent": "watch_market-readonly-research/1.0"})
now = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
MINT = "NVDAVuiB7hwd3m5Wa1JuHNovPaPG6BH1QNztbKFxNjv"
out = {"mint": MINT}
r = s.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": "getAccountInfo",
                      "params": [MINT, {"encoding": "base64", "commitment": "finalized"}]}, timeout=30)
j = r.json()
out["rpc"] = {"http_status": r.status_code, "at": now(), "sha256": hashlib.sha256(r.content).hexdigest()}
v = j["result"]["value"]
raw = base64.b64decode(v["data"][0])
out["owner"] = v["owner"]; out["space"] = v["space"]; out["data_len"] = len(raw)
out["base64_len"] = len(v["data"][0])
# base mint fields (82 bytes)
import struct
supply = struct.unpack("<Q", raw[36:44])[0]
decimals = raw[44]
is_init = raw[45]
mint_auth_flag = struct.unpack("<I", raw[0:4])[0]
freeze_flag = struct.unpack("<I", raw[82-36:82-32])[0]
out["base"] = {"mint_authority_present": mint_auth_flag == 1, "supply": str(supply),
               "decimals": decimals, "is_initialized": is_init,
               "freeze_authority_present": freeze_flag == 1}
# token-2022: 82 base + 83 padding + 1 account type at 165, TLV at 166
out["account_type_byte_at_165"] = raw[165] if len(raw) > 165 else None
EXT = {0:"Uninitialized",1:"TransferFeeConfig",2:"TransferFeeAmount",3:"MintCloseAuthority",
       4:"ConfidentialTransferMint",5:"ConfidentialTransferAccount",6:"DefaultAccountState",
       7:"ImmutableOwner",8:"MemoTransfer",9:"NonTransferable",10:"InterestBearingConfig",
       11:"CpiGuard",12:"PermanentDelegate",13:"NonTransferableAccount",14:"TransferHook",
       15:"TransferHookAccount",16:"ConfidentialTransferFeeConfig",17:"ConfidentialTransferFeeAmount",
       18:"MetadataPointer",19:"TokenMetadata",20:"GroupPointer",21:"TokenGroup",
       22:"GroupMemberPointer",23:"TokenGroupMember"}
exts = []
if len(raw) > 166:
    off = 166
    while off + 4 <= len(raw):
        t, ln = struct.unpack("<HH", raw[off:off+4])
        if t == 0 and ln == 0: break
        data = raw[off+4:off+4+ln]
        exts.append({"type": t, "name": EXT.get(t, "Unknown"), "len": ln,
                     "head_hex": data[:40].hex()})
        off += 4 + ln
out["extensions"] = exts
out["extensions_offset_used"] = 166
out["finished_at_utc"] = now()
json.dump(out, open(BASE + r"\mint2022_decode.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1)[:4000])
