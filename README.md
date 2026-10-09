# PUDU 物料库存 Streamlit

这是一个基于 Streamlit 的物料库存应用，数据库只使用飞书多维表格：

- 普通品类按「品类 + 型号 + 语种」管理库存组合。
- 不按型号分类的品类按「品类 + 语种」管理，并把型号统一标记为「无需型号」。
- 支持一次登记多种营销物料领取和物料采购。
- 页面触发的飞书业务写入统一先进入飞书「后台任务队列」，由独立 Windows Worker 执行物料申请、采购补库、品类维护、库存提交修正/撤回和周边礼品项目写入；页面确认入队后可以直接关闭，任务失败会自动重试。
- 普通物料申领不限制单次物料种类或单一明细数量；申请原因「代理商支持」兼容历史队列中的「代理活动」。选择代理商支持时，页面将客户名称外显为代理商名称，但仍写入原客户名称字段。管理员通知和配货工作台显示申请原因及申请总金额，配货调整时即时重算当前配货总金额。
- 支持新增物料品类，并自动写入飞书「物料品类」和「物料主数据」表。
- 工作台提供「发货模板填写」，国家名称支持输入中文、英文或两位代码并自动转换为英文简称；箱内品类按「印刷物料」「周边礼品」分成两个按钮式多选池，再按物料品类自动汇总唯一的商业发票明细。每箱长、宽、高和毛重为红底必填项，体积、1-3KG 包材重量和净重自动计算，下载文件统一移除单元格填充色，并支持一箱多品、同一物料拆分到多箱以及金额、重量和体积汇总。
- 管理员可在统一的「物料管理」工作台切换采购补库和品类管理；工作台导航提供飞书库存查询入口。
- 品类删除页按「印刷物料」「周边礼品」显示两个紧凑品类池，品类只能单选；选定品类后可分别多选产品型号和语种，并在提交前预览实际删除的物料行。
- 采购补库支持最多 20 条明细、提交前预览、直接增加库存、逐条写入库存流水并向全部启用管理员发送补库卡片。
- 库存登记会直接更新飞书「物料主数据」当前库存，并写入飞书「库存流水」。
- 飞书机器人支持通过截图或文字查询物料库存；文字支持品类、型号、语种的部分词和近似拼写，并返回实时库存、库存不足、无此组合及相似组合卡片。
- 实时库存页支持下载完整库存表、当前筛选结果和库存变更流水。
- 实时库存查看页需要密码 `376493`。

飞书多维表格是唯一运行时数据库。飞书配置缺失时，应用会直接停止并提示补齐配置。

发货模板的物料下拉读取「物料品类」表，并自动带出「商业发票产品名称」「装箱单产品类型」、美元单价和海关编码；其中「商业发票产品名称」在新增或编辑品类时必填。所有自动带出的发货字段都可在生成前手动修改。

## 运行

```powershell
cd "$env:USERPROFILE\Desktop\营销物料管理系统"
.\run_app.ps1
```

`run_app.ps1` 会自动寻找可用端口。如果 `8501` 被占用，会自动尝试 `8502`、`8503` 等端口。

## 一键部署与迁移

项目内置原生 Windows 部署启动器，用于迁移接管或准备备用节点。启动器会自动安装 Git、Python 3.12 和 cloudflared，再配置飞书、域名、本地端口、后台 Worker 与缓存计划任务：

```powershell
.\scripts\run_deployment_launcher.ps1
```

首次使用可创建桌面快捷方式：

```powershell
.\scripts\install_deployment_launcher_shortcut.ps1
```

新电脑可通过部署启动器一键安装 Git、Python 3.12 和 cloudflared，并继续配置 Web、Tunnel、后台 Worker 与缓存任务。敏感项保存在 Git 忽略的 `.streamlit/secrets.toml`。完整说明见 `docs/deployment_launcher.md`。

React 前端、FastAPI、本机 Web Runner、Cloudflare Tunnel 与公网域名之间的完整关系见 [`docs/frontend-and-tunnel-architecture.md`](docs/frontend-and-tunnel-architecture.md)。

如果第一次运行时还没有安装依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

运行后打开脚本打印的链接：

- 库存登记表单: `http://localhost:8501`
- 实时库存表: `http://localhost:8501/?view=inventory`

## Streamlit Secrets

部署或本地运行前，在 `.streamlit/secrets.toml` 或 Streamlit Cloud Secrets 中填写：

```toml
INVENTORY_VIEW_PASSWORD = "replace-with-a-strong-password"
APPROVAL_VIEW_PASSWORD = "replace-with-a-strong-password"
FEISHU_APP_ID = "cli_xxx"
FEISHU_APP_SECRET = "你的 app secret"
FEISHU_BITABLE_APP_TOKEN = "多维表格 base 链接里的 app_token"
FEISHU_CORPORATE_APPAREL_SOURCE_APP_TOKEN = "行政文化衫源表对应 Base 的 app_token"
FEISHU_APPROVAL_WRITEBACK_APP_ID = "cli_xxx"
FEISHU_APPROVAL_WRITEBACK_APP_SECRET = "审批回写应用的 app secret"
GITHUB_CACHE_REFRESH_TOKEN = "GitHub repository_dispatch token"
CLOUDFLARE_TUNNEL_TOKEN = "Cloudflare Named Tunnel token"
```

企业文化衫页面从主 Base 中的“文化周边编码及库存数量”同步表读取图片和目录标识，并从行政源表实时读取库存、尺码及已兑换数量；提交和驳回也通过上述独立源表 token 写入行政源表的“系统兑换数量”。“营销物料管理系统”应用必须对行政源表有编辑权限；源表的表 ID 配置在 `config/project_config.json` 的 `feishu.tables.corporate_apparel_source_table_id`。

应用会按表名自动发现以下飞书多维表格：

- 物料主数据
- 物料品类
- 库存流水
- 物料申请单
- 申请明细
- 库存批量操作
- 后台任务队列
- 后台任务载荷

飞书应用需要开通多维表格读写权限，并在目标多维表格右上角 `... -> 更多 -> 添加文档应用` 中添加为文档应用。

## 多人共同管理

多人共同管理时，请让所有人访问同一个已部署的 Streamlit 应用地址。所有库存读取、登记、新增品类和流水写入都会访问同一个飞书多维表格。

## 本地静态缓存任务

控制中心的缓存刷新工具、桌面 `Update PUDU Static Cache` / `Update PUDU Image Cache` 和定时缓存任务，在校验成功后都会把缓存同步到正式本机网页。无需关闭网页服务或控制程序；已打开页面会在约 5 秒内提示新缓存，可点击“加载最新缓存”或在正常页面交互时加载，保留正在填写的表单和购物车。缓存发布失败或正式网页不可用时，工具会明确报错。完整版本发布仍按测试、打包、推送和运行组件同步流程执行。

Windows 本地缓存节点每天 `10:30` 和 `16:30` 从飞书生成最新静态缓存，并推送到 GitHub `master`。物料申领与采购补库共用启用品类、型号、语种和库存组合缓存，因此本地任务会同时更新两个页面。周边礼品项目表中的图片附件会下载到 `assets/gift_projects`；附件更换或删除后，下次刷新会同步替换或清理对应静态图片。缓存生成前还会维护库存行状态：库存不为 `0` 的行自动启用；库存为 `0` 且超过 14 天没有有效库存数量变化的行自动停用，并向全部启用管理员发送明细卡片。`物料主数据.库存归零时间` 由程序自动创建和维护。

发货模板页同样使用页面静态缓存；缓存中的「物料品类」记录会保留「商业发票产品名称」「装箱单产品类型」、美元单价和海关编码，以便线上页面刷新后直接识别最新品类配置。

申请选项缓存使用 v2 结构，额外保存由启用物料行生成的品类、型号、语种组合配置。GitHub 与 Windows 刷新任务在推送缓存前都会重新验证组合配置和原始启用行，避免停用行或维度表中的孤立选项重新出现在申请页面。

“物料仓库位置查询”使用独立的人工发布静态缓存，不参与上述定时任务，也不参与应用内“更新全部数据缓存”。仅在明确需要更新位置文字或图片时手动运行 `python scripts/generate_warehouse_location_cache.py` 并发布生成的缓存与图片。

Windows 本地电脑另有 `PUDU Streamlit Nightly Wake` 定时任务，每天 23:20 使用无界面 Edge 检查生产应用；如遇休眠页会自动点击唤醒，并在 `work/streamlit-wake.log` 记录应用就绪结果。该任务只访问线上页面，不刷新飞书或静态缓存。

如需手动执行，可双击桌面的 `PUDU Streamlit Manual Wake` 快捷方式。重新创建快捷方式时，运行 `scripts/install_streamlit_wake_shortcut.ps1` 即可。

安装或重新配置本地缓存任务：

```powershell
.\scripts\install_local_cache_task.ps1
```

安装内容：

- 计划任务：`PUDU Material Cache Refresh`
- 独立运行目录：`%LOCALAPPDATA%\PuduMaterialCacheRunner`
- 桌面手动入口：`Update PUDU Static Cache.lnk`
- 运行日志：`%LOCALAPPDATA%\PuduMaterialCacheRunner\logs\latest.log`

任务支持锁屏运行、从睡眠中唤醒和错过计划后补跑；电脑关机时无法执行。GitHub Actions 工作流保留手动触发作为备用，不再承担定时更新。

## 申请后台任务 Worker

应用内业务提交不再依赖浏览器页面持续打开。页面只把操作写入飞书「后台任务队列」；较大的任务载荷会自动拆分写入「后台任务载荷」，并在完整读回校验后才确认入队成功。关闭页面、刷新浏览器或 Streamlit Cloud 重启都不会中断后续写入。物料申请不再提供附件。Windows Worker 每 5 秒检查任务，异常后按退避时间自动重试；Worker 意外退出时，处理中任务会在 10 分钟租约到期后恢复。

安装或更新 Worker：

```powershell
.\scripts\install_submission_worker_task.ps1
```

安装内容：

- 计划任务：`PUDU Submission Worker`
- 独立运行目录：`%LOCALAPPDATA%\PuduSubmissionWorker`
- 独立 Git 副本和 Python 环境，不修改桌面项目，也不与缓存任务共用运行目录
- Worker 日志：`%LOCALAPPDATA%\PuduSubmissionWorker\logs\worker.log`
- 启动日志：`%LOCALAPPDATA%\PuduSubmissionWorker\logs\bootstrap.log`

计划任务在当前 Windows 用户登录后常驻运行，锁屏不影响处理；异常退出后一分钟自动重启。代码更新并推送到 `master` 后，重新执行安装脚本即可停止旧进程、更新独立副本并启动新版本。

## 迁移与导出文件

`data/` 和 `outputs/` 下的 Excel/CSV 文件只作为历史导入、迁移模板或下载导出使用，不再作为应用运行时数据库。

如需重新生成飞书导入模板：

```powershell
.\.venv\Scripts\python.exe scripts\generate_feishu_bitable_migration.py
```
