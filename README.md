# PUDU 物料库存 Streamlit

这是一个本地 Git 项目，用 Streamlit 提供物料库存在线表单：

- 从 `data/source_materials.xlsx` 读取产品品类、型号、语种。
- 普通品类生成「品类 + 型号 + 语种」库存组合。
- 绿色底纹品类生成「品类 + 语种」库存组合，并把型号统一标记为「无需型号」。
- 支持一次提交多种物料的入库、出库和盘点修正。
- 支持新增物料品类，可多选已有产品型号和语种，也可自定义新增型号和语种。
- 新增品类后会自动生成库存行，并同步更新库存更新表单的下拉选项。
- 实时库存主数据保存在 Streamlit 应用目录的 `data/inventory.xlsx`。
- 配置 Supabase 后，实时库存主数据会保存在 Supabase 长期数据库。
- 实时库存页支持下载完整库存表、当前筛选结果和库存变更流水。
- 实时库存查看页需要密码 `376493`。

## 运行

```powershell
cd "$env:USERPROFILE\Desktop\pudu-material-inventory"
.\run_app.ps1
```

`run_app.ps1` 会自动寻找可用端口。如果 `8501` 被占用，会自动尝试 `8502`、`8503` 等端口。

如果第一次运行时还没有安装依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

运行后打开脚本打印的链接：

- 库存更新表单: `http://localhost:8501`
- 实时库存表: `http://localhost:8501/?view=inventory`

实时库存页需要输入密码 `376493`。

## Streamlit Secrets

部署到 Streamlit Cloud 时，在 Secrets 里填写：

```toml
INVENTORY_VIEW_PASSWORD = "376493"
SUPABASE_URL = "https://你的项目.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "你的 service_role key"
```

不要填写 `anon` / `public` key，也不要使用 `SUPABASE_KEY`。应用只接受 `SUPABASE_SERVICE_ROLE_KEY`，避免误用低权限密钥导致无法读写数据库。

如果只填写 `INVENTORY_VIEW_PASSWORD`，应用会继续使用本地 Excel 文件。填写 Supabase 后，应用会自动切换到长期数据库。

首次连接到空的 Supabase 数据库时，应用会把 `data/inventory.xlsx` 中的初始库存组合导入数据库。之后入库、出库、新增品类和流水都会写入 Supabase。

## 多人共同管理

不要让每个人各自在自己电脑上运行一份应用，否则每个人都会有独立的库存文件，数据不会同步。

建议把项目部署在一台固定电脑、公司内网服务器或 VPS 上，让所有管理人访问同一个 Streamlit 地址。详细说明见 `DEPLOYMENT.md`。

## 数据文件

- `data/inventory.xlsx`: 完整库存表
- `data/inventory.csv`: 完整库存表 CSV
- `data/options.json`: 下拉选项和绿色品类规则
- `data/transactions.csv`: 每次库存变更流水

## 新增物料品类

在首页打开「新增物料品类」标签页：

1. 填写新增物料品类名称。
2. 多选已有产品型号和语种，或在自定义输入框中新增型号、语种。
3. 如该品类不按型号分类，勾选「该品类不按产品型号分类」。
4. 点击「生成新增物料行」后，系统会把组合写入 `data/inventory.xlsx`，并更新表单选项。

如需重新根据源表生成初始库存：

```powershell
python scripts/generate_inventory.py
```
