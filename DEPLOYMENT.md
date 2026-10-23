# 部署与迁移

当前代码使用 React + FastAPI + Python Worker，配置入口统一为 `config/secrets.toml` 或 `PUDU_SECRETS_FILE` 指定的外部文件；不再有旧页面服务器或云端唤醒任务。

## Ubuntu

先按 [Ubuntu 服务说明](deployment/ubuntu/README.md) 准备独立 Python 环境和 systemd 服务。服务准备阶段只开放 `/api/health`，其他业务路径返回 503。Worker 仅安装配置，切换条件未满足前保持 disabled/inactive。

上线前须验证：

1. 网络：虚拟机能连接飞书开放平台和公司批准的软件源。
2. 身份：公司域名、HTTPS、飞书重定向地址与企业身份校验；管理员和 HR 角色仍来自权限表。
3. 数据：实时模式不读取生产业务快照；逐请求测量源表耗时。认证令牌复用不等于业务缓存。
4. 执行：任务生成接口、队列和 Worker 端到端通过。排空原节点在途任务后只切换一个生产执行节点，不能靠非原子领导选举保证双节点绝不重复。
5. 结果：按真实申请单、明细、库存/配额、任务终态和通知结果验收，不以入队成功或进程 Running 代替完成。

## Windows 现有生产

Web、Submission Worker、卡片 Worker 和 Cache Runner 是独立运行副本。当前分支的源码修改不会自动更新这些副本。旧节点升级必须受控迁移密钥到新配置路径，并整体验证，不得只更新其中一个文件。

维护脚本统一使用新的 `config` 目录。`scripts/run_local_web_app.ps1` 启动 `uvicorn request_web.api:api`；`scripts/submission_worker.py` 执行队列；`scripts/feishu_card_worker.py` 处理卡片长连接。当前生产节点暂不停止或换源，等待迁移窗口。

## 安全与回退

不要提交密钥、人员快照、SQLite、通知 outbox 或日志。配置文件权限最小化，日志只记录必要的任务标识和错误摘要。新节点验收失败时保持未接管状态，旧节点继续运行；不要删除旧队列状态或重放已有任务来测试。
