# 多人共用与部署说明

这个项目已经把实时库存主数据保存在 Streamlit 应用目录下：

- `data/inventory.xlsx`: 当前完整库存表
- `data/inventory.csv`: 当前完整库存表 CSV
- `data/options.json`: 表单下拉选项
- `data/transactions.csv`: 库存变更流水

所有物料领取、物料采购、新增物料品类操作都会直接更新这些应用内数据文件。实时库存页提供完整库存表和当前筛选结果的下载按钮。

## 推荐方式：部署到一台固定服务器

多人共同管理时，不建议每个人各自在电脑上运行一份应用。那样每个人的 `data/inventory.xlsx` 都是独立文件，库存不会同步。

建议选择一台固定电脑、公司内网服务器或 VPS 来运行这个应用：

```powershell
cd "$env:USERPROFILE\Desktop\pudu-material-inventory"
.\run_app.ps1
```

`run_app.ps1` 会自动寻找可用端口。如果 `8501` 被占用，它会自动尝试 `8502`、`8503` 等端口，并打印本机地址和局域网地址。

其他管理人只需要访问同一个地址，例如：

```text
http://服务器IP:端口
http://服务器IP:端口/?view=inventory
```

这种方式下，库存表保存在服务器项目目录的 `data/` 文件夹中，大家看到和更新的是同一份数据。

## Streamlit Community Cloud

如果你希望得到一个 `https://xxx.streamlit.app` 这样的公网链接，可以把项目推送到 GitHub，然后在 Streamlit Community Cloud 中选择仓库、分支和 `app.py` 部署。

## 飞书登录

当前测试版本已经把飞书登录作为全站门禁。未通过飞书登录时，不会显示库存登记、实时库存、数据维护等任何页面。实时库存页原来的查看密码 `376493` 仍然保留，飞书登录通过后进入实时库存页还需要输入一次该密码。

在飞书开发者后台创建企业自建应用后，进入应用的安全设置，把应用访问地址配置为重定向 URL。然后在 Streamlit Secrets 中填写：

```toml
FEISHU_APP_ID = "cli_xxxxxx"
FEISHU_APP_SECRET = "你的 App Secret"
FEISHU_REDIRECT_URI = "https://你的应用地址"
FEISHU_ALLOWED_TENANT_KEY = "深圳市普渡科技股份有限公司对应的 tenant_key"
FEISHU_SCOPE = ""
```

企业限制建议使用飞书 `user_info` 接口返回的 `tenant_key` 判断，而不是使用公司中文名。第一次配置时，可以先用普渡员工账号登录；如果 `FEISHU_ALLOWED_TENANT_KEY` 未填或填错，页面会提示当前账号返回的 `tenant_key`，复制该值到 Secrets 后重新启动应用即可。

## Supabase 长期数据库

正式多人长期使用时，推荐启用 Supabase。步骤如下：

1. 在 Supabase 新建项目。
2. 打开 Supabase SQL Editor。
3. 复制并运行 `supabase/schema.sql` 的全部 SQL。
4. 打开 Project Settings -> API，复制 Project URL 和 `service_role` key。
5. 在 Streamlit Cloud 的 Secrets 区域填写：

```toml
INVENTORY_VIEW_PASSWORD = "376493"
SUPABASE_URL = "https://你的项目.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "你的 service_role key"
```

`SUPABASE_SERVICE_ROLE_KEY` 只能放在 Streamlit Secrets 里，不要写入 GitHub 仓库。
不要填写 `anon` / `public` key，也不要使用 `SUPABASE_KEY`。如果页面报 `permission denied for table inventory_items`，基本就是密钥填错了。

可以参考 `.streamlit/secrets.toml.example`，但不要把真实密钥提交到 GitHub。

首次连接到空数据库时，应用会自动把 GitHub 仓库里的 `data/inventory.xlsx` 初始化导入 Supabase。之后所有库存登记、新增物料品类和库存变更流水都会写入 Supabase，不再依赖 Streamlit Cloud 的临时文件系统。

需要注意：Streamlit Community Cloud 适合快速共享应用地址，但应用运行时写入的本地文件不是长期数据库。代码重新部署、应用重启或云端环境重建后，`data/inventory.xlsx` 可能会回到 GitHub 仓库里的版本。因此如果采用 Community Cloud，请定期从实时库存页下载完整库存表备份。正式多人长期使用更推荐固定服务器或后续接入外部数据库。

## 下载备份

打开实时库存页并输入密码 `376493` 后，可以下载：

- 完整库存 Excel
- 完整库存 CSV
- 库存变更流水
- 当前筛选结果 Excel
- 当前筛选结果 CSV
