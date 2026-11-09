import json, collections

ROOT = r'D:\ds-arb-test\watch_market'
RUN = 'live-20261109T141903Z'

d = json.load(open(ROOT + r'\registry\findings.json', encoding='utf-8'))['items']
cur = [x for x in d if x.get('last_observed_run') == RUN]


def s(v, n=700):
    t = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    return (t or '')[:n]


lines = []
for x in cur:
    lines.append('===== %s | %s | %s | %s' % (x['finding_id'], x['status'], x['owner'], x['market_id']))
    lines.append('MECH: ' + s(x.get('mechanism')))
    lines.append('NET: ' + s(x.get('net_result'), 400))
    lines.append('CAP: ' + s(x.get('capacity'), 200) + ' | UNK: ' + s(x.get('unknown_costs'), 200))
    lines.append('EV: ' + json.dumps(x.get('evidence_urls'), ensure_ascii=False))
    lines.append('SRC: %s | OBS: %s' % (x.get('source_record'), list((x.get('observations_by_role') or {}).keys())))
open(ROOT + r'\evidence\Q00\live-20261109T141903Z\raw\_all_findings.txt', 'w', encoding='utf-8').write('\n'.join(lines))
print('ok lines', len(lines))
