# 执行环境记录：live-20261109T141903Z

生成时间：2026-11-09T22:19:03+08:00（UTC 2026-11-09T14:19:03Z）。输入提交 `1785c02b2ee1a98c447ece4a49880b247b05d386`（权威分支 `setup/access-check-20261108T150555Z`）。

## 为什么在本机执行

上一轮 `data-check-20261108T163237Z` 的唯一阻塞是原云端实例的网络策略：49 个数据域名 CONNECT403，平台网络配置写入通道返回 INVALID_ARGUMENT，48 岗实时就绪 0。用户于 2026-11-09 明确指示在本机配置 GitHub 写权限并执行一轮调研。本机不是原云端实例，但只读数据面实测可用；正式记录仍只以 GitHub 权威分支为准，本机磁盘不是正式存档。

## 实际执行环境

| 项 | 值 |
|---|---|
| 执行器 | 用户本机 Windows（DSH 会话），非云端实例 |
| 出网方式 | HTTP 代理 `http://127.0.0.1:7897`（HTTPS 同） |
| 归档写入 | Git Credential Manager OAuth（账号 `song1569498456-sketch`）；本文件所在提交已 push 并 fetch 读回 |
| 仓库可见性 | public（GitHub API 核验，2026-11-09） |
| 定时 | `NOT_CONFIGURED`；本机不是云端调度，不创建本地替代定时，不承诺关机运行 |
| 并发 | 研究子 agent 同时最多 3 个；Q00 独立复核 |

## 只读数据面（2026-11-09 实测）

- 九链 RPC（JSON-RPC 成功）：Ethereum `https://ethereum-rpc.publicnode.com`；Arbitrum One `https://arb1.arbitrum.io/rpc`；Optimism `https://mainnet.optimism.io`；Base `https://mainnet.base.org`；Polygon `https://polygon-bor-rpc.publicnode.com`；BNB Chain `https://bsc-dataseed.bnbchain.org`；Avalanche C-Chain `https://api.avax.network/ext/bc/C/rpc`；Sonic `https://rpc.soniclabs.com`；Solana `https://api.mainnet-beta.solana.com`。
- 不可用/需替换：`eth.llamarpc.com`（HTTP 525）、`polygon-rpc.com`（401 tenant disabled）、`api.etherscan.io`（需 API key，不得使用）。
- 发现类只读 API（无需 key，实测 200）：`api.dexscreener.com`、`api.curve.finance`、`api.beefy.finance`、`gamma-api.polymarket.com`、`api-v3.raydium.io`、`api.orca.so`、`api.kamino.finance`、`api.venus.io`（用 `/markets?chainId=56`）、`api.v3.aave.com`（GraphQL 需按 schema 带 request 参数）。
- 静态来源：`github.com` 与 `raw.githubusercontent.com` 可读（上一轮主要证据来源）。
- 受限：`help.coinbase.com`、`portal.arbitrum.io`（Cloudflare 人机挑战）；`solana.com`（429）；多条旧文档路径 404（host 可达，路径已被上游淘汰，记为源失效而不是网络不可达）；`docs.lista.org` TLS 失败。

## 子 agent 读写约定

- 共享同一工作目录 `D:\ds-arb-test\watch_market`。子 agent 只写自己的 `reports/agents/<id>/2026-11-09/<run_id>.md`、`evidence/<id>/<run_id>/`、`findings/<finding_id>/<run_id>-<id>.json`、`state/agents/<id>.json`；不推送、不修改 `registry/`、`config/`、`runs/manifest.json` 或其他岗位文件。
- 主控 M00 每批合并、普通 push，并 fetch 读回核对后才推进批次状态。
- 联网方法示例（只读）：
  - `curl.exe -sS -m 20 -x http://127.0.0.1:7897 -o out.json -w '%{http_code}' <url>`
  - Python JSON-RPC：`requests.Session()` 设 `sess.trust_env=False; sess.proxies={"http":"http://127.0.0.1:7897","https":"http://127.0.0.1:7897"}`，POST JSON-RPC 到上表 RPC。
- 限速：同一 host 请求间隔 ≥0.3s；单岗位外部请求建议 ≤80 次；同一服务连续 3 次失败即停止并记录缺口，不猜路径、不重试风暴。

## 记录规则提醒

- 报价超过 60 秒只作历史证据；多腿比较优先同一区块/slot；缺报价/费用时 `null`/`unknown`，不填 0。
- 上一轮结论只作基线：任何本轮经济结论必须来自本轮链上读取或本轮抓取的官方源。
- 30 天规则窗口（2026-10-10～2026-11-09）与 7 天活动窗口（2026-11-02～2026-11-09）如未覆盖，必须在 `coverage_gaps` 明确写出，不得声称已覆盖。
