import json, pathlib, subprocess, time, hashlib, re, datetime, html

ROOT=pathlib.Path('/workspace/watch_market')
OUT=ROOT/'evidence/Q00/full-20261108T152118Z'
utc=lambda:datetime.datetime.now(datetime.timezone.utc).isoformat()
started=utc()
items=json.loads((ROOT/'registry/findings.json').read_text())['items']
urls=list(dict.fromkeys(u for x in items for u in x['evidence_urls'] if 'raw.githubusercontent.com' in u or '/releases/tag/' in u))
urls += [u for u in [
 'https://raw.githubusercontent.com/Polymarket/ctf-exchange/main/README.md',
 'https://raw.githubusercontent.com/lidofinance/core/master/contracts/0.8.9/WithdrawalQueue.sol',
 'https://raw.githubusercontent.com/lidofinance/core/master/contracts/0.6.12/WstETH.sol',
 'https://raw.githubusercontent.com/makerdao/sdai/master/README.md',
] if u not in urls]
patterns=r'finalize|claim|owner|resumed|request|wsteth|withdrawalqueue|steth|chainid|jenner|2026|CAS20|702|admin|token_program|supported_mint|mint_a|mint_b|repay|borrower|redeem|archiv|base/base|base-org/node|200ms|persistence|Gas-Used|eth_call|amountIn =|amountOut|gasEstimate|dispute|burn|USDC|underlying|wrapped|WITHDRAW_QUEUE_ROLE|maxWithdraw|maxRedeem|NotEnoughLiquidity|withdrawQueue|liquidity|forgo|fee|tokensOwed|shortfall|blacklist|accrued|TCR|bootstrap|_LUSDamount|_maxFeePercentage|previewRedeem|limit|receiveAToken|actualDebtToLiquidate|onlyMinters|whenNotPaused|isPaused|supportMarket|poolRegistry|isListed|preBorrowHook|oracle|PMCT|CollateralToken|0xE111|0xC011|V2|payout|Mainnet|Devnet|KLend|kLend|undelegate|delay|withdraw|mintedVAI|variableDebt|params.asset'
allrows=[]
for i,url in enumerate(urls):
    time.sleep(1.05)
    at=utc()
    p=subprocess.run(['curl','-sS','-L','--max-time','20','-w','\n%{http_code}',url],capture_output=True)
    raw,status=(p.stdout.rsplit(b'\n',1)+[b'000'])[:2] if b'\n' in p.stdout else (p.stdout,b'000')
    body=raw.decode('utf-8','replace')
    if '/releases/tag/' in url:
        body=html.unescape(re.sub('<[^>]+>','\n',body))
        body='\n'.join(z.strip() for z in body.splitlines() if z.strip())
    lines=body.splitlines(); hits=[]
    for n,line in enumerate(lines):
        if re.search(patterns,line,re.I): hits.extend(range(max(0,n-2),min(len(lines),n+4)))
    # Full source is hashed, only selected evidence persisted. Each candidate's targeted code is reread below.
    selected=sorted(set(hits))
    excerpts=[{'line':n+1,'text':lines[n]} for n in selected]
    row={'source_id':'S%02d'%(i+1),'url':url,'fetched_at':at,'http_status':status.decode('ascii','replace'),'curl_exit':p.returncode,'error':p.stderr.decode('utf-8','replace')[:1000],'sha256':hashlib.sha256(raw).hexdigest(),'response_bytes':len(raw),'line_count':len(lines),'line_number_kind':'rendered_text' if '/releases/tag/' in url else 'source','excerpts':excerpts}
    allrows.append(row)
    (OUT/'independent-sources.json').write_text(json.dumps({'started_at':started,'finished_at':utc(),'sources':allrows},ensure_ascii=False,indent=2))
    print(row['source_id'],row['http_status'],len(raw),url,flush=True)
print('FINISHED',len(allrows),flush=True)
