import json, time, requests

PROXY = {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}
S = requests.Session(); S.trust_env = False; S.proxies = PROXY
S.headers.update({"Content-Type": "application/json"})
POOL = '0xDC24316b9AE028F1497c275EB9192a3Ea0f67022'
cands = [
    ('eth.drpc', 'https://eth.drpc.org'),
    ('blastapi', 'https://eth-mainnet.public.blastapi.io'),
    ('1rpc', 'https://1rpc.io/eth'),
    ('merkle', 'https://eth.merkle.io'),
    ('publicnode-latest', 'https://ethereum-rpc.publicnode.com'),
]
log = []
for name, url in cands:
    blk = 'latest' if name == 'publicnode-latest' else hex(26377898)
    try:
        r = S.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "eth_getCode", "params": [POOL, blk]}, timeout=20)
        j = r.json()
        res = j.get('result')
        ok = isinstance(res, str) and len(res) > 2
        log.append({'name': name, 'url': url, 'block': blk, 'ok': ok, 'bytes': (len(res) - 2) // 2 if ok else None, 'err': None if ok else j.get('error')})
    except Exception as e:
        log.append({'name': name, 'url': url, 'block': blk, 'ok': False, 'err': str(e)})
    time.sleep(0.3)
open(r'D:\ds-arb-test\watch_market\evidence\Q00\live-20261109T141903Z\raw\rpc_archive_probe.json', 'w', encoding='utf-8').write(json.dumps(log, ensure_ascii=False, indent=1))
print(json.dumps(log, ensure_ascii=False, indent=1))
