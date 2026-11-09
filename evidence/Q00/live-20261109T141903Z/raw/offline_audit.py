import json, os, re, collections

ROOT = r'D:\ds-arb-test\watch_market'
RUN = 'live-20261109T141903Z'
DATE = '2026-11-09'

def load(p):
    with open(os.path.join(ROOT, p), encoding='utf-8') as f:
        return json.load(f)

def exists(p):
    return os.path.isfile(os.path.join(ROOT, p))

agents = load('config/agents.json')
ids = [a['id'] for a in agents if a.get('enabled')]
research = [a['id'] for a in agents if a.get('enabled') and a['id'] not in ('M00', 'Q00')]
findings = load('registry/findings.json')['items']
cur = [x for x in findings if x.get('last_observed_run') == RUN]

REPORT = 'reports/agents/{id}/{date}/{run}.md'
RECORD = 'evidence/{id}/{run}/record.json'
STATE = 'state/agents/{id}.json'

rows = []
for rid in research:
    rep = REPORT.format(id=rid, date=DATE, run=RUN)
    rec = RECORD.format(id=rid, run=RUN)
    st = STATE.format(id=rid)
    e = {'id': rid, 'report': exists(rep), 'record': exists(rec), 'state': exists(st)}
    if e['report']:
        e['report_bytes'] = os.path.getsize(os.path.join(ROOT, rep))
    if e['record']:
        try:
            r = load(rec)
            e['exec_status'] = r.get('execution_status')
            e['status'] = r.get('status')
            e['quotes'] = len(r.get('quotes') or [])
            e['block'] = r.get('block_or_slot')
            e['asof_utc'] = (r.get('as_of') or {}).get('utc')
            e['finding_ids'] = [f.get('finding_id') for f in (r.get('findings') or [])]
            e['record_bytes'] = os.path.getsize(os.path.join(ROOT, rec))
            missing = [k for k in ['agent_id','run_id','chain','scope','started_at','finished_at','duration_seconds','execution_status','status','as_of','block_or_slot','market_ids','asset_ids','discovery_source','mechanism','observations','quotes','net_result','capacity','permissions','liabilities','waiting_time','invalidation_conditions','evidence_urls','coverage_gaps','next_check','handoff_to','markets','findings','rejections','observed_cursor'] if k not in r]
            e['missing_keys'] = missing
            bad_quotes = [q for q in (r.get('quotes') or []) if q.get('block') in (None, '') or not q.get('quote_time_utc')]
            e['quotes_no_block_or_time'] = len(bad_quotes)
            e['bad_quote_examples'] = bad_quotes[:2]
        except Exception as ex:
            e['record_error'] = str(ex)
    if e['state']:
        try:
            s = load(st)
            e['state_run'] = s.get('last_research_run_id')
            e['state_storage'] = s.get('last_attempt_storage')
            e['state_report'] = s.get('report')
            e['state_record'] = s.get('record')
        except Exception as ex:
            e['state_error'] = str(ex)
    rows.append(e)

cur_ids = {x['finding_id'] for x in cur}
owners = collections.Counter(x.get('owner') for x in cur)
# role coverage via source_record present in registry
src_rec = {x.get('source_record') for x in cur}

summary = {
    'enabled_total': len(ids),
    'research_roles': len(research),
    'reports_present': sum(1 for r in rows if r['report']),
    'records_present': sum(1 for r in rows if r['record']),
    'states_present': sum(1 for r in rows if r['state']),
    'missing_any': [r['id'] for r in rows if not (r['report'] and r['record'] and r['state'])],
    'missing_keys_roles': {r['id']: r['missing_keys'] for r in rows if r.get('missing_keys')},
    'quotes_no_block_or_time': {r['id']: r['quotes_no_block_or_time'] for r in rows if r.get('quotes_no_block_or_time')},
    'bad_quote_examples': {r['id']: r.get('bad_quote_examples') for r in rows if r.get('bad_quote_examples')},
    'exec_status': dict(collections.Counter(r.get('exec_status') for r in rows)),
    'record_status': dict(collections.Counter(r.get('status') for r in rows)),
    'states_missing_run': [r['id'] for r in rows if r.get('state') and r.get('state_run') != RUN],
    'total_quotes': sum(r.get('quotes') or 0 for r in rows),
    'cur_findings': len(cur),
    'cur_by_status': dict(collections.Counter(x.get('status') for x in cur)),
    'cur_owners': dict(owners),
    'roles_with_current_findings': len({x.get('owner') for x in cur}),
    'roles_without_current_findings': sorted([r['id'] for r in rows if r['id'] not in owners]),
    'source_record_count': len([s for s in src_rec if s]),
    'findings_missing_source_record': [x['finding_id'] for x in cur if not x.get('source_record')],
    'findings_missing_evidence_urls': [x['finding_id'] for x in cur if not x.get('evidence_urls')],
    'findings_missing_observed_at': [x['finding_id'] for x in cur if not x.get('last_observed_at')],
    'findings_missing_verified_onchain': [x['finding_id'] for x in cur if not x.get('last_verified_onchain_at')],
    'roles': rows,
}
os.makedirs(os.path.join(ROOT, 'evidence/Q00/live-20261109T141903Z/raw'), exist_ok=True)
with open(os.path.join(ROOT, 'evidence/Q00/live-20261109T141903Z/raw/offline_audit.json'), 'w', encoding='utf-8') as f:
    json.dump(summary, f, ensure_ascii=False, indent=1)
print('done', summary['reports_present'], summary['records_present'], summary['states_present'])
