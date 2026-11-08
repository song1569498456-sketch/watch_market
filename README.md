# watch_market

云端链上机会研究项目：48 个岗位（1 个主控、47 个子岗位），自主发现市场、检查规则差异并记录证据。

## 当前状态

- 正式提示词与研究规则已准备发布；全部岗位已启用但**尚未执行研究**。
- 历史研究进度正确初始化为空；访问测试、前置核验不计为研究。
- 未创建定时任务，不进行链上交易。
- 本仓库的正式记录分支为 `setup/access-check-20261108T150555Z`。请勿假定存在 main。

## 继续云端会话

读取 [续跑指令](prompts/launch/04-resume-cloud.txt)、[M00 提示词](prompts/agents/M00.txt)、[岗位清单](config/agents.json)、[运行配置](config/runtime.json)、[云端记录协议](docs/cloud-recording-protocol.txt)。
由当前云端会话担任主控，分批调用子 agent，不必另建云端任务。每批上限 3 个，候选交 Q00 复核。

## 文件位置

- prompts/agents/：48 份独立任务书。
- config/：启用岗位与运行参数。
- state/：逐岗位进度与研究历史，NOT_STARTED/null 是合法初始值。
- registry/：市场、线索、变化和覆盖缺口。
- reports/、findings/、evidence/、runs/：研究开始后按记录协议生成；此时不制造空的成功日报。
- preflight/：原云端前置阻塞记录，原样保留。

所有正式结果同步到 GitHub 并读回验证。临时工作区不算正式存档。发布只包含研究指令、规则与初始化状态，不包含研究成果或调度成功承诺。
