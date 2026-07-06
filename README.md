# PUDU 物料库存 Streamlit

这是一个基于 Streamlit 的物料库存应用，数据库只使用飞书多维表格：

- 普通品类按「品类 + 型号 + 语种」管理库存组合。
- 不按型号分类的品类按「品类 + 语种」管理，并把型号统一标记为「无需型号」。
- 支持一次登记多种营销物料领取和物料采购。
- 支持新增物料品类，并自动写入飞书「物料品类」和「物料主数据」表。
- 库存登记会直接更新飞书「物料主数据」当前库存，并写入飞书「库存流水」。
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

## 迁移与导出文件

`data/` 和 `outputs/` 下的 Excel/CSV 文件只作为历史导入、迁移模板或下载导出使用，不再作为应用运行时数据库。

如需重新生成飞书导入模板：

```powershell
.\.venv\Scripts\python.exe scripts\generate_feishu_bitable_migration.py
```
