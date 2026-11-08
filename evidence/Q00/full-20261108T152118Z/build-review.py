import json, pathlib, datetime, collections

ROOT=pathlib.Path('/workspace/watch_market')
OUT=ROOT/'evidence/Q00/full-20261108T152118Z'
run='full-20261108T152118Z'
now=datetime.datetime.now(datetime.timezone.utc).isoformat()
load=lambda p:json.loads(p.read_text())
write=lambda p,x:p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
sources=load(OUT/'independent-sources.json')
items=load(ROOT/'registry/findings.json')['items']
audit=load(OUT/'input-audit.json')
byid={s['source_id']:s for s in sources['sources']}

# Public evidence summaries, each tied to our own HTTP read and response hash.
fields={
'S01':'deployed-mainnet.json chainId=1; withdrawalQueueERC721 proxy=0x889edC2eDab5f40e902b864aD4d7AdE8E412F9B1, implementation=0xE42C659Dc09109566720EA8b2De186c2Be7D94D9; stETH/wstETH分别登记。静态部署表未证明当前代理存储。',
'S02':'L149-155 finalize需resumed和FINALIZE_ROLE；L169-175 ownerOf拒绝claimed；L230-248 transfer更新owner、清approval且不重置claimed。',
'S03':'发布正文：Jenner计划2026-12-08 02:30 UTC；BEP-702 token creation还需governance-appointed administrator另激活。公告中的非共识改动可早于硬分叉，不能统称所有发布内容都尚未生效。',
'S04':'L55-58 token_program_a/b必须等于mint owner；L82-91分别verify_supported_token_mint。未读取ProgramData或真实mint。',
'S05':'L16-19 折价时borrowers买入lisUSD偿债；文本不建立任意持有人的无条件美元兑付权。',
'S06':'L6 approve不是repayment完成；L12-18还自己的贷款。剩债文档数值不当当前参数。',
'S07':'L6 outstanding loan与提款相连，L11文档BNB等待/LST立即；不把此文档推广到公众lisUSD兑付。',
'S08':'L1-3旧仓明确archived，开发发布迁至base/base。',
'S09':'L31新仓承接原base/node public node；不是停链或当前增长区块证据。',
'S10':'发布正文200ms synchronization/propagation fixes；engine.persistence-threshold 7→70、memory-block-buffer 5→70、backpressure 16→160是软件默认值。',
'S11':'发布正文Gas-Used是每个request中completed eth_call总gas；未包括市场费/融资等，也不是交易receipt。',
'S12':'quoteExactInput L170-185逐腿amountIn=_amountOut，gasEstimate为内部估计；各单腿以revert报价，不证明重用同一池后的组合状态。',
'S13':'L80-83 gasEstimate是total、gasEstimateForL1是其中L1分量，禁止再重复相加。',
'S14':'L78-80 L2 burn→L1 message→dispute window后Outbox释放L1托管token；不是Arbitrum即时ETH。',
'S15':'L10 USDC.e=0xA7D7079b0FEaD91F3e65f86E8915Cb59c1a4C664；L12 USDC=0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E；L15 avUSDC另有地址。',
'S16':'L23-38 aave is_lending=true；底层DAI.e/USDC.e/USDT.e与avDAI/avUSDC/avUSDT分开，精度18/6/6。',
'S17':'L310 withdrawAVAX及L324 redeemAVAX均onlyRole(WITHDRAW_QUEUE_ROLE)；L330-332另查WAVAX流动性。未否定所有正常queue用户出口。',
'S18':'README说明退出受Morpho流动性及withdrawQueue影响；通用协议文档没有绑定Base特定vault。',
'S19':'L604-615 max扣模拟不可提额；L807-827遍历withdrawQueue后不足则NotEnoughLiquidity；L862-873受供借差额与真实loanToken余额限制。',
'S20':'README L35入Gauge换排放时pool fees权利交给Gauge；L39 fees分配voters。',
'S21':'_claimFees调用Pool.claimFees并向feesVotingReward notify；deposit/withdraw与reward另列，不将同一费用重复归给存款人。',
'S22':'L137-148 mint更新mintedVAI债务；L225-245 repay烧VAI本金并transferFrom VAI利息；卖出余额不是无负债利润。',
'S23':'L274 pool.burn后L282-299增加tokensOwed；collect另调用pool.collect，burn NFT须liquidity及tokensOwed清零。',
'S24':'L33-60 claim已累积供借奖励；L64-85 shortfall可转抵押；L88-119库存不足不转及黑名单约束。',
'S25':'补充独立读取JSON字段：troveManager=0xA39739EF8b0231DbFA0DcdA07d7e29faAbCf4bb2，lusdToken=0x5f98805A4E8be255a32880FDeC7F6728C6568bA0。',
'S26':'L948-953需maxFee/bootstrap/TCR/正数/LUSD余额；未要求赎回人有Trove；L1014-1022发送扣费后的ETH；L1387-1405动态赎回费。',
'S27':'ERC4626 previewRedeem L440明确忽略maxRedeem等redemption limits；view报价不等于账户额度/执行成功。',
'S28':'固定部署commit：maxRedeem=owner balance；previewRedeem=convertToAssets；_burn查余额/授权并pot.exit/daiJoin.exit。',
'S29':'L258-282 actualDebtToLiquidate有条件上限；L390 receiveAToken分支；L595-624按奖金部分扣协议费。未证明任何当前仓位。',
'S30':'L109 onlyMinters；L363-377 burn受pause/minter/blacklist约束，减少余额和supply，不含现金支付逻辑。',
'S31':'L345 swap查factory.isPaused；L447-450 getAmountOut查reserve/fee但不查pause，不能用view证明swap权限。',
'S32':'validateLiquidationCall检查reserve active/pause、HF、grace、抵押启用及债务；仍须与本链当前部署绑定。',
'S33':'L161 USDCe=0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174；L542 USDCn=0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359，各自aToken不同。',
'S34':'supportMarket L1095-1096限poolRegistry；preBorrowHook需listed、oracle非零、caps和流动性检查。检查存在不证明全部资产安全。',
'S35':'getUnderlyingPrice映射underlying；setTokenConfig由AccessControlManager授权并有pause/配置检查。没有读取当前feed值。',
'S36':'Polygon V2 exchange=0xE111180000d2663C0091e4f400237545B87B996B，CollateralToken proxy=0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB；L113-116 PMCT是USDC/USDCe ERC20 wrapper，CTF adapter独立。',
'S37':'reportPayouts绑定oracle与condition；redeemPositions L218-254须den>0、按payout vector与position余额烧份额；root collateral与parent position两种产出不同。',
'S38':'README L9/L11 Mainnet与Devnet同KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD，单ID不证明cluster。',
'S39':'L30 declare_id同README，只是源声明，未读取实际ProgramData。',
'S40':'Aave Sonic登记stS=0xE5DA20F15420aD15DE0fa650600aFc998bbE3955、USDC=0x29219dd400f2Bf60E5a23d13Be72B486D4038894、wS不同。',
'S41':'README L110烧stS、L114-118 pool与validator都走withdraw；L46 admin可改delay，文档two weeks不能当现行固定等待。',
'S42':'executeBorrow mint指数债务并发底层；executeRepay按当前userDebt，L211转params.asset，aToken分支需对应资产/自身偿债等条件。',
'S43':'V1 README L1-5明确archived和addresses updated，指向V2；没有声称旧合约在链上销毁或已停用。',
'S44':'L125-134 request需resumed和金额边界；L218-230未finalized/已claimed可领取为0；claim需owner且finalized。',
'S45':'L69-74 unwrap按getPooledEthByShares返回stETH，不是ETH。',
'S46':'README指部署commit 665879762f8b5df5d234463f45d1d6a49bd4fbeb及Mainnet sDAI地址。',
'S47':'CollateralToken L111-124 name=Polymarket USD，symbol=pUSD，decimals=6；USDC/USDCE/VAULT独立immutable；wrap/unwrap需WRAPPER_ROLE，mint/burn另需MINTER_ROLE。',
'S48':'CollateralOfframp L50-58公开unwrap先onlyUnpaused(asset)，从调用者转入抵押token再经token角色接口unwrap；角色限制不能推成普通用户无任何出口。',
}

# scope, verdict, sources, independently stated reason, concrete missing fields, next action
specs=[
('stETH/wstETH→Lido请求→unstETH→finalize→ETH领取；静态退出状态可核，当前数量和经济闭环未核','NEEDS_DATA',['S01','S02','S44','S45'],'份额转换、请求NFT与最终ETH是同一权益的阶段。主网部署表一致，但无当前代理/队列状态或买入报价，不能确认即时现金或收益。',['chainId/区块/当前proxy implementation','DEX真实池和数量q→买入输出','shares rate、paused、requestId/owner/finalized/claimed/claimable','完整取得→请求→领取→出售路线、gas/授权/等待/容量'], '先绑定主网实现；同状态分数量测现货和queue，记录requestId并与ETH05共用权益账本。'),
('仅确认BSC v1.8.2公告中Jenner与CAS20的计划时间/治理激活条件；不确认当前生效或参与收益','CONFIRMED_EVIDENCE',['S03'],'公告写明未来硬分叉和CAS20另行激活，本轮日期早于计划日期。非共识改动可能更早生效，应逐项区分。',['实际链上fork激活/治理任命/管理员activation','普通账户资格/成本/退出市场（若提出经济候选）'],'到计划时刻前后读chain配置和治理/管理员生效证据；不据未来计划创建当前铸造机会。'),
('仅确认Orca源码mint-owner/Token Program约束；不确认新规则、当前部署或具体池可交易','CONFIRMED_EVIDENCE',['S04'],'源码确实将token_program绑定mint.owner并验证supported mint；无真实mint和pool，规则源事实可通过，市场身份仍未知。',['genesis/finalized slot、ProgramData及升级版本','pool/mint owner、Token/Token2022扩展与真实余额','数量路线/当前报价/完整费用（若提交经济主张）'],'先绑定当前程序版本，再在具体已登记池检查mint owner与转账扩展。'),
('排除仅凭lisUSD锚定/借款人还债文档推出公众无条件1美元现金赎回；不判定所有新模块不存在','REJECTED',['S05','S06','S07'],'文本的购买主体是借款人、用途是减债并取回自有抵押；推不出任意持有人取得额外现金的权利。',['当前部署/新PSM或公开兑换模块','普通持有人资格/额度/接收资产','真实买入→兑付→退出数量及gas/等待'],'先查当前部署及新增模块；存在明确公众出口后再建立经济路线。'),
('仅确认Base节点官方研究源迁移及v1.5.4发布描述；不确认停链或链运行状态','CONFIRMED_EVIDENCE',['S08','S09','S10'],'旧README直接给新维护源，新仓承接节点，停链推断无依据。发布默认值不能替代当前链配置/增长区块。',['当前eth_chainId/最新区块及连续增长/最终性','运行版本和实际链参数（若要判断节点现状）'],'采用base/base固定版本作源；恢复RPC后独立核运行情况。'),
('排除C-Chain Gas-Used响应头等于完整交易经济成本','REJECTED',['S11'],'头字段只计已完成eth_call的gas，既不是支付的gas价格乘数量，也未含所有交易腿/市场/融资费用。',['节点版本和实际响应头','完整路线交易估算/receipt、gasPrice、DEX/税/融资费'],'按完整交易与经济账本核费；已含费项不再重复扣。'),
('排除三腿独立单价或同输入拼三角收益；源码数量传递规则核查，不含实际Arbitrum路线','REJECTED',['S12','S13'],'上一输出成为下一输入；Quoter内部gas不等于整笔成本，NodeInterface total内含L1分量。重复池仍须真实状态顺序模拟。',['三个不同资产/三个真实池和正确Quoter部署ABI','q及各腿实际输入输出、同块状态更新','完整交易/融资偿还和L1/L2费用'],'建立真实A→B→C→A并按序模拟；不要total外再加其L1分量。'),
('排除指定Lido canonical gateway退出等于Arbitrum本链即时ETH','REJECTED',['S14'],'出口是L2烧token后经消息和争议窗口在L1释放托管token；资产、链和时间均不同于主张。',['实际gateway/token映射与代码/暂停','当前争议/确认窗口、两侧q报价/桥费'],'若具体路径跨L1，交X-ARB；另行验证任何本链即时出口。'),
('排除Avalanche原生USDC、USDC.e与avUSDC合并为同资产或同1美元现金节点','REJECTED',['S15','S16'],'官方配置给不同地址与wrapped/underlying；没有转换和兑付证据就不能消去这条权益转换边。',['发行方/桥映射和当前代码','包装汇率/余额/兑换权限','真实循环池、q/顺序状态报价与完整成本'],'分别建资产节点，明确每条转换边后同状态测完整回路。'),
('仅排除ggAVAX两个已读AVAX方法可由任意普通账户无条件直接调用；不否定queue正常用户出口','REJECTED',['S17'],'两方法明确queue role，redeem另检查WAVAX现金。preview不能越过角色和资金条件；不套用sAVAX。',['当前ggAVAX部署/实现','withdrawQueue部署、普通用户入口/资格/容量','q报价、预览/实际产出、等待和费用'],'沿已授权正常queue用户入口核查，并独立处理sAVAX。'),
('排除MetaMorpho totalAssets/份额换算保证Base即时赎回折价利润','REJECTED',['S18','S19'],'流动性模拟与withdrawQueue限制真实退出，缺Base目标也缺二级市场成本。不能将此源码套给Aave STATA。',['Base vault/implementation/asset与二级池','q买入、NAV、maxWithdraw/maxRedeem、真实可提数','完整退出费/gas、等待及亏损历史'],'先确定Base具体vault和二级池，再比较四列，不混用不同实现。'),
('排除Aerodrome同账户同时拥有Gauge排放和同期间全部LP费用的双计','REJECTED',['S20','S21'],'LP转给Gauge改变手续费归属，feesVotingReward分给投票权益。可能同时持不同身份不构成把相同费用重复列入。',['实际Pool/Gauge/feesVotingReward与当前部署','账户LP/Gauge/veNFT权益、accrued和已到账','q完整存取/必要兑换、gas与费'],'按账户和权利逐项分账，证明每份费用只分配一次。'),
('排除VAI铸造卖出金额为无负债利润或可用任意面值稳定币还款','REJECTED',['S22'],'mint同时记债，repay用VAI烧本金并支付VAI利息；须回购债务资产并释放抵押才闭环。',['VAI/Controller当前实现、资格/上限/费率','q卖出与VAI回购报价','本金利息、抵押取回、gas/授权成本'],'测完整mint→sell→buy VAI→repay→collateral exit账本。'),
('排除PancakeV3 decreaseLiquidity返回值等于实际到账自由资产','REJECTED',['S23'],'pool.burn结果先入tokensOwed，collect才从池收取；NFT销毁还要求余量清零。',['真实position tokenId/授权、Pool与token身份','q流动性/tick/前中后余额、实际collect','完整退出/兑换费用及剩余NFT/应收'],'将liquidity、tokensOwed和已收款分别核，完整模拟确认最终余量。'),
('排除Venus公开claim意味着所有新地址零成本取得立即可售XVS','REJECTED',['S24'],'奖励取决于累积供借权益/资金，shortfall可变抵押头寸；公开函数不创造accrued奖励。',['当前diamond facet/XVS部署','普通账户accrued/shortfall/blacklist、库存','参与成本、claim数量/DEX实际售出/gas'],'指定正常账户只读核资格和余额，计参与与退出成本。'),
('Liquity v1持LUSD赎回ETH；静态持有人权限与输出规则可核，当前经济候选未核','NEEDS_DATA',['S25','S26'],'持币赎回不同于赎回自己Trove；源码可向持币人发送扣费ETH，但当下TCR/可赎债务/fee/hints和二级成交均未知。',['chainId/block与TroveManager当前代码/版本','q LUSD买入→实际可赎ETH→ETH出售数量路线','TCR、可赎债务、baseRate/fee、hints与partial completion','gas/授权/冲击/容量和最终余额'], '绑定v1部署后同状态测普通持币人路径，实际成功赎回量与未赎LUSD分别记。'),
('排除sDAI NAV/previewRedeem是用户提款额度或执行成功保证','REJECTED',['S27','S28','S46'],'标准明确preview忽略限额；指定部署源码还需余额/授权及Pot/DAIJoin实际执行。该源码没异步队列，不据此臆造排队。',['当前sDAI代码/Pot状态/chi/rho和用户余额授权','真实二级池/q买入、max/preview/完整redeem','DAI可卖数量与gas/费用'],'先有真实二级流动性，再同状态测试账户可执行退出。'),
('排除Ethereum Aave oracle×清算奖励为已实现净利；不裁决任何真实仓位','REJECTED',['S29'],'实际代还上限、aToken/底层分支和协议费会改变资产账本，且抵押仍要卖出或取出。',['当前Pool实现/borrower/block/HF/债务','q实际代还、所得抵押与卖出/提款报价','融资本息、gas/协议费、最终零负债余额'],'先找到真实合规仓位，只读完整路径核实，不用名义奖金记利润。'),
('排除USDC存在burn即任意OP持币人可链上按1美元拿现金','REJECTED',['S30'],'参考burn只是权限销毁余额/供给，没有付款；当前部署及现金渠道仍未知，不能据此否定合格客户发行方退出。',['OP USDC当前代理实现/原生桥接身份','发行方账户/地区/额度/实际接收资产与到账','q买入→真实兑付→退出报价和完整费'],'核实际发行方出口和普通合格账户条件；burn与现金分开。'),
('仅排除Velodrome getAmountOut有值就证明同状态swap权限','REJECTED',['S31'],'swap另查factory.isPaused，而view不查；未证明实际OP池处于暂停。',['真实Pool/Factory当前代码、pause与资产身份','q两腿同状态报价/组合执行','完整L1/L2/池费/转账限制'],'在真实池同时检查当前权限与数量报价，再测双DEX路线。'),
('排除Polygon Aave预言机奖金估值为可兑现净利；不认定任何仓位可清算','REJECTED',['S29','S32'],'正常清算需当前资格并支付实际代还，抵押权利/协议费/现金退出与融资分账；与Ethereum同源码不代表相同链上仓位。',['Polygon当前实现/reserve配置、borrower/block/HF','q实际代还→抵押/aToken→可卖/可提→融资归还','全费用/本金利息/最终自由资产'],'逐Polygon仓位同状态核验证据，不能套旧close factor或跨链仓位。'),
('排除Polygon USDCe与USDCn按名称/精度/oracle相同当同token双DEX闭环','REJECTED',['S33'],'两个underlying地址不同且aToken分开，必须显式计转换规则；不裁决其当前价格或正常转换收益。',['发行方/桥映射与链上token代码','两个真实池/资产方向和独立底层','q转换→第二腿实际输出、完整费用'],'按合约地址建图，保留原生/桥接转换边后报价。'),
('排除任意自建ERC20/币名TEST或DAI能直接在Venus抵押并无负债获利','REJECTED',['S34','S35'],'上市由registry控制，借款还需oracle/cap/liquidity；名称不能证明资产价值，检查存在也不能证明所有已上市资产无风险。',['当前PoolRegistry/Comptroller/vToken列表与实现','具体资产发行/桥/真实退出、oracle精度/时效','实际抵押/债务敞口/回收价值和时间范围'],'只读核真实注册资产与敞口；有异常才给RISK_ONLY，不制作利用路径。'),
('排除CTF或CollateralToken名称证明输方结果份额被借贷市场接受并可获利；同时复核V1→V2/PMCT权益','REJECTED',['S43','S36','S47','S48','S37','S33'],'V1已提示迁移但未证明链上退役；PMCT现金包装层源码名为pUSD，与condition结果份额分开。token角色限制经公开Offramp可衔接，不能又误判为所有普通人都无出口。无实际借贷接受映射，不能确认风险/收益。',['V2/旧V1当前代码、代理实现及迁移生效时间','USDC/USDCE/VAULT、Offramp角色/allowance/余额/pause','condition/position/payout最终性→结果wrapper→真实lending market→oracle映射','当前抵押/未偿本息/可回收价值；任何经济路线q/退出报价/完整成本'],'先核Polygon实际部署与正常offramp，再建立具体事件/借贷映射；PMCT/pUSD不替代outcome。'),
('排除KLend program ID单独证明mainnet-beta或可清算仓位','REJECTED',['S38','S39'],'官方Mainnet/Devnet可使用同程序ID，集群需genesis和slot证明；lib declare_id不是program binary或仓位。',['getGenesisHash/finalized slot/commitment','program owner/executable/ProgramData','market/reserve/obligation/mint/当前清算资格','q正常清算/退出报价及优先费/租金/融资'],'先确集群和版本，再核具体账户；不套EVM HF/地址口径。'),
('Sonic stS→S正常退出；静态份额与两步提款可核，当前数量/等待/价差未核','NEEDS_DATA',['S40','S41'],'两个静态源指向同stS；两条undelegate路径共用withdraw，admin可改等待。无当前rate/可提款额/DEX报价，文档两周不是实测。',['chainId146/block、stS当前proxy implementation','q DEX买入→按rate burn→withdraw→S可卖数量','current delay/pause/validator选择/withdrawal资金/罚没状态','退出费用、gas、等待成本与容量'],'绑定Sonic部署后分现货/即时/异步三出口测数量；有真实等待再给盈亏平衡成本。'),
('排除Sonic Aave借出卖出USDC余额为收入或任意面值稳定币可偿债','REJECTED',['S40','S42'],'借出同时铸指数债务；偿还用该reserve的asset或合规则对应aToken。回购本息与抵押退出缺一都不是自由利润。',['当前Sonic Pool实现、asset原生/桥接身份、借款资格/额度','q借出→卖出→取得债务资产→本息偿清→抵押取回','债务指数/利息与全程报价/gas/融资/剩债'],'完整同状态只读路径核账；本金只扣一次，最终债务清零须有余额证据。'),
]
assert len(specs)==len(items)==27
reviews=[]
for item,spec in zip(items,specs):
    scope,verdict,ids,reason,missing,nxt=spec
    checked=[]
    for sid in ids:
        s=byid[sid]
        checked.append({'source_id':sid,'url':s['url'],'fetched_at':s['fetched_at'],'http_status':s['http_status'],'sha256':s['sha256'],'fields_and_result':fields[sid]})
    reviews.append({'finding_id':item['finding_id'],'claim_scope':scope,'verdict':verdict,'recommended_status':'REJECTED' if verdict=='REJECTED' else 'UNVERIFIED','independently_checked_at':now,'independently_checked_sources':checked,'missing_fields':missing,'reasoning_summary':reason+' 本裁决不确认当前收益、30天完整规则或7天活动覆盖。','duplicate_of':None,'next_check':nxt})
write(OUT/'reviews.json',{'reviews':reviews})

corrections=[
 {'target':'N-POLY旧CTF入口；R-POLY纠错','kind':'SOURCE_AND_RIGHTS','result':'CONFIRMED_EVIDENCE','evidence':['S43','S36','S37'],'recommendation':'旧V1标LEGACY_SOURCE_REVALIDATION_REQUIRED，补V2官方入口；不宣称V1链上退役。PMCT现金层与CTF outcome分开，不能自动映射借贷抵押。'},
 {'target':'M00/N-BASE旧源迁移处理','kind':'SOURCE_MIGRATION','result':'CONFIRMED_EVIDENCE','evidence':['S08','S09','S10'],'recommendation':'采用base/base；保留链存活UNKNOWN，旧目录缺席/404/归档不得写停链。'},
 {'target':'N-ETH/ETH01/ETH05','kind':'DUPLICATE_RIGHTS','result':'CONFIRMED_EVIDENCE','evidence':['S01','S02','S44','S45'],'recommendation':'三岗queue地址相同，N-ETH与ETH01同一finding；ETH05 unstETH是同queue请求NFT。一个requestId只记一次取得成本/领取额；若独立买NFT，只对该件另核成本，不把底层stETH与NFT同时估为自由资产。'},
 {'target':'R-POLY/PMCT命名与权限补充','kind':'IDENTITY_AND_PERMISSION','result':'CONFIRMED_EVIDENCE','evidence':['S47','S48'],'recommendation':'README称PMCT，所读源码name=Polymarket USD/symbol=pUSD/6 decimals。token.unwrap受role但公开Offramp可衔接；普通用户当前出口取决于offramp绑定/角色/asset暂停/VAULT余额allowance。不是无条件法币现金。'},
 {'target':'N-BNB报告北京时间行','kind':'METADATA','result':'CORRECTION_REQUIRED','evidence':['reports/agents/N-BNB/2026-11-08/'+run+'.md'],'recommendation':'正文23:24:45.675031+00:00标为北京时间却保留UTC偏移，应改+08:00（绝对UTC时刻15:24:45.675031+00:00）。Q00不改原作者报告。'},
 {'target':'BNB04源失败尝试','kind':'PROCEDURE','result':'CORRECTION_REQUIRED','evidence':['evidence/BNB04/'+run+'/record.json'],'recommendation':'记录5个V2猜测路径404，超过同服务3次连续失败后停止的有界要求。后续最多3次失败即转已知官方入口；404不代表协议无市场。'}
]
write(OUT/'corrections.json',{'corrections':corrections,'material_evidence_corrections':4,'metadata_corrections':1,'procedure_corrections':1})

registered_by_owner=collections.defaultdict(list)
for it,rv in zip(items,reviews):registered_by_owner[it['owner']].extend(s['source_id'] for s in rv['independently_checked_sources'])
registered_by_owner['ETH01']=['S01','S02','S44','S45'];registered_by_owner['ETH05']=['S01','S02','S44'];registered_by_owner['X-ARB']=['S14'];registered_by_owner['X-BASE']=['S08','S09']
extra=[]
for row in audit['records']:
    row['q00_scope_assessment']='未见把跨链/其他协议模板当已确认本岗经济机会；通用源码与目标部署对应仍待核。'
    row['q00_current_quote_assessment']='本轮quotes为空，无法检查报价过60秒；静态源抓取时间不作为市场价时效。'
    row['q00_duplicate_assessment']='按链+地址+权益+路径去重；同源码不同链不合并收益。'
    if row['agent_id'] in ['N-ETH','ETH01','ETH05']:row['q00_duplicate_assessment']='共用ETH-LIDO-STETH-WITHDRAWAL-QUEUE-EXIT；ETH05是相同queue的NFT层，按requestId避免重复计权利。'
    if row['agent_id']=='BNB04':row['q00_scope_assessment']+='另见corrections.json程序性失败次数建议。'
    for n,rejection in enumerate(row['rejections']):
        extra.append({'agent_id':row['agent_id'],'rejection_index':n,'original_rejection':rejection,'audit_result':'LIMITED_REJECTION_SUPPORTED_OR_KEEP_UNVERIFIED','review_basis':'核对原报告限定范围和缺字段；会计恒等式/无证据不升级原则可支持退回推断，但不证明所有市场不存在或无风险。','related_independent_sources':sorted(set(registered_by_owner[row['agent_id']])),'source_matching_limit':'source IDs仅列本角色相关独立复读；本条未逐一绑定的其他部署/市场没有独立链核验。'})
write(OUT/'input-audit.json',audit)
write(OUT/'additional-rejections.json',{'records_read':46,'rejections_read_and_scope_checked':len(extra),'items':extra,'current_identity_or_economic_independent_verification_complete':False})

counts=dict(collections.Counter(r['verdict'] for r in reviews))
for v in ['CONFIRMED_EVIDENCE','NEEDS_DATA','STALE','REJECTED','RISK_ONLY']:counts.setdefault(v,0)
started=sources['started_at']
duration=(datetime.datetime.fromisoformat(now)-datetime.datetime.fromisoformat(started)).total_seconds()
record={
 'agent_id':'Q00','run_id':run,'chain':'CONTROL','scope':'独立复核本run已提交46研究岗位报告、102项rejections和registry全部27稳定finding；不做新市场发现。',
 'started_at':started,'finished_at':now,'duration_seconds':round(duration,3),'timing_scope':'独立取数至复核文件生成；前置契约/原报告阅读准备未计入，此为可复现数据阶段耗时。',
 'execution_status':'PARTIAL','status':'UNVERIFIED','as_of':{'utc':now,'beijing':datetime.datetime.fromisoformat(now).astimezone(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),'data_time':'各官方源fetched_at；当前链状态未取得'},
 'block_or_slot':None,'market_ids':[],'asset_ids':[],'discovery_source':[s['url'] for s in sources['sources']],
 'mechanism':'按身份→权限→数量→会计→成本→真实性→机制复核已提交主张，静态规则确认与当前经济闭环分开。',
 'observations':[{'review_counts':counts,'registry_coverage':'27/27 exactly once','research_records_read':46,'rejections_read':len(extra),'original_correction_arrays_read':1,'original_execution_statuses':{'PARTIAL':46},'original_quote_count':0,'independent_official_unique_urls':48,'independent_official_http_requests':50,'independent_http_200':49,'supplemental_successful_deployment_JSON_read_without_saved_HTTP_status':1,'independent_rpc_probes':5,'independent_rpc_CONNECT_403':5},'N-POLY旧源/V2现金包装层、Base迁移、Lido NFT同权益去重独立复核完成；另补pUSD命名与Offramp角色衔接。'],
 'quotes':[],'net_result':{'amount':None,'unit':'unpriced; assets not summed across chains','realized':False,'realized_profit_confirmed':False,'unrealized_profit_confirmed':False,'unknown_costs':['每项missing_fields列出的完整买卖/兑换/税费/冲击','授权/账户初始化/部署(如需)/gas及优先费','融资本金利息/退出/等待/跨链/失败费用'],'note':'本轮无交易或历史闭环样本，不能把未发生交易记为已实现盈利0或正数。'},
 'capacity':'unknown；没有当前q与完整路线或可兑额度','permissions':'静态代码限制已列；所有本轮真实部署/角色/普通账户当前资格未完成','liabilities':'本轮未建仓；VAI/Aave等假设路径中的本金利息/抵押锁定必须保留，未测不填0','waiting_time':'queue/bridge/stS规则存在等待；当前实际时长与可领取金额unknown',
 'invalidation_conditions':['官方分支源码与当前实现不同','源迁移/权限/暂停/资格变化','报价过期或数量/资产身份错误','重复权益/内部转账/负债未计或成本缺漏'],
 'evidence_urls':[s['url'] for s in sources['sources']],
 'coverage_gaps':['首次状态NOT_STARTED，无此前链上成功游标。','30天规则：本轮只重读选定官方源及三个发布页，不是全生态变更/生效完整回溯。','7天活动：未读取任何链上区块/slot、事件、交易与已完成收益样本。','Ethereum/Polygon/Base/Sonic/Solana五个只读身份探针均CONNECT403，保留真实headers与curl错误；BNB/ARB/OP/AVAX本轮未再探测，不能声称已核或可用。','所有27项缺部署/当前身份或具体经济字段见reviews.json；三项经济候选缺q/完整数量路线/当前报价/费用。','额外102排除逐条阅读和范围审查；相关源独立复读不等于102个目标当前部署全部重验。','本轮文件待M00统一合并发布和远端读回；Q00未操作Git或修改全局状态。'],
 'next_check':['按reviews.json逐项补字段，优先恢复只读链身份/实现和具体市场。','先对Lido、Liquity、stS三经济候选读同状态q路线、当前权限/容量与全成本；取得新报价后60秒内重取关键腿再裁决。','按corrections.json统一修订V1/V2、Base源、Lido权益去重与pUSD权限元数据。','保留30天/7天未覆盖标志，不推进完整成功游标。'],
 'handoff_to':['M00'],'markets':[],'findings':[],'rejections':[{'finding_id':r['finding_id'],'scope':r['claim_scope'],'reason':r['reasoning_summary']} for r in reviews if r['verdict']=='REJECTED'],
 'observed_cursor':{'kind':'independent_static_source_reads_and_bounded_failed_RPC_probes','source_fetched_at_start':started,'source_fetched_at_end':sources['finished_at'],'read_record_count':46,'reviewed_finding_ids':[r['finding_id'] for r in reviews],'chain_block_or_slot':None,'full_30_day_window_complete':False,'full_7_day_window_complete':False},
 'review_summary':counts,'research_status':'PARTIAL','storage_status':'PENDING_M00_PUBLICATION_AND_REMOTE_READBACK','schedule_status':'NOT_CONFIGURED','transactions_executed':False,
}
write(OUT/'record.json',record)

lines=[
'# Q00 独立复核：27项全覆盖，当前经济核验仍为PARTIAL',
'',
'已复核本轮46份原报告与记录、102项排除和1组原作者纠错；registry的27个稳定finding_id在reviews.json各出现一次。独立重读48个官方URL（48个URL的HTTP200证据，另有Liquity字段补读和精选片段恢复重读各一次），另有5次RPC身份请求均真实CONNECT 403。本轮无交易、报价、模拟或可确认的已实现盈利。',
'',
'裁决：CONFIRMED_EVIDENCE 3（只确认静态源码/公告/来源事实）；NEEDS_DATA 3；REJECTED 21（限定错误推断，不是认定相应市场没有机会）；STALE 0；RISK_ONLY 0。退回补数据3，退回错误推断21。4项实质纠错建议，另有1项时间格式、1项失败次数流程建议。没有当前报价，因此无可按60秒规则判过期的报价；旧V1入口须重核，未据源码归档断言链上退役。',
'',
'静态通过的是BSC公告计划与治理条件、Orca源码mint-owner规则、Base官方源迁移。三项经济候选Lido、Liquity v1和Sonic stS均NEEDS_DATA：缺当前部署/链身份、指定数量q、完整路线各腿、当前可成交报价、全部费用与容量。Lido还缺具体requestId和队列状态，Liquity缺TCR/动态费/hints/可赎债务，stS缺rate/现行delay/pause/提款资金。不能把静态通过计作收益通过。',
'',
'## 独立证据与具体纠错',
'',
'1. **Polymarket V1→V2与PMCT**：V1 README明确archived、addresses updated并指向V2；V2 Polygon交易所为0xE111180000d2663C0091e4f400237545B87B996B，CollateralToken proxy为0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB。它们仍是静态部署表，旧V1当前运行/迁移生效未知。CTF结果份额按condition payout结算，PMCT包USDC/USDC.e，两层不能合并，更不能自动映射借贷抵押。',
'2. **新增命名和权限补充**：本轮直接读取CollateralToken.sol，name=Polymarket USD、symbol=pUSD、6位；README的PMCT是机制称呼。token.unwrap受WRAPPER_ROLE，但公开CollateralOfframp.unwrap通过角色合约提供正常接口并检查asset暂停；不能又推成普通账户无任何出口。当前角色、VAULT余额/allowance和暂停未查链，不承诺兑付或法币现金。',
'3. **Base源迁移**：旧base-org/node README明说迁到base/base，新仓承接旧节点；v1.5.4描述200ms同步修复和engine默认值调整。认可M00按迁移处理；旧目录缺席/404/旧仓归档不证明停链，也不能反向证明链现已存活。',
'4. **Lido去重**：N-ETH与ETH01已共用同finding；ETH05的unstETH仍属同一0x889e…队列。源码NFT request铸、claim烧，transfer仅换owner且不重置claimed。按requestId记录一次取得成本及领取额；未领取NFT、底层stETH和预计ETH不能同时加总为三份资产。同源码跨链的Aave清算方法则不等于同一经济仓位，ETH与POLY不合并成一条收益。',
'5. **元数据与执行纪律**：N-BNB报告把北京时间23:24行写成+00:00，应为+08:00；保留原UTC时刻。BNB04记录同raw服务5个V2猜测路径404，后续应在3次连续失败后转已知入口。Q00未改原报告。',
'',
'## 身份、权限、数量、会计与成本',
'',
'身份只确认源中的地址和权益边界，未完成当前链code/代理实现或Solana ProgramData核验。已重新检查mint owner、queue role、public holder redemption、pause、minter、listed/oracle、Gauge费用归属等具体约束；不能用权限检查存在证明所有市场永久安全。',
'',
'数量与真实性：46份原始record的quotes总数为0，execution_status全部PARTIAL；本轮亦无数量报价或模拟。工厂、程序、SDK地址不替代真实池/仓位；单腿输出不当闭环。Quoter逐腿使用上腿输出，但重复池必须体现前腿状态变化。未读的block/slot填null，未知价格/费用不填0。',
'',
'成本：买卖费/冲击/税、授权/账户初始化/部署（如需要）、完整gas/L1数据费/优先费、融资、桥和退出/失败/等待成本仍未知；每项missing_fields具体列明。NodeInterface total已含L1分量，不重复加；Gas-Used响应头不是完整经济成本；借款本金只在统一资产负债表计一次。',
'',
'| 分类 | 本轮可确认范围 | 待核内容 |',
'| --- | --- | --- |',
'| 已实现 | 无交易或已完成闭环样本，无法确认盈利 | 真实前后余额、外部注资、本金、费用与债务闭合 |',
'| 未实现 | 未领取NFT/份额/抵押权利不记现金；无可计价当前持仓 | owner、实际可领、可卖买单、取得成本 |',
'| 负债 | VAI与Aave借款必须同步记本金利息；本轮未建仓 | 当前债务指数/回购/全偿/抵押释放 |',
'| 等待 | Lido请求、L1桥退出、stS有静态异步条件 | 当前延迟/暂停/资金/最终性/到账数量 |',
'',
'## 额外排除、范围与历史覆盖',
'',
'102项rejections已逐条读取并检查限定范围，详见additional-rejections.json。没有把无数据推广为全链无市场；工厂/程序不是池，LP/NFT不是额外收益，burn不等于现金，aToken不等于底层可支配余额，oracle奖金不等于售出利润，source TODO不是已生效规则。部分额外项只完成会计/范围审查，并未逐项重验其对应部署；文件明确区分这些层级。未发现岗位将跨链退出冒充本链即时已报价收益的实质越界。',
'',
'首次Q00状态NOT_STARTED、无成功历史游标。30天规则仅重读选定源码及三个发布页，没有全窗口diff/治理/生效事件；7天活动未读任何事件/交易/历史状态。当前Ethereum、Polygon、Base、Sonic、Solana身份请求各一次CONNECT403（真实响应在independent-probes.json），BNB/ARB/OP/AVAX未再次探测。两窗口及全部实时身份/数量经济缺口保持PARTIAL，不推进完整成功游标。源码分支快照以响应SHA256保留，未冒充固定部署commit（sDAI明确指定commit除外，当前部署对应仍待核）。',
'',
'下一步优先恢复只读身份与实现读取，再按reviews.json补Lido/Liquity/stS的数量路线与全成本；有当前报价时最终重取关键腿，并逐项补30天规则与7天活动。有新部署/角色/状态证据后对同finding追加复核，不每天重复造机会。',
'',
'## 逐项裁决索引',
'',
'| finding_id | 裁决 | 推荐研究等级 |',
'| --- | --- | --- |',
]
lines += ['| '+r['finding_id']+' | '+r['verdict']+' | '+r['recommended_status']+' |' for r in reviews]
lines += ['', '完整逐项来源、字段、缺口、下一次动作见evidence/Q00/'+run+'/reviews.json；全记录record.json；输入哈希与审查input-audit.json；独立源码精选independent-sources.json；额外排除additional-rejections.json；纠错corrections.json。', '',f'数据阶段UTC {started} 至 {now}，耗时{duration:.3f}秒；前置阅读准备未计入。北京时间结束{record["as_of"]["beijing"]}。研究PARTIAL；存储PENDING_M00_PUBLICATION_AND_REMOTE_READBACK；定时NOT_CONFIGURED。仅写Q00自己的报告/证据，无Git操作、全局状态修改、交易或定时创建。']
(ROOT/'reports/agents/Q00/2026-11-08'/f'{run}.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({'review_counts':counts,'duration_seconds':duration,'records':len(audit['records']),'rejections':len(extra)},ensure_ascii=False))
