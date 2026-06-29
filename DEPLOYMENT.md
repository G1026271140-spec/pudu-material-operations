# 多人共用与部署说明

这个项目已经把实时库存主数据保存在 Streamlit 应用目录下：

- `data/inventory.xlsx`: 当前完整库存表
- `data/inventory.csv`: 当前完整库存表 CSV
- `data/options.json`: 表单下拉选项
- `data/transactions.csv`: 库存变更流水

所有入库、出库、新增物料品类操作都会直接更新这些应用内数据文件。实时库存页提供完整库存表和当前筛选结果的下载按钮。

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

需要注意：Streamlit Community Cloud 适合快速共享应用地址，但本地文件写入不保证长期持久化。因此如果采用 Community Cloud，请定期从实时库存页下载完整库存表备份。正式多人长期使用更推荐固定服务器或后续接入外部数据库。

## 下载备份

打开实时库存页并输入密码 `376493` 后，可以下载：

- 完整库存 Excel
- 完整库存 CSV
- 库存变更流水
- 当前筛选结果 Excel
- 当前筛选结果 CSV
