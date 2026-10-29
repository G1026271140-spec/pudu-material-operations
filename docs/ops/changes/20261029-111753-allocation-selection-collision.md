# 配货规格误重复提示修复

- 北京时间：2026-10-29
- 工作区：/srv/pudu-materials-workspaces/gaohongyuan1
- 用户需求：配货台未重复添加却提示“同一物料不能重复添加，请合并数量”。
- 业务基准：V4.0.3 / a8fc32e6fbaca00be8eb41cfac8258e73c134a8f。

## 发现与处理

只读扫描现存申请未发现原始物料 ID 重复；用户截图不含单号和操作步骤，不能断言具体哪次选择触发。代码确认新增默认第一项、改型号强制第一语种，会产生用户未主动重复新增的规格碰撞。

新增默认跳过已选规格；切换型号优先保留语种。选到相同规格时合并数量、去重合并备注，提示核对；不同规格保持独立。整组分装与正常编辑在提交前再次规范草稿，API / Worker 的重复规格校验仍保留。

后端删除条件改为实际未保留的明细 ID，防止两行收敛为同一规格后旧行因其物料仍存在而残留、重复计量。配货变更继续在 PostgreSQL 事务中执行，outbox 后写飞书，原卡片通知、库存、幂等和权限规则不变。没有批量改写任何历史申请。

文件：AllocationWorkbench.tsx、allocationRows.ts、app.py、前后端回归测试、固定业务规则。

## 验证与发布证据

前端覆盖保留语种、新增避重、同规格合并总量 / 备注 / 来源、不同语种不合并、无效数量拒绝；后端模拟飞书覆盖合并时仅删除被替代行。测试在隔离库和模拟飞书执行。

实际测试结果与统一发布版本以 shared/release-audit.jsonl、shared/allocation-selection-tests.log、shared/mute-management-review-release.log、shared/audits/allocation-selection-live-20261029.json 为准；不预填发布成功。原始只读报告 shared/audits/allocation-duplicates-20261029.json 含业务信息，仅受限保存。

发布后用户原页面草稿尚未提交时不会自动恢复；刷新 / 重新打开申请后需复核数量。没有代为提交其配货单。
