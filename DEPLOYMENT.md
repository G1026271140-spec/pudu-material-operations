# 多人共用与部署说明

这个项目现在只使用飞书多维表格作为运行时数据库。飞书配置缺失时，应用会直接停止并提示补齐配置。

## 推荐方式

把项目部署在一台固定电脑、公司内网服务器、VPS 或 Streamlit Community Cloud 上，让所有管理人访问同一个 Streamlit 地址：

```powershell
cd "$env:USERPROFILE\Desktop\飞书多维表格版"
.\run_app.ps1
```

`run_app.ps1` 会自动寻找可用端口。如果 `8501` 被占用，它会自动尝试 `8502`、`8503` 等端口，并打印本机地址和局域网地址。

其他管理人只需要访问同一个地址，例如：

```text
http://服务器IP:端口
http://服务器IP:端口/?view=inventory
```

## 必填 Secrets

本地运行时写入 `.streamlit/secrets.toml`，云端部署时写入 Streamlit Cloud Secrets：

```toml
INVENTORY_VIEW_PASSWORD = "376493"

FEISHU_APP_ID = "cli_xxx"
FEISHU_APP_SECRET = "你的 app secret"
FEISHU_BITABLE_APP_TOKEN = "多维表格 base 链接里的 app_token"
STREAMLIT_APP_URL = "https://pudu-material-inventory-ndgbxrpkkrzgkbapvhzvix.streamlit.app/"
```

缺少任意一项飞书配置时，应用会直接停止并提示补齐配置。
`STREAMLIT_APP_URL` 用于机器人消息中的审批链接；当前生产地址已内置，可不配置，应用地址变更时再覆盖。

## 飞书权限

飞书应用需要：

- 开通多维表格读写相关权限。
- 添加“机器人”应用能力，并开通“以应用的身份发消息”权限（`im:message:send_as_bot`）。
- 开通接收单聊消息（`im:message.p2p_msg:readonly`）、接收群内 @ 机器人消息（`im:message.group_at_msg:readonly`）和读取消息资源（`im:message:readonly`）权限。
- 开通图片识别权限（`optical_char_recognition:image`）。
- 在“事件与回调”中选择长连接方式，并订阅“接收消息”事件（`im.message.receive_v1`）。
- 在开发者后台发布/生效权限变更。
- 在目标多维表格右上角 `... -> 更多 -> 添加文档应用` 中添加该应用。

### 机器人截图查库存

机器人支持从截图或文字识别物料品类、产品型号、语种和需求数量，实时读取飞书“物料主数据”与“物料品类”，并以 Card 2.0 表格回复库存充足、库存不足、无此组合和相似库存组合。文字可按“品类 型号 语种 数量”发送，支持部分品类/型号、语种别名和轻微拼写错误的模糊搜索，最多返回 10 个按相关度排序的真实库存组合；数量可省略，此时只返回当前库存。单聊中直接发送文字或截图即可；群聊中需要在同一条消息里 @ 机器人，截图查询需同时附图。

该功能由 Windows 常驻任务承载，不由 Streamlit Cloud 进程承载。固定电脑安装或更新任务：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_feishu_card_worker_task.ps1
```

计划任务名称默认为 `PUDU Feishu Card Worker`。更新代码后重启该任务即可加载新版本；电脑必须保持联网，任务会在登录时启动并在异常退出后自动重启。

### 营销申请后台任务

营销物料申请采用可恢复后台队列。Streamlit Cloud 只负责上传附件并把完整申请写入飞书「后台任务队列」；独立 Windows Worker 负责创建申请单、申请明细、登记销售身份并发送申请人和管理员机器人消息。应用显示任务已进入后台队列后，用户可以关闭页面，不会中断后续写入。

在保持联网的 Windows 电脑上安装或更新 Worker：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_submission_worker_task.ps1
```

计划任务名称为 `PUDU Submission Worker`，登录后常驻运行，锁屏不影响处理，异常退出后一分钟自动重启。它使用 `%LOCALAPPDATA%\PuduSubmissionWorker` 下的独立 Git 副本、虚拟环境、Secrets 和日志，不会读写桌面工作区，也不会与 `%LOCALAPPDATA%\PuduMaterialCacheRunner` 中的缓存刷新程序发生 Git 冲突。

任务使用 `提交幂等键` 防止 Worker 重启造成重复申请，处理过程会分阶段保存进度。单次任务最多重试 10 次，退避时间最高 15 分钟；Worker 在处理中退出后，10 分钟租约过期即可由重启后的进程接管。日志位置：

```text
%LOCALAPPDATA%\PuduSubmissionWorker\logs\worker.log
%LOCALAPPDATA%\PuduSubmissionWorker\logs\bootstrap.log
```

手动检查或恢复失败任务：

```powershell
Stop-ScheduledTask -TaskName "PUDU Submission Worker"
cd "$env:LOCALAPPDATA\PuduSubmissionWorker\repo"
.\.venv\Scripts\python.exe scripts\submission_worker.py --once
.\.venv\Scripts\python.exe scripts\submission_worker.py --retry-failed --once
Start-ScheduledTask -TaskName "PUDU Submission Worker"
```

代码推送到 `master` 后重新运行安装脚本，安装器会停止旧 Worker、快进更新独立副本、校验或修复队列表结构，再启动新版本。

营销物料申请成功后，机器人会自动向“用户权限表”内角色包含“管理员”且“是否启用”为“是”的账号发送无操作按钮的申请通知卡片。卡片完整展示申请信息、收件信息、物料用途与全部明细，并提示管理员关注飞书审批进度。申请人若尚未登记，应用会新增一条仅包含“销售”身份的启用记录；应用不会自动添加管理员身份。启用的申请人会收到已进入审批流程的回执和物料明细。机器人提醒失败不会影响申请数据的写入。

“物料管理”统一包含采购补库、品类管理和物料数据库。采购补库确认后直接增加物料主数据库存，并为每条明细写入“物料采购（增加库存）”流水；完成后机器人会向全部启用管理员发送补库卡片，列明补库单号、补库人、采购单号、补库说明、每条物料及库存变化。采购补库与物料申领共用静态选项缓存，Windows 本地缓存任务会在每天 `10:30` 和 `16:30` 同步更新。

申请与补库选项缓存会从当前启用的“物料主数据”行生成品类、型号、语种组合配置。GitHub 手动缓存工作流、Windows 本地缓存任务和应用内缓存刷新使用同一份表清单与构建逻辑；静态缓存提交前会校验组合配置、唯一组合数和原始启用行完全一致，校验失败时不会发布缓存。

每次 Windows 本地缓存任务、GitHub 手动缓存工作流或应用内“更新全部数据缓存”执行前，都会维护库存行启停状态：库存不为 `0` 的行自动启用；库存为 `0` 且超过 14 天没有有效库存数量变化的行自动停用，并向全部启用管理员发送停用明细卡片。首次运行会在“物料主数据”自动创建文本字段 `库存归零时间`；没有历史流水和计时值的零库存行从首次检查时开始计时，不会被立即误停用。

应用会按名称读取以下表：

- 物料主数据
- 物料品类
- 库存流水
- 物料申请单
- 申请明细
- 库存批量操作
- 用户权限表
- 后台任务队列

“物料申请单”包含独立文本字段：`客户名称`、`国家`、`收件人信息`、`运费承担者`。审批发放页不读取仓库静态缓存；进入页面及点击“刷新实时数据”时直接从飞书读取申请单、申请明细和物料主数据。

## 下载备份

打开实时库存页并输入密码 `376493` 后，可以从飞书当前数据导出：

- 完整库存 Excel
- 完整库存 CSV
- 库存变更流水
- 当前筛选结果 Excel
- 当前筛选结果 CSV
