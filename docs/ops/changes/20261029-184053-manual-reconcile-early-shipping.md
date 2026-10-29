# 手动飞书全量校验、提前发货及日历物流更新通知

- 北京时间：2026-10-29 18:40 起；操作者 gaohongyuan1，个人 VM 工作区 /srv/pudu-materials-workspaces/gaohongyuan1。
- 基准：V4.1.5 / 948986b4f2faf8bd22acb5b79224461b85ee776d。
- 实现和相关隔离验收通过；正式发布和线上证据以 shared/release-audit.jsonl、shared/audits/manual-sync-live-20261029.json 为准，不预填发布成功。

## 用户需求和最终规则

用户要求虚拟数据库增加手动直接同步校验飞书数据；配货与发货的日历提前提交物流文字或图片后即为已发货、通知申请人，后续审批只通过即可。补充：已发货后更新物流仍要再通知，但这类重复通知仅限日历修改。

复用 03:00 的 23 表 Feishu-authoritative reconciliation。仅管理员确认后入持久队列，独立 inbound 执行，无业务 SQL 事务跨 HTTP；复用工作连接和同一全量校验锁。全量字段及记录读取失败时不应用部分数据。无远端 ID 新建行保留，旧本地冲突留档不重放。幂等重试 / 多管理员同时点击复用活动任务。页面展示阶段、表数、上次结果，后台任务可追溯；不向飞书写任务表 / 通知。

日历提交真实物流使 PG 同事务勾选是否发货，待 outbox 成功后发送申请人卡片，审批未通过也可。待补充 / 示例图不算物流。后续审批不补写两项物流、不重发。日历每次有效提交有版本，已通知后只允许该来源的新提交再次通知，保持只读申请人链接、日期变更卡片、未知发送结果 UUID 和顺序；不重跑审批、扣库或配货。

## 文件和字段

material_store/manual_reconcile.py、reconcile.py、inbound.py、jobs.py、task_monitor.py；request_web/database_api.py、DatabaseReconcile.tsx、DatabaseWorkbench.tsx、database.css。新增 GET/POST /api/admin/database/reconcile，保持 require_admin；无字段 / SQL schema 迁移。

material_store/shipping_calendar.py、auto_shipping.py、effects.py、ShippingCalendarPage.tsx。继续使用物料申请单既有发货单号及文字信息、发货图片、是否发货字段和 ordinary outbox；日历来源 / 版本元数据保存在 material_ops.documents，不增业务表字段。同步 README 和固定规则。

## 实际验证

相关 118 项隔离 PG / 模拟飞书检查通过（manual-sync-tests.log），包括 23 表校验、飞书覆盖旧本地冲突、保留新建行、互斥 / 幂等 / 非管理员拒绝、独立 worker、防止进入业务事务、提前文字 / 图片、审批后不覆盖 / 不重发、日历物流更新再通知、源表更新不重复通知、占位排除、旧卡片 / 未知发送结果与只读权限。前端 TypeScript/Vite 构建通过。正式发布会再执行全部检查；线上通过真实只读 API / 运行态 / 版本回读，不做员工测试通知。

预上线只读快照：shared/audits/manual-sync-before-20261029.json，生产原全量校验已完成 23 表。只有 REQ-20261028-020 为未发货且已有真实物流，存在同版本日历 shipping-batch 持久提交证据、PENDING 原生审批、未通知。上线后按新规则通过标准 save_batch 严格版本校验补齐这一既有日历提交；只补发货状态及申请人通知，不重跑审批 / 扣库。实际结果以 live 回执为准。

## 发布与后续运维

使用唯一 sudo pudu-release，备份、检查在途任务、全量测试和构建、GitLab 推送、切换版本及 10 个服务、公网 / 本地健康回读。应用入口仅增加功能，不自动对生产执行全量手动覆盖；管理员在页面确认后才启动。日校验时间仍是北京时间 03:00。

回退沿正式发布流程，保留数据库、outbox 和 effects；不得重放已完成发货通知。无其他新增人工配置需求。
