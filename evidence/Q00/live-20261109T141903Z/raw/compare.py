import json, re

ROOT = r'D:\ds-arb-test\watch_market'
RUN = 'live-20261109T141903Z'
n2 = json.load(open(ROOT + rf'\evidence\Q00\live-20261109T141903Z\raw\network_checks2.json', encoding='utf-8'))['derived']
n3 = json.load(open(ROOT + rf'\evidence\Q00\live-20261109T141903Z\raw\network_checks3.json', encoding='utf-8'))['derived']

def w0(hexstr):
    if not isinstance(hexstr, str):
        return None
    return int(hexstr[2:66], 16)

res = {}
g = n2['gate']
res['gate'] = {
    'chain_id': int(g['chain_id'], 16),
    'block_hash': g['block_hash'],
    'block_timestamp': g['block_timestamp'],
    'base_fee': g['base_fee'],
    'pool_code_bytes': g['pool_code_bytes'], 'pool_code_keccak': g['pool_code_keccak'],
    'steth_code_bytes': g['steth_code_bytes'], 'steth_code_keccak': g['steth_code_keccak'],
    'pool_eip1967': g['pool_eip1967_slot0'], 'steth_eip1967': g['steth_eip1967_slot0'],
    'coins0': g['coins0'], 'coins1': g['coins1'],
    'fee_raw': int(g['fee'], 16),
    'get_dy_001_raw': int(g['get_dy_001'], 16),
    'get_dy_100_raw': int(g['get_dy_100'], 16),
}
f = n2['findings']
res['quotes'] = {
    'eth_curve_steth_100_at26377950_raw': int(f['ETH-LIDO-STETH-WITHDRAWAL-QUEUE-EXIT']['get_dy_100_steth'], 16),
    'eth_univ3_wsteth_100_raw': w0(f['ETH-LIDO-WSTETH-QUEUE-VS-DEX-EXIT']['quoter_wsteth_100']),
    'eth_wsteth_stEthPerToken_raw': int(f['ETH-LIDO-WSTETH-QUEUE-VS-DEX-EXIT']['stEthPerToken'], 16),
    'eth_reth_getEthValue100_raw': int(f['ETH-ROCKETPOOL-RETH-INSTANT-BURN']['getEthValue_100'], 16),
    'eth_reth_totalCollateral_raw': int(f['ETH-ROCKETPOOL-RETH-INSTANT-BURN']['getTotalCollateral'], 16),
    'base_usdc_to_usdbc_1_raw': w0(f['BASE-USDC-USDbC-DEX-DISCOUNT-20261109']['quote_buy_usdbc_1']),
    'base_usdbc_to_usdc_100_raw': w0(f['BASE-USDC-USDbC-DEX-DISCOUNT-20261109']['quote_sell_usdbc_100']),
    'base_cbeth_l1Token': f['BASE-LST-BRIDGED-NO-NATIVE-REDEMPTION']['cbETH_l1Token'],
    'base_cbeth_exchangeRate_err': f['BASE-LST-BRIDGED-NO-NATIVE-REDEMPTION']['cbETH_exchangeRate_expected_revert'],
    'op_usdc_to_usdt_1000_raw': w0(f['OP-USDT-BRIDGE-DISCOUNT-DELAYED']['quoter_usdc_usdt_1000']),
    'op_usdt_l1Token': f['OP-USDT-BRIDGE-DISCOUNT-DELAYED']['usdt_l1Token'],
    'bnb_psm_getDayBuyLeft_raw': int(f['BNB-LISUSD-PUBLIC-REDEMPTION-ASSUMPTION']['getDayBuyLeft'], 16),
    'poly_pmct_impl_slot': f['POLY-POLYMARKET-V2-PMCT-ONCHAIN-ROLES']['pmct_impl_slot'],
    'poly_pmct_totalSupply_raw': int(f['POLY-POLYMARKET-V2-PMCT-ONCHAIN-ROLES']['pmct_totalSupply'], 16),
    'arb_wsteth_1_raw': int(n3['arb_wsteth_1'], 16),
    'arb_reth_1_raw': int(n3['arb_reth_1'], 16),
}
# expected from original evidence
expected = {
    'gate_get_dy_001_raw': 9997160735119382,
    'gate_fee_raw': 1000000,
    'eth_curve_steth_100': 99.971312137,
    'eth_univ3_wsteth_100': 124.846612633,
    'eth_stEthPerToken': 1.248822059877,
    'eth_reth_getEthValue100': 117.543595045,
    'eth_reth_totalCollateral': 2087.964746,
    'base_usdc_to_usdbc_1': 1.000018,
    'base_usdbc_to_usdc_100': 99.977632,
    'op_usdc_to_usdt_1000': 1000.904767,
    'arb_wsteth_1': 1.248497488656218,
    'arb_reth_1': 1.1737989660492183,
    'bnb_dayBuyLeft': 500000,
    'poly_pmct_totalSupply': 519400000.0,
}
res['comparison'] = {
    'gate_get_dy_001': {'mine': res['gate']['get_dy_001_raw'], 'their': expected['gate_get_dy_001_raw'], 'match': res['gate']['get_dy_001_raw'] == expected['gate_get_dy_001_raw']},
    'gate_fee': {'mine': res['gate']['fee_raw'], 'their': expected['gate_fee_raw'], 'match': res['gate']['fee_raw'] == 1000000},
    'eth_curve_steth_100': {'mine': res['quotes']['eth_curve_steth_100_at26377950_raw'] / 1e18, 'their': expected['eth_curve_steth_100']},
    'eth_univ3_wsteth_100': {'mine': res['quotes']['eth_univ3_wsteth_100_raw'] / 1e18, 'their': expected['eth_univ3_wsteth_100']},
    'eth_stEthPerToken': {'mine': res['quotes']['eth_wsteth_stEthPerToken_raw'] / 1e18, 'their': expected['eth_stEthPerToken']},
    'eth_reth_getEthValue100': {'mine': res['quotes']['eth_reth_getEthValue100_raw'] / 1e18, 'their': expected['eth_reth_getEthValue100']},
    'eth_reth_totalCollateral': {'mine': res['quotes']['eth_reth_totalCollateral_raw'] / 1e18, 'their': expected['eth_reth_totalCollateral']},
    'base_usdc_to_usdbc_1': {'mine': res['quotes']['base_usdc_to_usdbc_1_raw'] / 1e6, 'their': expected['base_usdc_to_usdbc_1']},
    'base_usdbc_to_usdc_100': {'mine': res['quotes']['base_usdbc_to_usdc_100_raw'] / 1e6, 'their': expected['base_usdbc_to_usdc_100']},
    'op_usdc_to_usdt_1000': {'mine': res['quotes']['op_usdc_to_usdt_1000_raw'] / 1e6, 'their': expected['op_usdc_to_usdt_1000']},
    'arb_wsteth_1': {'mine': res['quotes']['arb_wsteth_1_raw'] / 1e18, 'their': expected['arb_wsteth_1']},
    'arb_reth_1': {'mine': res['quotes']['arb_reth_1_raw'] / 1e18, 'their': expected['arb_reth_1']},
    'bnb_dayBuyLeft': {'mine': res['quotes']['bnb_psm_getDayBuyLeft_raw'] / 1e18, 'their': expected['bnb_dayBuyLeft']},
    'poly_pmct_totalSupply': {'mine': res['quotes']['poly_pmct_totalSupply_raw'] / 1e6, 'their': expected['poly_pmct_totalSupply']},
}

# ---- report vs record consistency sample ----
sample = ['N-ETH', 'ETH01', 'BNB01', 'SOL01', 'BASE02', 'X-ARB']
cons = []
for r in sample:
    rec = json.load(open(ROOT + rf'\evidence\{r}\{RUN}\record.json', encoding='utf-8'))
    rep = open(ROOT + rf'\reports\agents\{r}\2026-11-09\{RUN}.md', encoding='utf-8').read()
    block = str(rec.get('block_or_slot'))
    row = {'role': r, 'record_block': block, 'block_in_report': block in rep.replace(',', ''), 'record_status': rec.get('status'),
           'status_in_report': rec.get('status') in rep, 'record_exec': rec.get('execution_status'), 'exec_in_report': rec.get('execution_status') in rep,
           'finding_ids': [x.get('finding_id') for x in (rec.get('findings') or [])],
           'findings_in_report': all((x.get('finding_id') in rep) for x in (rec.get('findings') or [])),
           'quotes': len(rec.get('quotes') or []), 'record_run': rec.get('run_id'), 'report_bytes': len(rep)}
    cons.append(row)
res['report_record_consistency'] = cons
res['request_totals'] = {'run1': 36, 'probe': 5, 'run2': 34, 'run3': 7}
json.dump(res, open(ROOT + rf'\evidence\Q00\live-20261109T141903Z\raw\comparison.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(json.dumps(res['comparison'], ensure_ascii=False, indent=1))
print(json.dumps(cons, ensure_ascii=False, indent=1))
