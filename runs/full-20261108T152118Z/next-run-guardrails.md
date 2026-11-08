# 下轮续跑约束

- 读取权威分支和本轮已验证state；PARTIAL游标不表示30天/7天完整回看。
- 数据域名访问缺口见network-access-gaps.json；恢复后重新验证，不把GitHub可达等同于RPC可达。
- 每服务连续3次失败即停止，404也计入；从官方README/部署索引找已知入口，不继续猜路径。BNB04本轮5次404已作为流程偏差保留。
- 北京时间使用UTC时刻的Asia/Shanghai转换（+08:00），不只将小时加8保留+00:00；本轮规范化索引见normalized-report-times.json。
- 同一Lido queue/requestId权益去重；PMCT/pUSD现金wrapper与CTF outcome分开，token角色与公开offramp路径分开，链上绑定和额度仍待查。
- 不重写历史报告；修正追加到同finding、changes和勘误，子agent不改全局状态。
- 本轮没有创建定时任务或交易；新任务不得把拟定时间当成已部署调度。
