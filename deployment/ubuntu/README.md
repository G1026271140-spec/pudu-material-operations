# Ubuntu 服务搭建（非业务上线）

本目录是 2026-10-23 虚拟机准备阶段的部署资产，**不修改现有 Windows 生产实例**。

- 系统：Ubuntu 24.04 / Python 3.12，目标账号 `gaohongyuan1`。
- 安装目录：`/home/gaohongyuan1/pudu-materials-operation`，下设 `source/`、`venv/`、`logs/`。
- Web：`pudu-material-web.service` 监听 `0.0.0.0:8501`，开机自启，systemd 自动重启，日志写 journal。
- `GET /api/health` 返回 200，只表示服务活着，响应明确 `business_ready=false`。
- 其他所有路径/方法返回 503，不开放文档、文件、OAuth、业务读写或同步 Webhook。没有业务缓存，也不启动原应用的收据通知/对账线程。
- Worker：`pudu-material-worker.service` 仅安装，默认不启用。需要真实密钥以及 root 管理的 `/etc/pudu-materials-operation/worker-enabled` 标记才能启动。**不要为了验证 unit 而创建标记。**
- 截图拟用域名 `materials.pudu.work` 暂不写入正式配置；IT 可以先用 IP:8501 验证连通性。没有切换 DNS、TLS、飞书工作台或 OAuth 回调。

## 离线依赖

在有网络的准备机上，用 `pip download --only-binary=:all:` 为 CPython 3.12 / Linux x86_64 收集 wheel，打包后核对 SHA-256 传到虚拟机。虚拟机 `python3 -m venv --without-pip venv`，使用 wheel 内的 pip 离线引导，再用 `--no-index --find-links` 安装。不修改 Ubuntu 的系统 Python，不通过准备机代理飞书业务访问。

打包资产须保存全部 wheel 哈希清单和最终固定依赖列表。`pip check`、原业务模块导入、Worker `--help` 和隔离测试通过，仅表示运行环境适配，不代表读写业务已通过。

本次顶层依赖沿用原环境版本，唯独 pandas 3.0.4 已被上游撤回（日期功能崩溃），Ubuntu 准备环境改用 3.0.6；不修改 Windows 环境。所有传递依赖以实际离线包中的锁定列表及哈希为准。

## 验证与维护

```sh
sudo systemctl status pudu-material-web --no-pager
sudo journalctl -u pudu-material-web -n 50 --no-pager
curl -fsS http://127.0.0.1:8501/api/health
curl -i http://127.0.0.1:8501/api/readiness
sudo systemctl is-enabled pudu-material-worker
sudo systemctl is-active pudu-material-worker
```

Web 配置安装前用 `systemd-analyze verify` 校验。日志不打印密码、令牌或业务载荷。不要通过重启整台虚拟机来测试此阶段的开机自启；检查 enable 状态并有控制地重启 Web 服务验证。

## 后续上线前置条件

1. 飞书开放平台出网放通，使用原“营销物料管理”应用身份通过只读检查。
2. 实现并验证实时读取模式：不使用业务 JSON / 跨请求内存快照；不把本阶段服务误认为已实现实时读表。
3. 公司域名、TLS、飞书回调与企业身份校验完成，业务读写入口按现有用户权限保护。
4. 核对原 Worker 和在途任务，排空后单一执行节点切换，启用前审查持久状态和日志写入路径。本模板的可写目录需按实际任务验收补全，不能任意放宽为全目录。
5. 完成真实任务终态、源表写回、库存、配额和通知验证，再处理原 Worker 的自启动。幂等记录、队列租约、SQLite 写入状态不是读取缓存，不能删除。

没有验证以上各项时，保持 commissioning 入口和禁用的 Worker；不直接将 ExecStart 换成原 api 冒充迁移成功。
