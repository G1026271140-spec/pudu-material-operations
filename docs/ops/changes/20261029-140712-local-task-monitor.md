# 本地后台任务实时页面

- 北京时间：2026-10-29
- 操作人 / 工作区：gaohongyuan1 / /srv/pudu-materials-workspaces/gaohongyuan1
- 用户需求：专门页面查看 Worker 任务，可以不写入飞书；补充要求实时查看所有进行中的任务。
- 业务基准：V4.0.4 / 96c4b48df4fcd343d871f89ba9910b6e66bb6fb1。

## 设计与实现

系统工具增加仅管理员的“后台任务” /management/tasks。五类本地记录统一查看：jobs 业务、outbox 飞书同步、effects 卡片通知、reconcile_runs 校验、import_runs 导入。默认进行中，全局状态计数、类型 / 状态 / 日期 / 单号搜索、游标分页、详情与关联处理链，每 2 秒自动刷新，隐藏页面暂停并在返回时刷新；失败显示旧数据标识。大标题说明栏继续取消，提示沿用右上角红色浮层。

业务 jobs 的执行过程在原事务内，处理中状态原本不可见；现以独立短连接写入本地 documents 的 task-activity 标记与进度，完成清除，读取时核对 PostgreSQL backend PID 与启动时间。崩溃旧标记不会显示为正在执行。此标记不经过 outbox、不写飞书，业务事务 / 顺序 / 幂等保持不变。effects / outbox 保留原状态机。

查询为限定表、参数化条件、只读事务，分页有上限；凭据键和错误中的凭据信息隐藏。没有新增重试、取消、删除、编辑任务操作。

## 文件

material_store/task_monitor.py、task_activity.py、jobs.py、inbound.py；request_web/task_monitor_api.py、api.py；Portal.tsx、TaskMonitorPage.tsx、task-monitor.css；隔离测试、README、固定规则。

## 验证与发布

测试仅在 pudu_materials_test / 模拟飞书，覆盖五类、执行可见性、崩溃标记、筛选分页、状态变更、关联依赖、只读性、脱敏和非管理员拒绝。实际测试日志 shared/task-monitor-tests.log；上线版本 / SHA 取 shared/release-audit.jsonl，只读回读 shared/audits/task-monitor-live-20261029.json。上线后不投递测试申请或通知。

## 遗留与回退

页面显示持久化任务 / 校验 / 导入及 Worker 心跳，不把业务完成误报成同步完成；没有给扫描循环内每个内部函数建立“任务”。正式回退保留生产数据及队列。


## 实际开发验证

相关隔离后端回归 37 passed，前端 28 passed，构建通过；优化前端列表对应查询后，在当前生产库只读执行 active / all / problem 三种查询约 16 / 13 / 9 ms。该数值仅 VM 内部查询时间，不是公网页面时限。全量后端测试在发布前达到 1070 passed / 4 skipped / 22 subtests（此后增加发布入口运行标记检查测试，最终结果以正式发布为准）。

发布入口同时检查有效运行标记，避免原子事务未提交时被当作空闲；没有修改现网服务定义或外置凭据。仓库默认 README 和 GitHub 镜像在实际发布后同步。
