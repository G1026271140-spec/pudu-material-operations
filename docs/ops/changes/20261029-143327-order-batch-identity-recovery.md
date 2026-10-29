# 下单批次编号冲突与原卡片等待恢复

- 北京时间：2026-10-29
- 工作区：gaohongyuan1 / /srv/pudu-materials-workspaces/gaohongyuan1
- 用户需求：后台任务中下单批次明细一直等待“关联记录尚未同步”；补充 REQ-20261029-004 两个原卡片更新一直等待。
- 基准：V4.0.5 / 42818f3ae92bd13a787154a254d5d36fd1986256。

## 根因和影响

自动配货生成键为 allocation:<申请 ID>:<版本>，旧批次号仅截前 10 字符，导致同日均为 PO-20261029-ALLOCATION。首次批次已同步，后续 REQ-20261028-012、REQ-20261029-004 的两张批次因显示编号相同但内容不同发生冲突；7 条批次明细等待批次远端 ID。REQ-20261029-004 两条 update_interactive_message 按既有规则等待相关 outbox 完成，因此未尝试调用飞书卡片更新。

只读完整读取飞书 32 个批次、142 条批次明细，并核对稳定记录 ID 和生成幂等键。源表历史本来存在多组同日同显示编号的独立批次，不能按显示编号合并。受限证据 shared/audits/order-source-audit-20261029.json、order-dependencies-before-20261029.json；原始业务数据不入 Git。

## 变更

order_scheduling.batch_number 对完整生成键取稳定摘要；SchedulingService 调用该函数。outbox 批次创建按生成幂等键查重，明细仍按完整批次明细编号；相同身份但内容不同继续冲突保护。新增 order_recovery 对已核实的旧前缀碰撞提供严格计划 / 原子修复：仅未取得远端 ID 的冲突 create，核对源端无同生成键，旧显示编号被另一生成键占用；修复显示编号、折叠原 create，保留任务 ID / 数量 / 业务键 / 重试历史，写审计及本地修复凭据。不修改已有历史远端批次。

恢复后由原 Worker 发布同一 outbox 并继续原卡片更新，不直接重放业务，不添加替代通知卡片。

## 验证和发布

隔离 PG / 假飞书验证同日前缀碰撞、同键重试、内容冲突保留、恢复总量 / 关联 / 任务 ID 不变、事务回退及原卡片等待后恢复。实际测试 shared/order-identity-tests.log；统一发布 shared/order-identity-release.log、shared/release-audit.jsonl；恢复前后及卡片结果 shared/audits/order-recovery-20261029.json。发布、恢复、回读实际完成前不预填成功。

## 遗留 / 回退

不批量重命名历史已同步批次；非本原因的冲突继续保留。生产恢复不重跑库存或审批；发布回退不撤销已经同步的批次与原卡片更新。


相关隔离回归：76 passed。覆盖同日不同完整键、相同键复用、相同键不同内容保留冲突、恢复后原任务 ID / 关联 / 下单数量保持、源端已存在同键拒绝修复、远端创建成功后进程中断重试不重复建单、两条原卡片依赖等待后仅更新原消息。恢复入口默认预览 `python scripts/repair_order_batch_collisions.py`，核对后加 `--apply`；生产实际恢复结果以受限凭据为准。
