# 修复全量校验等待与 outbox 领取的互相阻塞

- 2026-10-30，gaohongyuan1。基准 V4.1.6 / 613410301ce7079f4428db2e503d03e051a6accf。
- 本轮继续验收手动校验与提前发货，发现 03:00 定时校验超时后数据库等待仍未退出。

## 原因和修复

三个 outbox session guard 已持 reconciliation 共享锁，claim / claim_more 却在另一连接重新申请事务共享锁。当全量校验排队请求独占锁时，新共享申请会等待独占请求，而独占请求又等待 guard，形成跨连接等待环。这是原有领取路径的缺陷，影响定时及手动全量校验，和任务明细数量无关。

outbox_worker.claim 及 line_outbox_batch.claim_more 接受既有 reconciliation_guard；run_once / run_claimed 在 guard 持锁期间跳过跨连接的重复锁申请。没有 guard 的独立调用仍保留事务共享锁。远端写入全程仍受 session 锁保护，无事务跨 HTTP，不取消记录锁、claim token、版本顺序、冲突和幂等校验。

## 恢复与证据

确认原定时 service 已 timeout 且数据库仅停在最初获取独占锁（尚未进入记录注册 / 业务应用），取消这条等待中的 SELECT，未终止业务写事务或重跑业务。shared/audits/reconcile-wait-recovery-20261030.json 保留 PID / 时间 / 取消结果。队列自行恢复，既有 REQ-20261028-020 的严格版本日历补齐得以提交；结果位于 shared/audits/early-calendar-adoption-20261030.json，不重跑审批或扣库。

## 验证

27 项隔离检查通过（shared/reconcile-lock-tests.log），包括真实 PG 多连接复现：在已持 guard 和排队独占校验的情况下，单条 / 10 条批量发布可继续完成，退出后校验获得独占锁；无 guard 领取仍阻止越过全量校验。正式 sudo pudu-release 继续全量检查 / 构建 / 备份 / GitLab / 健康回读；最终版本与真实运行证据以 shared/release-audit.jsonl 和 shared/audits/manual-sync-live-20261029.json 为准。

## 运维

保持每日北京时间 03:00。不可通过禁用校验、绕过锁或重放原申请规避问题；回退仍遵守正式流程并保留 outbox / effects。
