# PUDU 物料库存 Streamlit

这是一个本地 Git 项目，用 Streamlit 提供物料库存在线表单：

- 从 `data/source_materials.xlsx` 读取产品品类、型号、语种。
- 普通品类生成「品类 + 型号 + 语种」库存组合。
- 绿色底纹品类生成「品类 + 语种」库存组合，并把型号统一标记为「无需型号」。
- 支持一次提交多种物料的入库、出库和盘点修正。
- 支持新增物料品类，可多选已有产品型号和语种，也可自定义新增型号和语种。
- 新增品类后会自动生成库存行，并同步更新库存更新表单的下拉选项。
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
