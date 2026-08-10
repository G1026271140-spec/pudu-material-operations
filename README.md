# PUDU 物料库存 Streamlit

这是一个基于 Streamlit 的物料库存应用，数据库只使用飞书多维表格：

- 普通品类按「品类 + 型号 + 语种」管理库存组合。
- 不按型号分类的品类按「品类 + 语种」管理，并把型号统一标记为「无需型号」。
- 支持一次登记多种营销物料领取和物料采购。
- 支持新增物料品类，并自动写入飞书「物料品类」和「物料主数据」表。
- 管理员可在统一的「物料管理」工作台切换采购补库、品类管理和物料数据库。
- 采购补库支持最多 20 条明细、提交前预览、直接增加库存、逐条写入库存流水并向全部启用管理员发送补库卡片。
- 库存登记会直接更新飞书「物料主数据」当前库存，并写入飞书「库存流水」。
- 飞书机器人支持通过截图或文字查询物料库存；文字支持品类、型号、语种的部分词和近似拼写，并返回实时库存、库存不足、无此组合及相似组合卡片。
- 实时库存页支持下载完整库存表、当前筛选结果和库存变更流水。
- 实时库存查看页需要密码 `376493`。

飞书多维表格是唯一运行时数据库。飞书配置缺失时，应用会直接停止并提示补齐配置。

## 运行

```powershell
cd "$env:USERPROFILE\Desktop\飞书多维表格版"
.\run_app.ps1
```

`run_app.ps1` 会自动寻找可用端口。如果 `8501` 被占用，会自动尝试 `8502`、`8503` 等端口。

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
INVENTORY_VIEW_PASSWORD = "376493"

FEISHU_APP_ID = "cli_xxx"
FEISHU_APP_SECRET = "你的 app secret"
FEISHU_BITABLE_APP_TOKEN = "多维表格 base 链接里的 app_token"
```

应用会按表名自动发现以下飞书多维表格：

- 物料主数据
- 物料品类
- 库存流水
- 物料申请单
- 申请明细
- 库存批量操作

飞书应用需要开通多维表格读写权限，并在目标多维表格右上角 `... -> 更多 -> 添加文档应用` 中添加为文档应用。

## 多人共同管理

多人共同管理时，请让所有人访问同一个已部署的 Streamlit 应用地址。所有库存读取、登记、新增品类和流水写入都会访问同一个飞书多维表格。

## 本地静态缓存任务

Windows 本地缓存节点每天 `10:30` 和 `16:30` 从飞书生成最新静态缓存，并推送到 GitHub `master`。物料申领与采购补库共用启用品类、型号、语种和库存组合缓存，因此本地任务会同时更新两个页面。缓存生成前还会维护库存行状态：库存不为 `0` 的行自动启用；库存为 `0` 且超过 14 天没有有效库存数量变化的行自动停用，并向全部启用管理员发送明细卡片。`物料主数据.库存归零时间` 由程序自动创建和维护。安装或重新配置：

“物料仓库位置查询”使用独立的人工发布静态缓存，不参与上述定时任务，也不参与应用内“更新全部数据缓存”。仅在明确需要更新位置文字或图片时手动运行 `python scripts/generate_warehouse_location_cache.py` 并发布生成的缓存与图片。

Windows 本地电脑另有 `PUDU Streamlit Nightly Wake` 定时任务，每天 23:20 使用无界面 Edge 检查生产应用；如遇休眠页会自动点击唤醒，并在 `work/streamlit-wake.log` 记录应用就绪结果。该任务只访问线上页面，不刷新飞书或静态缓存。

如需手动执行，可双击桌面的 `PUDU Streamlit Manual Wake` 快捷方式。重新创建快捷方式时，运行 `scripts/install_streamlit_wake_shortcut.ps1` 即可。

```powershell
.\scripts\install_local_cache_task.ps1
```

安装内容：

- 计划任务：`PUDU Material Cache Refresh`
- 独立运行目录：`%LOCALAPPDATA%\PuduMaterialCacheRunner`
- 桌面手动入口：`Update PUDU Static Cache.lnk`
- 运行日志：`%LOCALAPPDATA%\PuduMaterialCacheRunner\logs\latest.log`

任务支持锁屏运行、从睡眠中唤醒和错过计划后补跑；电脑关机时无法执行。GitHub Actions 工作流保留手动触发作为备用，不再承担定时更新。

## 迁移与导出文件

`data/` 和 `outputs/` 下的 Excel/CSV 文件只作为历史导入、迁移模板或下载导出使用，不再作为应用运行时数据库。

如需重新生成飞书导入模板：

```powershell
.\.venv\Scripts\python.exe scripts\generate_feishu_bitable_migration.py
```
