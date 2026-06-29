# PUDU 物料库存 Streamlit

这是一个本地 Git 项目，用 Streamlit 提供物料库存在线表单：

- 从 `data/source_materials.xlsx` 读取产品品类、型号、语种。
- 普通品类生成「品类 + 型号 + 语种」库存组合。
- 绿色底纹品类生成「品类 + 语种」库存组合，并把型号统一标记为「无需型号」。
- 支持一次提交多种物料的入库、出库和盘点修正。
- 实时库存查看页需要密码 `376493`。

## 运行

```powershell
cd "$env:USERPROFILE\Desktop\pudu-material-inventory"
pip install -r requirements.txt
streamlit run app.py
```

运行后打开：

- 库存更新表单: `http://localhost:8501`
- 实时库存表: `http://localhost:8501/?view=inventory`

实时库存页需要输入密码 `376493`。

## 数据文件

- `data/inventory.xlsx`: 完整库存表
- `data/inventory.csv`: 完整库存表 CSV
- `data/options.json`: 下拉选项和绿色品类规则
- `data/transactions.csv`: 每次库存变更流水

如需重新根据源表生成初始库存：

```powershell
python scripts/generate_inventory.py
```
