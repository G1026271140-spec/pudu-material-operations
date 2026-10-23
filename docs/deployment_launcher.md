# PUDU Material Operations 部署启动器

部署启动器用于把营销物料管理系统迁移到新电脑，或预先准备一个不会争抢后台队列的备用节点。

## 一键安装范围

启动器会请求 Windows 管理员权限，并通过 `winget` 自动安装和校验：

- Git
- Python 3.12
- cloudflared

用户不需要提前安装这些组件。基础软件安装完成后，启动器会部署项目文件、创建独立 Python 环境、写入本机配置，并按部署模式注册计划任务。

## 部署模式

- 迁移接管：启动 Web、Cloudflare Tunnel、提交 Worker、飞书卡片 Worker 和缓存任务。
- 备用节点：只准备代码、运行环境和配置，不注册会与主节点争抢的后台任务。以后可重新运行启动器切换为迁移接管。

启动器不会自动停止或卸载旧电脑上的节点。旧电脑何时退出由管理员另行决定。

## 配置迁移

旧电脑可导出 `.pudu-migration` 文件。迁移包使用 PBKDF2-SHA256 派生密钥并以 AES-256-GCM 加密，App Secret、Token 和管理密码不会以明文写入文件。迁移包密码不得与文件通过同一渠道传输。

## 域名切换

该域名必须归当前部署者所有，并已接入对应的 Cloudflare 账号。选择自动配置时，需要提供仅包含 Tunnel 与 DNS 编辑权限的 Cloudflare API Token；选择手动配置时，启动器会提供配置内容并负责验证。

自动模式会先验证 Zone 与域名关系，再创建或复用 Named Tunnel、写入 Public Hostname 和 CNAME。遇到同名但指向其他目标的 DNS 记录时会停止，不会覆盖。启动器只回滚本次新建的 Tunnel 或 DNS，不删除已有资源。

## 构建和运行

```powershell
.\scripts\build_deployment_launcher.ps1
.\scripts\run_deployment_launcher.ps1
```

构建产物：

- `PUDU Material Operations Setup.exe`
- `PUDU Material Operations Setup.version`
