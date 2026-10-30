# stock-query-reconcile-wait

- 北京时间：2026-10-30T10:48:01+08:00
- 操作人 / Linux 工作区：gaohongyuan1 / /srv/pudu-materials-workspaces/gaohongyuan1
- 聊天与轮次 ID（可取得时）：
- 状态：隔离验收通过，待正式发布和线上只读验收；实际发布结果见 shared/release-audit.jsonl 及受限验收回执。
- 业务基准版本和 SHA：V4.1.9 / e12dc5eb1319ed7343cbb6ff8fa6e85463a80f5a

## 用户需求与后续补充

1. 检测凌晨飞书多维表格校验失败的原因。
2. 在虚拟数据库新增查询指定物料库存的页面，支持品类、型号、语种、战区检索，能够修改库存并同步飞书。

## 固定规则与影响

遵循 [固定业务规则](../02-固定业务规则.md)。仅管理员开放，保留 last_commit_wins、行锁、领域通道和幂等；读取本地 PG，写入、审计、库存修正流水和 outbox 同事务。无 SQL 迁移、无飞书字段增删，无新增管理员消息。

| 来源 | 稳定表 ID | 更新字段 |
|---|---|---|
| 普通物料 | tbl4UsiEmprnImIY | 当前库存 fldxI2P07C |
| 文化周边 | tblu3wRpylTj6zJl | 当前库存 fld5XxOhp9；沿用非正库存申领开关规则 |
| 行政文化衫 | tbledtC3RafsHNh0 | 入库/纠正 fldrIT2TnY；不直接写最新库存 fld6RjVT0Q 或兑换数量 |
| 库存流水 | tbljMfuTeGM7VC3v | 库存修正、前后数量、差额、操作人、来源与说明 |

## 处理过程和代码

- 实际 timer / journal 确认 2026-10-30 03:00 历史运行被旧 Worker 跨连接锁互等阻塞，03:15 超时；V4.1.7 已修 guard/claim 重复锁。09:41:04–09:42:08 补跑 23 表成功，更新 644、新增 13、冲突 0。未重复运行审批、扣库或通知。
- material_store/reconcile.py：等待锁前登记运行，120 秒等待超时记录原因、阶段、耗时；恢复原锁超时设置；显示逐表读取进度。取完全部来源后才原子应用的规则保留。
- material_store/stock_workbench.py、request_web/database_api.py、request_web/api.py：三来源库存投影、四维筛选、编码搜索、分页与专用保存接口。文化衫按最新值计算纠正差额，保留兑换；关联流水不伪造跨 Base 链接。
- StockWorkbench.tsx、stock-workbench.css、DatabaseWorkbench.tsx：在虚拟数据库内增加库存查询页签，5 秒自动刷新，编辑期间保留草稿，保存失败保留内容；DatabaseReconcile.tsx 显示每日运行阶段和等待失败原因。
- tests/test_stock_workbench.py、test_reconcile_wait_record.py：隔离 PG、禁止飞书 HTTP；三类型保存、流水审计、outbox、幂等、旧版本并发更新、失败回滚、过滤、权限及真实锁等待超时。

## 验证

| 验证对象 | 环境 / 命令 | 实际结果 / 证据位置 |
|---|---|---|
| 受影响功能 | 隔离 pudu_materials_test；stock_workbench、reconcile_wait_record、manual_reconcile、reconcile_preflight、reconcile_outbox_locking | 27 passed；shared/stock-workbench-tests.log |
| 前端 | VM npm run build | TypeScript / Vite build 成功；shared/stock-workbench-build.log |
| 统一发布 | sudo pudu-release | 发布命令执行完整后端 / 前端测试和构建；真实终态见 shared/release-audit.jsonl |
| 线上只读回读 | 三类库存列表 / 过滤 / 对话框取消 / 定时器与服务 / 公网版本 | 发布后写入 shared/audits/stock-workbench-live-20261030.json 及受限截图；不写生产库存，不发送测试通知 |

## 提交与上线

代码及本记录一起提交，release 自动关联该提交。实际版本、SHA、所有服务与校验回执由正式发布后只读采集；不预填尚未发生的成功。GitLab / GitHub 镜像与默认分支 README 随本次发布更新。

## 遗留事项 / 回退方法

最终验收以发布回执为准。凌晨下一次实际运行需到 2026-10-31 03:00 才产生结果，本次没有把未来执行写成成功。回退沿用正式发布流程，保留数据库、库存流水、审计和 outbox，不以源码回退撤销已提交业务数据。
