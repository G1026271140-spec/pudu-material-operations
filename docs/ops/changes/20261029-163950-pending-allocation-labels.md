# 配货台待核实标签、跟进备注与日期分组

## 用户需求及后续确认

2026-10-29：待核实物料申请有些暂时无法判断是否继续流程，需要标签备注；随后明确按申请提交日期分日期展示，并将带自定义标签的申请改为黄色外观。

## 最终行为

- 配货台待核实列表按北京时间的提交日期从新到旧分组，标注每组单数；缺日期保留在最后，不漏单。同日保留原列表顺序。
- 每张申请的“添加 / 编辑标签 / 备注”是独立按钮，不会误入配货或提交核实。标签最多 40 字，跟进备注最多 1000 字，均可清空；不占用申请人原“备注”。
- 只有非空自定义标签使整张卡片显示浅黄色底、黄色边框和标签标记。备注独立展示，移除标签恢复普通外观。
- 仅启用的管理员可编辑，复用现有后端管理员鉴权。保存验证申请仍为普通物料、待审批、未核实库存；不会修改流程状态、库存、明细、审批或发送任何通知。
- 正常写入在 PostgreSQL 同一事务保存字段、审计、幂等结果和本地任务，outbox 再同步飞书；页面立即读取本地结果。每天 03:00 的飞书权威校验沿用现有注册。复用服务器最后提交及记录 / 业务锁，幂等重试不新建任务。

## 字段及迁移

主申请表 tbl3eyt8lkl3uQa1 新增文本字段：待核实标签 / fldx0dDBjm，待核实备注 / fldC20Nrr6。操作前 backup.service 成功（Result=success / ExecMainStatus=0），原注册保存在 shared/audits/pending-followup-registry-before.json。

先以应用身份读取 63 个原字段并校验身份，再只添加 2 个字段；schema owner 只新增对应 text 投影与元数据。生产和隔离测试库均完成注册，未修改业务记录。config/feishu_field_registry.json、frontend_field_contracts.json 和 docs/frontend-field-map.md 保留稳定 ID 和页面字段映射，新字段仅管理员配货台跟进入口。

## 主要文件

material_store/pending_followup.py、pending_followup_schema.py；request_web/pending_followup_api.py / api.py；前端 PendingAllocationList、PendingFollowupDialog、pendingAllocation.ts、pending-followup.css 及 AllocationWorkbench；scripts/ensure_pending_followup_schema.py（默认预览，显式 --apply 才创建或注册）。

## 实际验证

隔离 pudu_materials_test 后端相关 27 passed，前端 31 passed，构建通过。覆盖先本地可读、outbox 仅两个字段、模拟飞书发布、无 effects、不改变原备注和业务字段、清空、幂等、输入 / 版本错误回滚、已核实及文化周边拒绝、严格版本 / 最后提交策略和管理员路由保护。日期含 UTC 跨日 / 非法 / 缺失值，标签和备注安全转义、独立按钮、清空恢复普通颜色均有验证。示例页仅模拟单据，用于黄色卡片视觉验收，未给真实待核实单预设标签，也未向员工发测试通知。

正式发布使用唯一 pudu-release，版本与 Git SHA 以 shared/release-audit.jsonl 及 shared/audits/pending-followup-live-20261029.json 的实际结果为准；生产只读核对字段注册、源表、待核实列表及服务 / 公开健康接口，浏览器核验日期分组和编辑弹窗。原 Windows 服务保持停止，独立线索采集不在范围。


## 发布回归补充

首次正式发布被全量测试阻止：隔离测试库字段映射用例把总数固定为 366，新增两字段后为 368。修正数量并额外断言两个字段均为文本，原逐字段原始 JSON / SQL 类型往返校验、事务回滚、应用角色无 DDL 权限校验全部保留；没有跳过或弱化字段校验。首次失败未推送或切换线上版本。

修正后隔离全量回归：1108 passed、4 skipped、22 subtests passed；前端 31 passed，构建通过。
