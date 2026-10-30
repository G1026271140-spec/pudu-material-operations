# card-admin-contacts-material-identity

- 北京时间：2026-10-30T12:46:41+08:00
- 操作人 / Linux 工作区：gaohongyuan1 / /srv/pudu-materials-workspaces/gaohongyuan1
- 聊天与轮次 ID（可取得时）：
- 状态：隔离验证通过；正式发布及只读终态回执见 shared/release-audit.jsonl 和本次受限审计文件。
- 业务基准版本和 SHA：V4.2.0 / b8e2c75b0243f11b97dc3fa678e878a01d0ef908

## 用户需求与后续补充

- 检查卡片中提及的已启用管理员，权限变更后使用最新名单。
- 用户明确选择：仅新发送和后续业务更新时生效，不批量改写历史卡片。
- 继续处理“冰箱贴 / ET1 / 无需语种”仍提示未找到物料组合的问题，避免靠单条补录掩盖匹配错误。

## 固定规则与影响

见 [固定业务规则](../02-固定业务规则.md)。权限读取本地 PG 用户权限表 tblytA4DHQVbJiIJ，启用角色并集及 open_id 去重。未改变权限、库存、额度数据或数据库 / 飞书 schema，不新增管理员成功卡片；原消息接收人和按钮范围保留。

## 处理过程和代码

- 生产只读核对 MAT-0931 / rec27IsS6khtOz，本地与应用身份读取飞书均为冰箱贴( Fridge Magnet) / ET1 / 无需语种、库存 150，非漏同步。
- 当前页面目录只读审计 1482 个普通物料选项，均能在管理员完整索引中解析。该规格标记 adminOnly；复现最终提交仅识别管理员、未识别已有区域市场经理完整目录权限的问题；旧 feishu_inventory_index 对品类括号空格精确匹配也能复现同一标签格式变化失败。用户截图未附请求日志，不推断其当时身份。
- app.py、request_web/api.py：区域市场经理与管理员的完整目录提交规则对齐；销售仍拒绝隐藏规格，并明确给出权限原因；旧库存查询 / 流水纠正的规格键沿用 request_material_match_key，不改变型号与语种，重复规格明确拒绝。目录 rolesByUser 与 requester_has_enabled_role 也取所有启用权限记录并集，避免后一个销售记录覆盖先前管理员。
- material_store/card_admin_contacts.py：只改系统联系人块，保留其他 @对象、按钮、明细、状态；按实时 PG 启用管理员集渲染。
- material_store/effects.py：每次新发送 / 原卡片更新之前读取最新权限；首次 send 正文持久化，未知结果重试保留 UUID / 正文，取得原 ID 后更新联系人；已确认 ID 后 PATCH 失败只重试原消息，不新发。已完成历史 effects 不扫描或回放。
- tests/test_card_admin_contacts.py、test_material_identity_consistency.py：实际权限变更后的待发送 / 原消息更新、未知结果 + 更新失败重试、重复启用 / 停用、历史不回填、两种完整目录角色的实际本地提交、幂等、隐藏规格销售拒绝与精确规格防错配。

## 验证

| 验证对象 | 环境 / 命令 | 实际结果 / 证据位置 |
|---|---|---|
| 受影响模块 | 隔离 pudu_materials_test、模拟飞书 HTTP；新增测试及 permission_union_refresh / material_activation / account_tools | 59 passed；shared/admin-card-targeted-tests.log |
| 上线验证 | sudo pudu-release | 完整后端 / 前端检查、构建、备份、队列安全、推送及所有运行服务以实际发布回执为准 |
| 生产回读 | 只读全目录一致性、当前启用管理员渲染、MAT-0931 PG / 飞书一致、服务版本 | shared/audits/admin-card-live-20261030.json；无生产权限 / 库存改写，无员工测试消息 |

## 提交与上线

代码及本记录随同提交，正式发布后采集实际版本 / SHA / 线上结果；GitLab、GitHub 代码及默认 README 同步。不预填尚未产生的上线成功。

## 遗留事项 / 回退方法

不批量刷新历史已发卡片、不补发新管理员历史通知；这是用户明确范围。未取得截图对应失败请求的原始载荷，已按可复现的规则差异修复并全目录核对；不重复执行用户申请。回退走正式发布入口，保留业务数据、审计与 outbox。
