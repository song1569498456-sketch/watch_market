import json, os

ROOT = r'D:\ds-arb-test\watch_market'
RUN = 'live-20261109T141903Z'
roles = ['N-ETH', 'ETH01', 'ETH02', 'ETH03', 'ARB01', 'ARB02', 'ARB03', 'BASE01', 'BASE02', 'AVAX01', 'AVAX02', 'BNB01', 'BNB03', 'BNB04', 'POLY01', 'POLY03', 'OP01', 'OP02', 'SONIC02', 'X-ARB', 'X-BASE']
out = []
for r in roles:
    p = os.path.join(ROOT, 'evidence', r, RUN, 'record.json')
    rec = json.load(open(p, encoding='utf-8'))
    out.append('########## ' + r + ' block=' + str(rec.get('block_or_slot')) + ' status=' + str(rec.get('status')))
    out.append('AS_OF: ' + json.dumps(rec.get('as_of'), ensure_ascii=False))
    for q in rec.get('quotes') or []:
        out.append('Q: ' + json.dumps(q, ensure_ascii=False))
    for f in rec.get('findings') or []:
        out.append('F: ' + json.dumps({k: f.get(k) for k in ('finding_id', 'status', 'market_id')}, ensure_ascii=False))
    for m in rec.get('markets') or []:
        out.append('M: ' + json.dumps(m, ensure_ascii=False)[:500])
open(ROOT + r'\evidence\Q00\live-20261109T141903Z\raw\_quotes.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('lines', len(out))
