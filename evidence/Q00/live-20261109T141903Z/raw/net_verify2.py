import json, time, requests
from Crypto.Hash import keccak

ROOT = r'D:\ds-arb-test\watch_market'
PROXY = {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}
S = requests.Session(); S.trust_env = False; S.proxies = PROXY
S.headers.update({"Content-Type": "application/json"})
RPC = {
    'ETH': 'https://eth.drpc.org',
    'ARB': 'https://arbitrum.drpc.org',
    'BASE': 'https://base.drpc.org',
    'BNB': 'https://bsc.drpc.org',
    'AVAX': 'https://avalanche.drpc.org',
    'OP': 'https://optimism.drpc.org',
    'POLY': 'https://polygon.drpc.org',
}
count = [0]; log = []

def sel(sig):
    k = keccak.new(digest_bits=256); k.update(sig.encode()); return '0x' + k.hexdigest()[:8]

def pad_addr(a): return a.lower().replace('0x', '').rjust(64, '0')
def pad_uint(n): return format(n, 'x').rjust(64, '0')

def rpc(chain, method, params, label):
    count[0] += 1; t0 = time.time()
    try:
        r = S.post(RPC[chain], json={"jsonrpc": "2.0", "id": count[0], "method": method, "params": params}, timeout=25)
        res = r.json()
    except Exception as e:
        res = {"error": str(e)}
    log.append({"label": label, "chain": chain, "method": method, "params": params, "elapsed_s": round(time.time() - t0, 3), "response": res})
    time.sleep(0.25)
    return res

def call(chain, to, data, block, label): return rpc(chain, 'eth_call', [{"to": to, "data": data}, hex(block)], label)
def res1(r): return r.get('result') if isinstance(r, dict) and 'result' in r else r.get('error')

out = {}
# ---------- A. gate pinned 26377898 on eth.drpc ----------
G = 26377898
gate = {}
gate['chain_id'] = res1(rpc('ETH', 'eth_chainId', [], 'gate.chainId'))
blk = res1(rpc('ETH', 'eth_getBlockByNumber', [hex(G), False], 'gate.block'))
gate['block_hash'] = blk.get('hash') if isinstance(blk, dict) else None
gate['block_timestamp'] = int(blk['timestamp'], 16) if isinstance(blk, dict) else None
gate['base_fee'] = int(blk['baseFeePerGas'], 16) if isinstance(blk, dict) else None
pool = '0xDC24316b9AE028F1497c275EB9192a3Ea0f67022'
steth = '0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84'
for name, addr in (('pool', pool), ('steth', steth)):
    c = res1(rpc('ETH', 'eth_getCode', [addr, hex(G)], 'gate.%s.code' % name))
    gate[name + '_code_bytes'] = (len(c) - 2) // 2 if isinstance(c, str) else None
    gate[name + '_code_keccak'] = '0x' + keccak.new(digest_bits=256, data=bytes.fromhex(c[2:])).hexdigest() if isinstance(c, str) else None
    gate[name + '_eip1967_slot0'] = res1(rpc('ETH', 'eth_getStorageAt', [addr, '0x' + '0' * 64, hex(G)], 'gate.%s.eip1967' % name))
gate['coins0'] = res1(call('ETH', pool, sel('coins(uint256)') + pad_uint(0), G, 'gate.coins0'))
gate['coins1'] = res1(call('ETH', pool, sel('coins(uint256)') + pad_uint(1), G, 'gate.coins1'))
gate['fee'] = res1(call('ETH', pool, sel('fee()'), G, 'gate.fee'))
gate['get_dy_001'] = res1(call('ETH', pool, sel('get_dy(int128,int128,uint256)') + pad_uint(1) + pad_uint(0) + pad_uint(10**16), G, 'gate.get_dy(1,0,1e16)'))
gate['get_dy_100'] = res1(call('ETH', pool, sel('get_dy(int128,int128,uint256)') + pad_uint(1) + pad_uint(0) + pad_uint(100 * 10**18), G, 'gate.get_dy(1,0,100e18)'))
gate['steth_symbol'] = res1(call('ETH', steth, sel('symbol()'), G, 'gate.steth.symbol'))
gate['steth_decimals'] = res1(call('ETH', steth, sel('decimals()'), G, 'gate.steth.decimals'))
out['gate'] = gate

# ---------- B. findings ----------
f = {}
B1 = 26377950
QV2 = '0x61fFE014bA17989E743c5F6cB21bF9697530B21e'
wst = '0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0'
weth = '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2'
f['ETH-LIDO-STETH-WITHDRAWAL-QUEUE-EXIT'] = {'block': B1, 'get_dy_100_steth': res1(call('ETH', pool, sel('get_dy(int128,int128,uint256)') + pad_uint(1) + pad_uint(0) + pad_uint(100 * 10**18), B1, 'q.curve.dy100@26377950'))}
f['ETH-LIDO-WSTETH-QUEUE-VS-DEX-EXIT'] = {'block': B1,
    'quoter_wsteth_100': res1(call('ETH', QV2, sel('quoteExactInputSingle((address,address,uint256,uint24,uint160))') + pad_addr(wst) + pad_addr(weth) + pad_uint(100 * 10**18) + pad_uint(100) + pad_uint(0), B1, 'q.univ3.wsteth100@26377950')),
    'stEthPerToken': res1(call('ETH', wst, sel('stEthPerToken()'), B1, 'q.wsteth.stEthPerToken@26377950'))}
reth1 = '0xae78736Cd615f374D3085123A210448E74Fc6393'
f['ETH-ROCKETPOOL-RETH-INSTANT-BURN'] = {'block': B1,
    'getEthValue_100': res1(call('ETH', reth1, sel('getEthValue(uint256)') + pad_uint(100 * 10**18), B1, 'q.reth.getEthValue100@26377950')),
    'getTotalCollateral': res1(call('ETH', reth1, sel('getTotalCollateral()'), B1, 'q.reth.getTotalCollateral@26377950'))}
A3 = 522707442
qv1 = sel('quoteExactInputSingle(address,address,uint24,uint256,uint160)')
qarb = '0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6'
wst_arb = '0x5979D7b546E38E414F7E9822514be443A4800529'; reth_arb = '0xEC70Dcb4A1EFa46b8F2D97C310C9c4790ba5ffA8'; weth_arb = '0x82aF49447D8a07e3bd95BD0d56f35241523fBab1'
f['ARB-WSTETH-L2-DEX-DISCOUNT-VS-L1-REFERENCE'] = {'block': A3,
    'quoter_wsteth_1': res1(call('ARB', qarb, qv1 + pad_addr(wst_arb) + pad_addr(weth_arb) + pad_uint(100) + pad_uint(10**18) + pad_uint(0), A3, 'q.arb.wsteth1@522707442')),
    'wsteth_l2_stEthPerToken': res1(call('ARB', wst_arb, sel('stEthPerToken()'), A3, 'q.arb.wsteth.stEthPerToken(expect revert)'))}
f['ARB-RETH-L2-DEX-DISCOUNT-VS-L1-REFERENCE'] = {'block': A3,
    'quoter_reth_1': res1(call('ARB', qarb, qv1 + pad_addr(reth_arb) + pad_addr(weth_arb) + pad_uint(500) + pad_uint(10**18) + pad_uint(0), A3, 'q.arb.reth1@522707442'))}
BSE = 55228648
qbase = '0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a'
usdc_b = '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913'; usdbc = '0xd9aAEc86B65D86f6A7B5B1b0c42FFA531710b6CA'
qb = sel('quoteExactInputSingle((address,address,uint256,uint24,uint160))')
f['BASE-USDC-USDbC-DEX-DISCOUNT-20261109'] = {'block': BSE,
    'quote_buy_usdbc_1': res1(call('BASE', qbase, qb + pad_addr(usdc_b) + pad_addr(usdbc) + pad_uint(10**6) + pad_uint(100) + pad_uint(0), BSE, 'q.base.usdc->usdbc 1')),
    'quote_sell_usdbc_100': res1(call('BASE', qbase, qb + pad_addr(usdbc) + pad_addr(usdc_b) + pad_uint(100 * 10**6) + pad_uint(100) + pad_uint(0), BSE, 'q.base.usdbc->usdc 100'))}
cbeth = '0x2Ae3F1Ec7F1F5012CFEab0185bfc7aa3cf0DEc22'
f['BASE-LST-BRIDGED-NO-NATIVE-REDEMPTION'] = {'block': BSE,
    'cbETH_exchangeRate_expected_revert': res1(call('BASE', cbeth, sel('exchangeRate()'), BSE, 'q.base.cbeth.exchangeRate(expect revert)')),
    'cbETH_l1Token': res1(call('BASE', cbeth, sel('l1Token()'), BSE, 'q.base.cbeth.l1Token'))}
BN = 132601543; psm = '0xaa57F36DD5Ef2aC471863ec46277f976f272eC0c'
f['BNB-LISUSD-PUBLIC-REDEMPTION-ASSUMPTION'] = {'block': BN,
    'buyFee': res1(call('BNB', psm, sel('buyFee()'), BN, 'q.bnb.psm.buyFee')),
    'sellFee': res1(call('BNB', psm, sel('sellFee()'), BN, 'q.bnb.psm.sellFee')),
    'getDayBuyLeft': res1(call('BNB', psm, sel('getDayBuyLeft()'), BN, 'q.bnb.psm.getDayBuyLeft'))}
BN2 = 132604696
router_bnb = '0x10ED43C718714eb63d5aA57B78B54704E256024E'
path = ['0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d', '0x55d398326f99059fF775485246999027B3197955', '0x1AF3F329e8BE154074D8769D1FFa4eE058B1DBc3', '0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d']
enc = sel('getAmountsOut(uint256,address[])') + pad_uint(10**18) + pad_uint(0x40) + pad_uint(len(path)) + ''.join(pad_addr(a) for a in path)
f['BNB-USDC-USDT-DAI-PANCAKE-V2-TRIANGLE-NEGATIVE'] = {'block': BN2, 'getAmountsOut_1USDC': res1(call('BNB', router_bnb, enc, BN2, 'q.bnb.pancake.triangle 1USDC'))}
AV = 99858972; acurve = '0x7f90122BF0700F9E7e1F688fe926940E8839F353'
gdy = sel('get_dy(int128,int128,uint256)')
d1 = res1(call('AVAX', acurve, gdy + pad_uint(0) + pad_uint(1) + pad_uint(10**18), AV, 'q.avax.curve.dy(0,1,1e18)'))
d2 = res1(call('AVAX', acurve, gdy + pad_uint(1) + pad_uint(2) + pad_uint(int(d1, 16)), AV, 'q.avax.curve.dy(1,2,out1)')) if isinstance(d1, str) else None
d3 = res1(call('AVAX', acurve, gdy + pad_uint(2) + pad_uint(0) + pad_uint(int(d2, 16)), AV, 'q.avax.curve.dy(2,0,out2)')) if isinstance(d2, str) else None
f['AVAX-CURVE-AAVE-POOL-DAIE-USDC.E-USDTE-CLOSED-LOOP'] = {'block': AV, 'dy_leg1': d1, 'dy_leg2': d2, 'dy_leg3': d3}
OPB = 159319120; qop = '0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6'
usdc_op = '0x0b2c639c533813f4aa9d7837caf62653d097ff85'; usdt_op = '0x94b008aA00579c1307B0EF2c499aD98a8ce58e58'
f['OP-USDT-BRIDGE-DISCOUNT-DELAYED'] = {'block': OPB,
    'quoter_usdc_usdt_1000': res1(call('OP', qop, qv1 + pad_addr(usdc_op) + pad_addr(usdt_op) + pad_uint(100) + pad_uint(1000 * 10**6) + pad_uint(0), OPB, 'q.op.usdc->usdt 1000')),
    'usdt_l1Token': res1(call('OP', usdt_op, sel('l1Token()'), OPB, 'q.op.usdt.l1Token'))}
PL = 97021016; pmct = '0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB'
IMP_SLOT = '0x360894a13ba1a3210667c828492db98d7b8a15cbd5b4e5e6e4b12f2ba45f5a17'
f['POLY-POLYMARKET-V2-PMCT-ONCHAIN-ROLES'] = {'block': PL,
    'pmct_impl_slot': res1(rpc('POLY', 'eth_getStorageAt', [pmct, IMP_SLOT, hex(PL)], 'q.poly.pmct.impl_slot')),
    'pmct_totalSupply': res1(call('POLY', pmct, sel('totalSupply()'), PL, 'q.poly.pmct.totalSupply'))}
out['findings'] = f
out['request_count'] = count[0]
json.dump({'log': log, 'derived': out}, open(ROOT + r'\evidence\Q00\live-20261109T141903Z\raw\network_checks2.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('requests:', count[0])
print(json.dumps({k: out['gate'][k] for k in ('chain_id', 'block_hash', 'pool_code_bytes', 'pool_code_keccak', 'steth_code_bytes', 'steth_code_keccak', 'coins0', 'coins1', 'fee', 'get_dy_001', 'get_dy_100')}, ensure_ascii=False, indent=1))
