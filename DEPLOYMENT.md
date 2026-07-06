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
```

缺少任意一项飞书配置时，应用会直接停止并提示补齐配置。

## 飞书权限

飞书应用需要：

- 开通多维表格读写相关权限。
- 在开发者后台发布/生效权限变更。
- 在目标多维表格右上角 `... -> 更多 -> 添加文档应用` 中添加该应用。

应用会按名称读取以下表：

- 物料主数据
- 物料品类
- 库存流水
- 物料申请单
- 申请明细
- 库存批量操作

## 下载备份

打开实时库存页并输入密码 `376493` 后，可以从飞书当前数据导出：

- 完整库存 Excel
- 完整库存 CSV
- 库存变更流水
- 当前筛选结果 Excel
- 当前筛选结果 CSV
