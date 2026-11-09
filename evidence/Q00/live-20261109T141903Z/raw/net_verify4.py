import json, time, requests
from Crypto.Hash import keccak
S = requests.Session(); S.trust_env = False; S.proxies = {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}
S.headers.update({"Content-Type": "application/json"})
def sel(sig):
    k = keccak.new(digest_bits=256); k.update(sig.encode()); return '0x' + k.hexdigest()[:8]
def pa(a): return a.lower().replace('0x', '').rjust(64, '0')
def pu(n): return format(n, 'x').rjust(64, '0')
log = []; count = [0]
def rpc(url, method, params, label):
    count[0] += 1
    try:
        r = S.post(url, json={"jsonrpc": "2.0", "id": count[0], "method": method, "params": params}, timeout=25)
        res = r.json()
    except Exception as e:
        res = {"error": str(e)}
    log.append({"label": label, "method": method, "params": params, "response": res}); time.sleep(0.3); return res
def call(url, to, data, block, label): return rpc(url, 'eth_call', [{"to": to, "data": data}, hex(block)], label)
ETH = 'https://eth.drpc.org'; OP = 'https://optimism.drpc.org'; ARB = 'https://arbitrum-one.public.blastapi.io'
out = {}
# rejection 1: sDAI premium (ETH03) — NAV convertToAssets + Curve get_dy(0,1,1e18)==FRAX->sDAI buy side
sdai = '0x83F20F44975D03b1b09e64809B757c47f942BEeA'
out['sdai_convertToAssets_1'] = call(ETH, sdai, sel('convertToAssets(uint256)') + pu(10**18), 26378111, 'sdai.nav').get('result')
curve_sdai = '0xcE6431D21E3fb1036CE9973a3312368ED96F5CE7'
out['curve_sdai_frax_buy1'] = call(ETH, curve_sdai, sel('get_dy(int128,int128,uint256)') + pu(0) + pu(1) + pu(10**18), 26378111, 'curve.sdai.buy1').get('result')
out['curve_sdai_sell1'] = call(ETH, curve_sdai, sel('get_dy(int128,int128,uint256)') + pu(1) + pu(0) + pu(10**18), 26378111, 'curve.sdai.sell1').get('result')
# rejection 2: OP02 Velodrome getAmountOut view not swap proof — factory isPaused/getFee revert + pool code size
velo_factory = '0xF1046053aa5682b4F9a81b5481394DA16BE5FF5a'
velo_pool = '0x0493bf8b6dbb159ce2db2e0e8403e753abd1235b'
out['velo_isPaused'] = call(OP, velo_factory, sel('isPaused(address)') + pa(velo_pool), 159319129, 'velo.isPaused').get('result')
out['velo_isPaused_err'] = call(OP, velo_factory, sel('isPaused(address)') + pa(velo_pool), 159319129, 'velo.isPaused2')
c = rpc(OP, 'eth_getCode', [velo_pool, hex(159319129)], 'velo.pool.code').get('result')
out['velo_pool_code_bytes'] = (len(c) - 2) // 2 if isinstance(c, str) else None
# rejection 3: ARB01 Uni V3 first-leg quote reproduction at pinned 522706375 (10 USDC.e -> WETH fee500)
qarb = '0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6'
out['arb01_uni_10usdc_to_weth'] = call(ARB, qarb, sel('quoteExactInputSingle(address,address,uint24,uint256,uint160)') + pa('0xff970a61a04b1ca14834a43f5de4533ebddb5cc8') + pa('0x82af49447d8a07e3bd95bd0d56f35241523fbab1') + pu(500) + pu(10**6) * 0 + pu(10 * 10**6) + pu(0), 522706375, 'arb01.uni.10usdc').get('result')
out['request_count'] = count[0]
json.dump({'log': log, 'derived': out}, open(r'D:\ds-arb-test\watch_market\evidence\Q00\live-20261109T141903Z\raw\network_checks4.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1)[:2500])
