# Marketing materials Control

本地控制台把项目配置、配置来源、外部修改入口、Windows 后台任务、日志和生效动作放在同一界面中。它是项目代码的一部分，会随仓库版本更新；实际密码、App Secret 和 Token 仍只保存在被 Git 忽略的 `.streamlit/secrets.toml`。

## 启动

下载或克隆源码后，可直接双击项目根目录的 `Marketing materials Control.exe`。这是便携式 Windows 应用，不要求先启动 Streamlit，也不会在打开时停止、重启或重新安装现有网页、Tunnel、Worker 或缓存任务。

如果需要从源码重新生成应用：

```powershell
.\scripts\build_control_center_app.ps1
```

打包脚本会读取 `app.py` 中的 `APP_VERSION`，同步写入 EXE 元数据和 `Marketing materials Control.version`。现有启动脚本只会优先打开与源码版本一致的 EXE，避免项目升级后误开旧控制台；每次正式版本发布都应重新运行打包脚本并提交新的 EXE 与版本标记。

运行：

```powershell
.\scripts\run_control_center.ps1
```

安装桌面快捷方式：

```powershell
.\scripts\install_control_center_shortcut.ps1
```

## 配置分层

- `config/project_config.json`：非敏感且需要随版本同步的项目配置，包括 GitHub 仓库与分支、正式入口、本地端口、飞书精确表名、队列/Worker 参数、任务名称与执行时间。
- `.streamlit/secrets.toml`：本机敏感配置，包括页面密码、控制台主密码、飞书 App ID/App Secret/Base Token、审批回写凭证、GitHub Token 和 Cloudflare Tunnel Token。该文件被 Git 忽略。
- `.streamlit/config.toml`：Streamlit 自身配置，例如监听地址、上传大小和主题。
- Windows 任务计划程序：真实运行状态、触发器、最近结果和下次运行时间。控制台只允许操作项目清单内的固定任务。

控制台保存前会验证数据类型和关键格式，并把原文件备份到 `work/control_center/backups/<时间戳>/` 后再原子替换。敏感值在列表和详情中默认遮罩；查看或修改时需要 `CONTROL_CENTER_MASTER_PASSWORD`，未设置时暂时回退为 `INVENTORY_VIEW_PASSWORD`。

## 本机与云端的边界

本机控制台不会静默覆盖云端 Secrets，也不会因保存配置而自动重启任何服务。修改 `.streamlit/secrets.toml` 后，相关本地 Runner 可在管理员明确确认后通过“同步所选任务配置”复制新值并重装任务；Streamlit Cloud、GitHub Actions、飞书开放平台和 Cloudflare Dashboard 中的同名值仍需在每条配置显示的平台入口同步。这样可避免本机配置误覆盖生产环境。

## 审批定义与审批实例

- 审批定义 Code 是长期配置，记录在 `config/project_config.json`，并应与 `anycross.feishu` 中的流程蓝图一致。
- 审批实例 Code 是每次申请运行后产生的数据，用于查询、回写和排错，不应保存为固定配置。后续实例查询应从申请单、后台队列载荷或飞书审批 API 读取。

## 后台任务控制

“后台任务与日志”页面可以读取、启动、停止、重启和立即运行以下任务，并显示最近结果与下次运行时间：

- 本地 Web 应用与 Cloudflare Tunnel
- 提交 Worker
- 飞书卡片 Worker
- 物料缓存与联系人缓存
- Streamlit 夜间唤醒

“同步所选任务配置”会运行仓库中对应的受控安装器，复制 Secrets 到独立 Runner 并重装相关任务。同步完成只代表安装动作完成；正式验收仍需检查日志、最终任务结果、各运行目录 Git 修订以及对应业务读回。
