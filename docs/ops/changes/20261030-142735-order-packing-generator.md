# order-packing-generator

- 北京时间：2026-10-30T14:27:35+08:00
- 操作人 / Linux 工作区：gaohongyuan1 / /srv/pudu-materials-workspaces/gaohongyuan1
- 聊天与轮次 ID（可取得时）：
- 状态：隔离测试通过；正式发布与生产只读回读结果见 shared/release-audit.jsonl 和 shared/audits/order-packing-live-20261030.json。
- 业务基准版本和 SHA：V4.2.1 / 1477eab32563dc1411815f09fd8407c13aa2f819；承接 20261030-140100 分析记录。

## 用户需求与后续补充

- 用户批准独立选择“本次生成日期”，其他按分析方案；功能名称“下单分装表生成”。
- 批量选择很多张申请单，自动提取全部有效印刷物料进入下单 / 分装两表，不按“需要下单”过滤。
- 额外下单分装选择参考申领页，可加入现有规格和手填自定义物料，与申请单合并到同一 Excel。
- 本轮用户追问上午库存查询入口后已自行说明未刷新应用；保留虚拟数据库库存查询，不重复改写或移除。

## 固定规则与影响

仅管理员，入口物料管理 → 下单分装表生成（/management/order-packing）。独立生成日期用于文件名和历史，不修改原申请日期。既有来源表 / 字段保持不变，无数据库迁移。快照、幂等任务与历史保存在 material_ops.documents / jobs，文件位于共享媒体目录并随现有媒体备份。

本功能是资料导出，保留配货、库存、在途、审批和飞书同步流程，不创建采购批次、发放记录、库存流水或消息 effects。旧发货排期页面仍关闭。参考 docs/ops/02-固定业务规则.md。

## 处理过程和代码

- 新增 material_store/order_packing.py：一次来源投影、稳定物料 ID / 远端别名、印刷定义及有效状态过滤、最新配货数量、指纹核对、跨单汇总及按单分装，额外既有规格 / 自定义校验；幂等 session 锁先于 repeatable-read 快照，随后同事务冻结来源和排入本地任务。两表独立求和核对，数量 / 制作备注保留。
- 新增 order_packing_xlsx.py：使用项目既有获准 openpyxl 依赖生成五列双表，数值数量、分装用途合并、逐行制作备注、续行避免长用途丢失、原文文本防公式执行。只读渲染发现并修正空白分隔行造成后组用途被错误合并清空的问题，回归测试已覆盖所有分装组标签。
- 新增 request_web/order_packing_api.py，所有查询 / 预览 / 生成 / 历史 / 下载路由复核管理员；下载核对 UUID、任务类型、完成状态、文件 SHA256。
- inbound.py 支持新任务，jobs.py 排除此类型，文件生成不进入业务事务；后台任务可见。生成失败明确留档，不反复重放；确认生成按钮重试复用原标识，成功后允许显式再生成新版本。
- OrderPackingPage.tsx / orderPacking.ts / order-packing.css：日期、月历及日期依据、搜索、跨筛选 / 分页选择、一次全选全部筛选结果，每页 30 张；额外品类图片卡片、型号框选、语种 / 数量 / 用途、手填自定义，双表预览及生成历史 / 下载。
- ManagementPage.tsx / Portal.tsx 接入独立页签与 URL；旧页面和上午库存查询保留。README 与固定规则 / 代码导航同步。

## 验证

| 验证对象 | 环境 / 命令 | 实际结果 / 证据位置 |
|---|---|---|
| 集成与边界 | 隔离 pudu_materials_test；test_order_packing / test_manual_reconcile / test_account_tools | 34 passed，包含 150 张申请的真实双表、额外合并、自定义、数量一致、版本冲突、权限、幂等、失败、历史重下载、公式文本和无业务副作用；shared/order-packing-tests.log |
| 前端逻辑 | Node test orderPacking.test.mjs | 3 passed，覆盖 250 张跨日期多选、全选筛选结果、未设日期、保持版本及额外去重；shared/order-packing-frontend-tests.log |
| TypeScript | VM tsc -b | 通过；正式发布再运行完整前端测试 / build |
| 生产来源 | 显式只读 PG 预检 | 91 张符合有效普通物料条件，64 张有可导出印刷明细，8 个印刷品类 / 730 个规格，明细核对警告 0；未创建业务或导出任务 |
| 双表排版 | 合成匿名来源，实际导出器 + Artifact Tool 只读渲染 | 下单表与分装表都检查表头、用途、分组、数量及制作备注；不使用员工或收件信息做测试消息 |
| 发布及线上 | sudo pudu-release，生产只读 API / 版本 / Worker / 页面路由回读 | 真实版本 / SHA / 结果写 shared/release-audit.jsonl 及受限审计回执；不预填未来成功 |

## 提交与上线

代码和本记录同次提交。GitLab 通过统一发布入口上线，随后更新 GitHub 镜像与默认 README。实际发布以回执为准。既有 PUDU Lead Intake Worker 不属于本项目，不修改。

## 遗留事项 / 回退方法

一次最多选择 2000 张申请、添加 2000 条额外物料，总明细最多 50000 条；更大范围须分批。来源缺失 / 多父关联等不明确状态保留核对提示，不能默默丢弃有效印刷明细。历史文件由 PG 快照和共享媒体备份共同保存。回退走统一发布，保留导出历史和业务数据。
