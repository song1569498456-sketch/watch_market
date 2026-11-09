import json, time, requests

PROXY = {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}
S = requests.Session(); S.trust_env = False; S.proxies = PROXY
S.headers.update({"Content-Type": "application/json"})
from Crypto.Hash import keccak

def sel(sig):
    k = keccak.new(digest_bits=256); k.update(sig.encode()); return '0x' + k.hexdigest()[:8]
def pa(a): return a.lower().replace('0x', '').rjust(64, '0')
def pu(n): return format(n, 'x').rjust(64, '0')
count = [0]; log = []

def rpc(url, method, params, label, chain):
    count[0] += 1
    try:
        r = S.post(url, json={"jsonrpc": "2.0", "id": count[0], "method": method, "params": params}, timeout=25)
        res = r.json()
    except Exception as e:
        res = {"error": str(e)}
    log.append({"label": label, "chain": chain, "method": method, "params": params, "response": res})
    time.sleep(0.3)
    return res
def call(url, to, data, block, label, chain): return rpc(url, 'eth_call', [{"to": to, "data": data}, hex(block)], label, chain)

ARB = 'https://arbitrum-one.public.blastapi.io'
BNB = 'https://bnb-mainnet.public.blastapi.io'
AVAX = 'https://avax-mainnet.public.blastapi.io'
qv1 = sel('quoteExactInputSingle(address,address,uint24,uint256,uint160)')
qarb = '0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6'
wst_arb = '0x5979D7b546E38E414F7E9822514be443A4800529'; reth_arb = '0xEC70Dcb4A1EFa46b8F2D97C310C9c4790ba5ffA8'; weth_arb = '0x82aF49447D8a07e3bd95BD0d56f35241523fBab1'
pv2 = sel('quoteExactInputSingle((address,address,uint256,uint24,uint160))')
out = {}
out['arb_wsteth_1'] = call(ARB, qarb, qv1 + pa(wst_arb) + pa(weth_arb) + pu(100) + pu(10**18) + pu(0), 522707442, 'arb.wsteth1', 'ARB').get('result')
out['arb_reth_1'] = call(ARB, qarb, qv1 + pa(reth_arb) + pa(weth_arb) + pu(500) + pu(10**18) + pu(0), 522707442, 'arb.reth1', 'ARB').get('result')
out['arb_wsteth_stEthPerToken'] = call(ARB, wst_arb, sel('stEthPerToken()'), 522707442, 'arb.wsteth.rate', 'ARB').get('result')
BN = 132601543; psm = '0xaa57F36DD5Ef2aC471863ec46277f976f272eC0c'
out['bnb_buyFee'] = call(BNB, psm, sel('buyFee()'), BN, 'bnb.buyFee', 'BNB').get('result')
out['bnb_sellFee'] = call(BNB, psm, sel('sellFee()'), BN, 'bnb.sellFee', 'BNB').get('result')
BN2 = 132604696
router = '0x10ED43C718714eb63d5aA57B78B54704E256024E'
path = ['0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d', '0x55d398326f99059fF775485246999027B3197955', '0x1AF3F329e8BE154074D8769D1FFa4eE058B1DBc3', '0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d']
enc = sel('getAmountsOut(uint256,address[])') + pu(10**18) + pu(0x40) + pu(4) + ''.join(pa(a) for a in path)
out['bnb_triangle'] = call(BNB, router, enc, BN2, 'bnb.triangle', 'BNB').get('result')
AV = 99858972; acurve = '0x7f90122BF0700F9E7e1F688fe926940E8839F353'; gdy = sel('get_dy(int128,int128,uint256)')
d1 = call(AVAX, acurve, gdy + pu(0) + pu(1) + pu(10**18), AV, 'avax.leg1', 'AVAX').get('result')
d2 = call(AVAX, acurve, gdy + pu(1) + pu(2) + pu(int(d1, 16)), AV, 'avax.leg2', 'AVAX').get('result') if isinstance(d1, str) else None
d3 = call(AVAX, acurve, gdy + pu(2) + pu(0) + pu(int(d2, 16)), AV, 'avax.leg3', 'AVAX').get('result') if isinstance(d2, str) else None
out['avax_leg1'] = d1; out['avax_leg2'] = d2; out['avax_leg3'] = d3
out['request_count'] = count[0]
json.dump({'log': log, 'derived': out}, open(r'D:\ds-arb-test\watch_market\evidence\Q00\live-20261109T141903Z\raw\network_checks3.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1)[:3000])
