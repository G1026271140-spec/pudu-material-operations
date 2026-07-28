from __future__ import annotations

import re
from functools import wraps
from typing import Callable

import pandas as pd


LANGUAGE_ZH = "zh"
LANGUAGE_EN = "en"
SUPPORTED_UI_LANGUAGES = (LANGUAGE_ZH, LANGUAGE_EN)


# These mappings are presentation-only. Business values and Feishu field values
# must continue to use their original text.
ZH_DISPLAY_TEXT = {
    "客户名称 Customer Name": "客户名称",
    "国家 Country": "国家",
    "收件人信息 Recipient Information": "收件人信息",
    "运费的承担者 Freight Payer": "运费的承担者",
    "物料用途 Material Usage": "物料用途",
    "相关附件 Relevant Attachments": "相关附件",
    "物料申请清单 Material List": "物料申请清单",
    "物料品类(Material Category)": "物料品类",
    "产品型号(Product Model)": "产品型号",
    "语种(Language)": "语种",
    "现存物料数量(Material Quantity)": "现存物料数量",
    "库存登记": "物料申领",
}


EN_DISPLAY_TEXT = {
    # Brand, navigation, and shared controls.
    "营销物料中心": "Marketing Materials Center",
    "营销物料管理系统": "Marketing Materials System",
    "界面语言": "Interface Language",
    "语言设置": "Language",
    "工作台导航": "Workspace Navigation",
    "库存登记": "Material Request",
    "审批与发放": "Approval & Issuance",
    "物料管理": "Material Management",
    "物料仓库位置查询": "Warehouse Location Search",
    "采购补库": "Purchase Restock",
    "物料数据库": "Material Database",
    "品类管理": "Category Management",
    "修改与撤回": "Edit & Revoke",
    "数据同步": "Data Sync",
    "数据与系统": "Data & System",
    "数据与系统工具": "Data & System Tools",
    "更新全部数据缓存": "Refresh All Data",
    "发布 GitHub 静态缓存": "Publish GitHub Static Cache",
    "手动发布静态缓存": "Publish Static Cache Manually",
    "系统连接": "System Connection",
    "检查连接并刷新数据": "Check Connection & Refresh",
    "飞书多维表格连接成功": "Feishu Bitable connected",
    "飞书多维表格连接失败": "Feishu Bitable connection failed",
    "请在 Streamlit Secrets 中同时填写 FEISHU_APP_ID、FEISHU_APP_SECRET、FEISHU_BITABLE_APP_TOKEN。": (
        "Add FEISHU_APP_ID, FEISHU_APP_SECRET, and FEISHU_BITABLE_APP_TOKEN to Streamlit Secrets."
    ),
    "飞书多维表格读取失败，请先检查应用权限和多维表格授权。": (
        "Feishu Bitable could not be read. Check the app permissions and Bitable authorization."
    ),
    "当前飞书应用缺少多维表格读取权限。请在飞书开放平台给应用开通 bitable/base 表格读取权限，并确认该应用已添加到目标多维表格。": (
        "The Feishu app does not have Bitable read access. Enable the bitable/base read permissions in Feishu Open Platform and add the app to the target Bitable."
    ),
    "查看错误详情": "View Error Details",
    "飞书多维表格": "Feishu Bitable",
    "飞书实时数据": "Live Feishu data",
    "静态缓存": "Static cache",
    "部署静态缓存": "Deployment static cache",
    "服务缓存已刷新": "Runtime cache refreshed",
    "已读取": "Loaded",
    "未读取": "Not loaded",
    "刷新本页数据": "Refresh This Page",
    "刷新实时数据": "Refresh Live Data",
    "打开飞书物料主数据表": "Open Feishu Material Database",
    "返回库存管理": "Back to Inventory Management",
    "查看实时库存表": "View Live Inventory",
    "打开审批发放页": "Open Approval & Issuance",
    "管理功能": "Workspace View",
    "物料管理功能": "Material Management View",

    # Page headers and section titles.
    "飞书数据已连接": "Feishu data connected",
    "营销物料领取登记": "Marketing Material Request",
    "申请工作台": "Request Workspace",
    "登记客户、收件信息和领取明细，提交后进入审批发放流程。": (
        "Enter customer, recipient, and material details, then submit them for approval."
    ),
    "申请信息确认": "Request Review",
    "提交前核对": "Review Before Submission",
    "确认申请信息和全部物料明细后再同步至飞书。": (
        "Review the request and all material lines before syncing them to Feishu."
    ),
    "等待确认": "Awaiting Confirmation",
    "物料品类管理": "Material Category Management",
    "仓库位置图集": "Warehouse Location Gallery",
    "按物料、型号、语种、货架编号或位置说明查询存放位置。": (
        "Search storage locations by material, model, language, shelf, or location description."
    ),
    "静态位置缓存": "Static Location Cache",
    "本页面仅用于查询物料存放位置。如需拿取物料，请先提交物料申请。": (
        "This page only shows storage locations. Submit a material request before collecting any items."
    ),
    "搜索物料或位置": "Search Materials or Locations",
    "筛选货架": "Filter Shelf",
    "全部货架": "All Shelves",
    "位置图片集锦": "Location Gallery",
    "基础数据": "Master Data",
    "新增或调整物料品类、型号、语种和库存组合。": (
        "Add or update material categories, models, languages, and inventory combinations."
    ),
    "新增或调整品类名称、型号、语种和对应库存组合": (
        "Add or update category names, models, languages, and related inventory combinations"
    ),
    "搜索、编辑或删除物料主数据记录。": "Search, edit, or delete material master records.",
    "提交记录修改与撤回": "Edit or Revoke Submissions",
    "管理工作台": "Management Workspace",
    "筛选、修正或撤回库存提交记录。": "Filter, correct, or revoke inventory submissions.",
    "营销物料审批与发放": "Marketing Material Approval & Issuance",
    "审批工作台": "Approval Workspace",
    "核对申请明细、登记实际发放数量并同步库存流水。": (
        "Review request lines, enter issued quantities, and sync inventory transactions."
    ),
    "实时物料库存表": "Live Material Inventory",
    "库存视图": "Inventory View",
    "按物料品类、产品型号和语种查看当前库存与价值。": (
        "View current quantity and value by category, product model, and language."
    ),
    "申请与业务信息": "Request & Business Information",
    "填写领取申请的基础信息": "Enter the basic information for this request",
    "物料申请清单": "Material Request List",
    "申请物料清单": "Requested Materials",
    "选择申请物料": "Choose Materials",
    "像购物一样选择规格并加入采购车，最多 20 种": (
        "Choose options and add materials to your cart, up to 20 material types"
    ),
    "搜索物料": "Search Materials",
    "输入品类名称搜索": "Search by material category",
    "暂无图片": "No image available",
    "没有找到匹配的物料，请更换关键词。": (
        "No matching materials found. Try another keyword."
    ),
    "采购车为空，请先选择物料。": "Your cart is empty. Choose a material first.",
    "所选型号和语种之间没有有效的物料组合。": (
        "No valid material combination exists for the selected models and languages."
    ),
    "采购车": "Cart",
    "查看采购车": "View Cart",
    "型号多选": "Select Multiple Models",
    "语种多选": "Select Multiple Languages",
    "型号多选与语种多选不可同时开启；多选时填写的数量将应用到全部所选规格。": (
        "Model and language multi-select cannot be enabled together. "
        "The quantity entered in multi-select mode applies to every selected option."
    ),
    "种物料": "material types",
    "件": "units",
    "扇子": "Fan",
    "请核对完整申请内容后再提交": "Review the complete request before submission",
    "下载库存数据": "Download Inventory Data",
    "按需生成完整库存、筛选结果和库存流水文件": (
        "Generate full inventory, filtered results, and transaction files as needed"
    ),
    "库存提交记录": "Inventory Submission History",
    "筛选、修正或撤回库存变更流水": "Filter, correct, or revoke inventory transactions",
    "库存行维护": "Inventory Row Maintenance",
    "搜索、编辑或删除物料主数据记录": "Search, edit, or delete material master records",
    "库存数据看板": "Inventory Dashboard",
    "自定义查看库存规模、价值分布和预警状态": (
        "Customize inventory scale, value distribution, and alert views"
    ),
    "仅统计启用库存行，并自定义查看库存规模、价值分布和预警状态": (
        "Analyze active inventory rows only, with customizable scale, value, and alert views"
    ),
    "仅展示启用库存行；搜索、编辑或删除物料主数据记录": (
        "Show active inventory rows only; search, edit, or delete material master records"
    ),
    "看板设置": "Dashboard Settings",
    "显示内容": "Visible Modules",
    "低库存阈值": "Low-stock Threshold",
    "概览指标": "Overview Metrics",
    "品类库存数量": "Inventory Quantity by Category",
    "品类库存价值": "Inventory Value by Category",
    "语种分布": "Language Distribution",
    "语种库存分布": "Inventory by Language",
    "库存预警": "Inventory Alerts",
    "库存状态": "Inventory Status",
    "库存不足": "Insufficient Inventory",
    "库存充足": "Sufficient Inventory",
    "负库存": "Negative Inventory",
    "零库存": "Zero Inventory",
    "低库存": "Low Inventory",
    "正常库存": "Normal Inventory",
    "全部品类": "All Categories",
    "全部型号": "All Models",
    "全部语种": "All Languages",
    "全部状态": "All Statuses",
    "库存组合数": "Inventory Combinations",
    "负库存行": "Negative Inventory Rows",
    "零库存行": "Zero Inventory Rows",
    "物料品类维护": "Material Category Maintenance",
    "编辑品类规则或撤回未使用的品类": "Edit category rules or revoke unused categories",
    "待审批申请": "Pending Requests",
    "选择申请单并填写实际发放数量": "Select a request and enter actual issued quantities",
    "历史审批记录": "Approval History",
    "查看已完成审批及对应发放明细": "View completed approvals and issuance details",
    "库存筛选": "Inventory Filters",
    "库存明细": "Inventory Details",
    "待处理明细": "Pending Lines",
    "历史申请": "Historical Requests",
    "历史发放数量": "Historical Issued Quantity",
    "组合总数": "Total Combinations",
    "非零库存组合": "Non-zero Combinations",
    "库存总数量": "Total Inventory Quantity",
    "库存总价值": "Total Inventory Value",
    "品类基础信息": "Category Details",
    "配置品类名称、型号规则和可用语种": "Configure the category name, model rules, and languages",
    "库存工作台": "Inventory Workspace",
    "采购补库、品类维护与物料数据库统一管理。": (
        "Manage purchase restocking, categories, and the material database in one workspace."
    ),
    "采购补库信息": "Purchase Restock Information",
    "填写补库基础信息并逐条添加采购物料": (
        "Enter restock information and add purchased materials line by line"
    ),
    "采购补库清单": "Purchase Restock List",
    "补库信息确认": "Restock Review",
    "请核对补库信息和全部明细后再确认": (
        "Review the restock information and all lines before confirming"
    ),
    "补库明细预览": "Restock Line Preview",

    # Field labels and table headers.
    "申请信息": "Request Information",
    "业务信息": "Business Information",
    "申请标题": "Request Title",
    "标题": "Title",
    "申请单号": "Request No.",
    "申请部门": "Requesting Department",
    "申请人": "Applicant",
    "补库人": "Restock Operator",
    "补库单号": "Restock No.",
    "采购单号": "Purchase Order No.",
    "补库说明": "Restock Notes",
    "补库数量": "Restock Quantity",
    "补库总数量": "Total Restock Quantity",
    "补库物料种类": "Restock Material Types",
    "缓存库存": "Cached Inventory",
    "预计补库后库存": "Expected Inventory After Restock",
    "明细备注": "Line Remarks",
    "岗位": "Position",
    "客户名称": "Customer Name",
    "国家": "Country",
    "收件人信息": "Recipient Information",
    "运费的承担者": "Freight Payer",
    "运费承担者": "Freight Payer",
    "物料用途": "Material Usage",
    "相关附件": "Attachments",
    "物料种类": "Material Types",
    "申请总数量": "Total Requested Quantity",
    "附件数量": "Attachments",
    "物料品类": "Material Category",
    "产品型号": "Product Model",
    "语种": "Language",
    "数量": "Quantity",
    "备注": "Remarks",
    "序号": "No.",
    "申请数量": "Requested Quantity",
    "库存情况": "Inventory Status",
    "实际发放数量": "Actual Issued Quantity",
    "申请物料品类": "Requested Category",
    "申请产品型号": "Requested Model",
    "申请语种": "Requested Language",
    "实际发放品类": "Issued Category",
    "实际发放信息": "Actual Issuance",
    "实际发放编辑": "Actual Issuance Editing",
    "请根据申请明细填写实际发放物料与数量": (
        "Enter the actual issued materials and quantities based on the request details"
    ),
    "实际发放型号": "Issued Model",
    "实际发放语种": "Issued Language",
    "实际发放物料编码": "Issued Material Code",
    "实际发放物料品类": "Issued Material Category",
    "实际发放产品型号": "Issued Product Model",
    "当前库存快照": "Current Inventory Snapshot",
    "明细状态": "Line Status",
    "明细数": "Line Count",
    "状态": "Status",
    "记录ID": "Record ID",
    "选择": "Select",
    "时间": "Time",
    "操作": "Operation",
    "变更前数量": "Quantity Before",
    "变更后数量": "Quantity After",
    "现存物料数量": "Current Quantity",
    "单价": "Unit Price",
    "单价（美元）": "Unit Price (USD)",
    "现存物料总价值": "Total Inventory Value",
    "最后更新时间": "Last Updated",
    "物料编码": "Material Code",
    "海关编码": "Customs Code",
    "业务类型": "Business Type",
    "产品型号数量": "Product Model Count",
    "语种数量": "Language Count",
    "库存数量": "Inventory Quantity",
    "库存行数": "Inventory Row Count",
    "目标库存行": "Target Inventory Rows",
    "当前库存": "Current Inventory",
    "提交时库存快照": "Inventory at Submission",
    "总价值": "Total Value",
    "库存变化": "Inventory Change",
    "结果库存": "Resulting Inventory",
    "变更前": "Before",
    "变更后": "After",
    "关联申请单号": "Related Request No.",
    "关联申请明细": "Related Request Line",
    "关联明细": "Related Line",
    "品类关联": "Category Link",
    "明细编号": "Line No.",
    "申请总数": "Total Requested",
    "申请部门/区域": "Requesting Department / Region",
    "申请部门|区域": "Requesting Department / Region",
    "用途/活动": "Usage / Event",
    "用途|活动": "Usage / Event",
    "审批意见": "Approval Notes",
    "审批状态": "Approval Status",
    "操作状态": "Operation Status",
    "处理方式": "Processing Method",
    "流水类型": "Transaction Type",
    "启用状态": "Enabled Status",
    "是否启用": "Enabled",
    "是否无需型号": "No Model Required",
    "是否无需语种": "No Language Required",
    "用户编号": "User ID",
    "用户账号": "User Account",
    "角色": "Role",
    "客户": "Customer",
    "缺货说明": "Shortage Notes",
    "幂等键": "Idempotency Key",
    "申请状态": "Request Status",
    "申请时间": "Requested At",
    "审批时间": "Approved At",
    "提交时间": "Submitted At",
    "发生时间": "Occurred At",
    "发放时间": "Issued At",
    "撤回时间": "Revoked At",
    "实际发放总数": "Total Issued Quantity",
    "审批/发放备注": "Approval / Issuance Remarks",
    "撤回备注": "Revocation Remarks",
    "记录状态": "Record Status",
    "初始库存": "Initial Inventory",
    "当前组合": "Current Combinations",
    "目标组合": "Target Combinations",
    "新增组合": "New Combinations",
    "合并/删除行": "Rows to Merge / Delete",
    "库存组合明细": "Inventory Combination Details",
    "移除旧行": "Removed Existing Rows",
    "当前库存合计": "Current Inventory Total",
    "目标库存合计": "Target Inventory Total",
    "库存数量差额": "Inventory Quantity Difference",
    "库存数量 *": "Inventory Quantity *",
    "启用状态 *": "Enabled Status *",
    "品类启用状态 *": "Category Status *",
    "品类启用状态": "Category Status",
    "产品型号规则": "Product Model Rule",
    "语种规则": "Language Rule",
    "重组": "Reconfigured",
    "保留": "Retained",
    "新增": "New",
    "无需型号": "No Model Required",
    "无需语种": "No Language Required",
    "物料品类名称": "Material Category Name",
    "新增物料品类": "New Material Category",
    "新增品类": "Add Category",
    "编辑现有品类": "Edit Existing Category",
    "保存品类配置": "Save Category Settings",
    "创建物料品类": "Create Material Category",
    "品类信息确认": "Confirm Category Information",
    "确认基础信息后编辑每一条新增库存行": (
        "Confirm the category settings, then edit every new inventory row"
    ),
    "新增库存行预览": "New Inventory Row Preview",
    "逐行填写初始库存数量；确认创建前不会写入飞书": (
        "Enter the initial quantity for each row. Nothing is written to Feishu before confirmation"
    ),
    "确认创建品类": "Confirm Category Creation",
    "点击创建物料品类后，将先进入全部新增库存行预览页；最终确认前不会写入飞书。": (
        "Creating a category first opens a preview of all new inventory rows. Nothing is written to Feishu before final confirmation."
    ),
    "正在创建物料品类和库存行，请勿关闭页面......": (
        "Creating the material category and inventory rows. Keep this page open..."
    ),
    "创建物料品类失败，尚未完成全部库存行写入。请检查飞书数据后重试。": (
        "The material category could not be fully created. Check the Feishu data and try again."
    ),
    "预览库存行与目标型号、语种组合不一致，请返回修改后重新预览。": (
        "The preview rows do not match the target model and language combinations. Return to edit and preview again."
    ),
    "请先修正库存行数据后再返回。": "Correct the inventory row data before returning.",
    "请先修正全部库存行后再确认创建。": (
        "Correct every inventory row before confirming creation."
    ),
    "选择已有产品型号": "Select Existing Product Models",
    "选择已有语种": "Select Existing Languages",
    "自定义产品型号": "Custom Product Models",
    "自定义语种": "Custom Languages",
    "新增自定义型号": "Add Custom Models",
    "新增型号": "Add Models",
    "新增自定义语种": "Add Custom Languages",
    "修改已有型号": "Rename Existing Models",
    "选择要修改的型号": "Select a Model to Rename",
    "新的型号名称 *": "New Model Name *",
    "应用改名": "Apply Rename",
    "已设置": "Applied",
    "当前型号": "Current Model",
    "修改后型号": "Updated Model",
    "修改后型号 *": "Updated Model *",
    "该品类无需产品型号": "This category does not require a product model",
    "该品类无需语种": "This category does not require a language",
    "被取消型号的库存归并到": "Merge inventory from removed models into",
    "被取消语种的库存归并到": "Merge inventory from removed languages into",
    "被取消型号的库存归并到 *": "Merge inventory from removed models into *",
    "被取消语种的库存归并到 *": "Merge inventory from removed languages into *",
    "被取消型号的历史关联迁移到 *": "Move historical links from removed models to *",
    "被取消语种的历史关联迁移到 *": "Move historical links from removed languages to *",
    "新增组合初始库存": "Initial Quantity for New Combinations",
    "审批通过数量": "Approved Quantity",
    "原流水ID": "Original Transaction ID",

    # Form controls and commands.
    "请输入查看密码": "Enter access password",
    "请输入管理员密码": "Enter administrator password",
    "解锁": "Unlock",
    "密码不正确": "Incorrect password",
    "选择申请单": "Select Request",
    "查看历史审批明细": "View Approval Details",
    "返回修改": "Back to Edit",
    "确认提交": "Confirm & Submit",
    "预览并核对申请": "Review Request",
    "预览并核对补库": "Review Restock",
    "确认补库": "Confirm Restock",
    "物料品类名称 *": "Material Category Name *",
    "产品型号 *": "Product Models *",
    "语种 *": "Languages *",
    "选择物料品类": "Select Material Category",
    "操作类型": "Operation Type",
    "取消编辑": "Cancel Editing",
    "保存修改": "Save Changes",
    "加入清单": "Add to List",
    "选择规格": "Choose Options",
    "加入采购车": "Add to Cart",
    "编辑选中": "Edit Selected",
    "删除选中": "Delete Selected",
    "清空附件": "Clear Attachments",
    "上传或管理附件": "Upload or Manage Attachments",
    "生成或刷新下载文件": "Generate or Refresh Downloads",
    "下载完整库存 Excel": "Download Full Inventory Excel",
    "下载完整库存 CSV": "Download Full Inventory CSV",
    "下载库存变更流水": "Download Inventory Transactions",
    "下载当前筛选 Excel": "Download Filtered Excel",
    "下载当前筛选 CSV": "Download Filtered CSV",
    "开始日期": "Start Date",
    "结束日期": "End Date",
    "最多显示": "Maximum Rows",
    "按申请人筛选": "Filter by Applicant",
    "显示记录": "Displayed Records",
    "有效记录": "Valid Records",
    "库存净变化": "Net Inventory Change",
    "关联申请单": "Related Requests",
    "批量撤回备注": "Bulk Revocation Remarks",
    "确认批量撤回": "Confirm Bulk Revocation",
    "批量撤回选中提交": "Revoke Selected Submissions",
    "编辑选中提交": "Edit Selected Submission",
    "修正备注": "Correction Remarks",
    "确认撤回原记录并保存修正记录": "Confirm revocation and save the corrected record",
    "保存选中记录的编辑": "Save Selected Record",
    "搜索库存行": "Search Inventory Rows",
    "显示库存行": "Displayed Inventory Rows",
    "非零库存行": "Non-zero Inventory Rows",
    "库存合计": "Total Quantity",
    "确认批量删除": "Confirm Bulk Deletion",
    "批量删除选中库存行": "Delete Selected Inventory Rows",
    "编辑选中库存行": "Edit Selected Inventory Row",
    "保存选中库存行修改": "Save Inventory Row Changes",
    "显示品类": "Displayed Categories",
    "非零库存品类": "Categories with Inventory",
    "批量撤回选中品类": "Revoke Selected Categories",
    "编辑选中物料品类": "Edit Selected Category",
    "保存选中品类修改": "Save Category Changes",
    "撤回当前品类": "Revoke Current Category",
    "确认撤回该品类": "Confirm Category Revocation",
    "我已确认以上品类配置和库存组合": "I confirm the category settings and inventory combinations above",
    "确认直接舍弃未分配库存": "Confirm discarding unallocated inventory",
    "批量设置启用状态": "Set Status in Bulk",
    "库存组合编辑": "Edit Inventory Combinations",
    "选择要编辑的产品型号": "Select a Product Model",
    "选择要编辑的语种": "Select a Language",
    "当前组合处理方式": "Current Combination Action",
    "批量调整库存状态": "Update Inventory Status in Bulk",
    "选择库存组合": "Select Inventory Combinations",
    "应用到所选库存组合": "Apply to Selected Combinations",
    "应用到已勾选库存行": "Apply to Selected Inventory Rows",
    "保存实际发放并扣减库存": "Save Issuance & Update Inventory",
    "仅看非零库存": "Show Non-zero Inventory Only",
    "显示全部库存组合": "Show All Inventory Combinations",
    "请选择飞书部门": "Select a Feishu department",
    "输入姓名搜索申请人": "Search applicant by name",
    "全部申请人": "All applicants",
    "可选": "Optional",
    "可选，例如：0.06": "Optional, e.g. 0.06",
    "可选，例如：4911101000": "Optional, e.g. 4911101000",
    "物料编码 / 品类 / 型号 / 语种": "Material code / category / model / language",
    "请写明快递地址（包含收件人信息、邮编、具体地址）": (
        "Enter the delivery address, including recipient information, postal code, and street address"
    ),
    "活动物料请注明具体活动名称": "Specify the exact event name for promotional materials",
    "可用逗号、分号、顿号或换行分隔": "Separate entries with commas, semicolons, or line breaks",
    "例如：新版宣传册(New Brochure)": "Example: New Brochure",
    "修改后会同步更新当前品类下所有对应库存行；库存、单价、海关编码、启用状态和历史关联保持不变。": (
        "Renaming updates every matching inventory row in this category while preserving quantity, unit price, customs code, status, and historical links."
    ),
    "勾选后产品型号统一为“无需型号”，现有型号库存会自动归并。": (
        "When selected, all models use No Model Required and existing model inventory is merged automatically."
    ),
    "勾选后语种统一为“无需语种”，现有语种库存会自动归并。": (
        "When selected, all languages use No Language Required and existing language inventory is merged automatically."
    ),
    "勾选后产品型号统一为“无需型号”，库存数量可在下方库存组合编辑区重新分配。": (
        "When selected, the product model becomes No Model Required; redistribute quantities in the inventory combination editor below."
    ),
    "勾选后语种统一为“无需语种”，库存数量可在下方库存组合编辑区重新分配。": (
        "When selected, the language becomes No Language Required; redistribute quantities in the inventory combination editor below."
    ),
    "停用品类不会出现在物料申请页；历史库存和申请记录仍会保留。": (
        "Inactive categories are hidden from material requests while historical inventory and requests remain available."
    ),
    "单价和海关编码可留空；新增库存组合默认继承这里的值，也可在下方单独调整。": (
        "Unit price and customs code are optional. New inventory combinations inherit these defaults and can be adjusted individually below."
    ),
    "品类停用时，旗下所有库存组合会同步停用；重新启用品类后可再选择需要启用的库存行。": (
        "When a category is inactive, all of its inventory combinations are also deactivated. After reactivating the category, choose which inventory rows to enable."
    ),
    "这里只决定申请明细和流水的关联去向；库存数量请在下方库存组合编辑区填写。": (
        "This only controls where request and transaction links move; enter inventory quantities in the inventory combination editor below."
    ),
    "一次选择一个型号进行修改；应用后可继续选择其他型号，库存和历史关联保持不变。": (
        "Rename one model at a time. After applying a rename, select another model; inventory and historical links remain unchanged."
    ),
    "需要取消某项改名时，将新的型号名称改回原型号并再次应用。": (
        "To cancel a rename, change the new model name back to the original and apply it again."
    ),
    "选择一个型号和语种后编辑对应库存组合；切换到其他组合时，已经填写的内容会自动保留。": (
        "Select a model and language to edit one inventory combination. Your entries are preserved when switching combinations."
    ),
    "批量设置只更新当前页面状态，保存品类配置后才会同步至飞书。": (
        "Bulk updates remain on this page until you save the category settings, then they are synchronized to Feishu."
    ),
    "单个附件不超过 20 MB，最多上传 100 个。": "Each attachment must be 20 MB or smaller, with up to 100 files.",
    "被取消型号对应的库存、申请明细和流水关联会迁移到这里。": (
        "Inventory, request lines, and transaction links for removed models will be moved here."
    ),
    "被取消语种对应的库存、申请明细和流水关联会迁移到这里。": (
        "Inventory, request lines, and transaction links for removed languages will be moved here."
    ),
    "填写实际发放数量并保存后，系统会按该数量更新物料库存。": (
        "Enter the actual issued quantity and save to update material inventory by that amount."
    ),
    "物料品类(Material Category)": "Material Category",
    "产品型号(Product Model)": "Product Model",
    "语种(Language)": "Language",
    "现存物料数量(Material Quantity)": "Current Quantity",
    "客户名称 Customer Name": "Customer Name",
    "国家 Country": "Country",
    "收件人信息 Recipient Information": "Recipient Information",
    "运费的承担者 Freight Payer": "Freight Payer",
    "物料用途 Material Usage": "Material Usage",
    "相关附件 Relevant Attachments": "Attachments",
    "物料申请清单 Material List": "Material Request List",

    # Stored option values are translated only by widget formatters; their
    # original values are still returned to the application and written to Feishu.
    "物料领取（减少库存）": "Material Issuance (Decrease Inventory)",
    "物料采购（增加库存）": "Material Purchase (Increase Inventory)",
    "申请部门承担": "Requesting Department",
    "市场部承担": "Marketing Department",
    "客户承担": "Customer",
    "普渡付款(PUDU)": "PUDU",
    "其他": "Other",
    "待审批": "Pending",
    "部分发放": "Partially Issued",
    "已发放": "Issued",
    "已撤回": "Revoked",
    "有效": "Valid",
    "全部": "All",
    "无": "None",

    # Loading states, hints, and common messages.
    "物料数据加载中，请稍后......": "Loading material data, please wait...",
    "物料数据同步中，请稍后......": "Syncing material data, please wait...",
    "全部页面数据同步中，请稍后......": "Syncing data for all pages, please wait...",
    "正在同步本页数据，请稍后......": "Syncing this page, please wait...",
    "正在读取飞书审批数据，请稍后......": "Loading live approval data from Feishu, please wait...",
    "正在重新读取飞书审批数据，请稍后......": "Refreshing live approval data from Feishu, please wait...",
    "正在提交申请，请勿重复点击...": "Submitting the request. Please do not click again...",
    "申请已提交，正在通知审批人......": "Request submitted. Notifying approvers...",
    "正在读取部门成员，请稍后......": "Loading department members, please wait...",
    "正在生成下载文件...": "Generating download files...",
    "正在保存品类配置并同步关联数据，请勿关闭页面......": (
        "Saving category settings and syncing related data. Please keep this page open..."
    ),
    "正在发放并更新库存，请稍后......": "Issuing materials and updating inventory, please wait...",
    "审批已保存，正在向申请人发送结果......": "Approval saved. Sending the result to the applicant...",
    "正在提交 GitHub 缓存发布任务，请稍后......": "Starting the GitHub cache workflow, please wait...",
    "为加快页面打开速度，行数统计改为手动检查。": (
        "Row counts are checked manually to keep page loading fast."
    ),
    "当前没有可申请的物料品类，请先刷新数据或联系管理员。": (
        "No material categories are currently available. Refresh the data or contact an administrator."
    ),
    "部门成员读取失败，请刷新本页数据后重试。": (
        "Department members could not be loaded. Refresh this page and try again."
    ),
    "该部门暂无可选成员。": "No selectable members were found in this department.",
    "尚未添加申请物料。": "No requested materials have been added.",
    "暂无可编辑的物料品类，请先新增品类。": "No editable categories are available. Add a category first.",
    "暂无物料行。": "No material rows are available.",
    "暂无物料数据可供分析。": "No material data is available for analysis.",
    "当前筛选无可展示数据。": "No data is available for the current filters.",
    "当前筛选下没有库存预警。": "There are no inventory alerts for the current filters.",
    "当前看板筛选下暂无物料行。": "No material rows match the current dashboard filters.",
    "暂无物料品类。": "No material categories are available.",
    "暂无待审批或待发放的申请明细。": "No requests are awaiting approval or issuance.",
    "暂无历史审批记录。": "No approval history is available.",
    "该申请单暂无可显示的审批明细。": "This request has no approval details to display.",
    "该申请单为部分发放，审批已经完成。": "This request was partially issued and its approval is complete.",
    "点击上方按钮后会显示下载链接。筛选条件变化后请重新生成。": (
        "Download links appear after you use the button above. Regenerate them after changing filters."
    ),
    "开始日期不能晚于结束日期。": "The start date cannot be later than the end date.",
    "当前日期、状态和申请人筛选条件下暂无库存提交记录。": (
        "No inventory submissions match the selected date, status, and applicant filters."
    ),
    "仅允许删除库存为 0 且没有流水记录的库存行。": (
        "Only zero-quantity inventory rows with no transactions can be deleted."
    ),
    "仅允许撤回所有库存行为 0 且没有流水记录的品类。": (
        "Only categories whose inventory rows are all zero and have no transactions can be revoked."
    ),
    "仅允许撤回库存合计为 0 且没有库存流水的品类。": (
        "Only categories with zero total inventory and no transactions can be revoked."
    ),
    "只需填写新增组合；已有或归并组合会沿用并汇总当前库存。库存允许为负数。": (
        "Enter quantities only for new combinations. Existing or merged combinations retain and aggregate their current inventory. Negative quantities are allowed."
    ),
    "可直接填写每个组合的最终库存、单价和海关编码；单价与海关编码可留空。": (
        "Enter the final quantity, unit price, and customs code for each combination; unit price and customs code are optional."
    ),
    "可填写每个组合的最终库存、单价、海关编码和启用状态；单价与海关编码可留空。": (
        "Enter the final quantity, unit price, customs code, and status for each combination; unit price and customs code are optional."
    ),
    "请确认直接舍弃未分配库存。": "Confirm that unallocated inventory should be discarded.",
    "请检查库存组合中的数量、单价和海关编码。": (
        "Check the quantity, unit price, and customs code in the inventory combinations."
    ),
    "请检查库存组合中的数量、单价、海关编码和启用状态。": (
        "Check the quantity, unit price, customs code, and status in the inventory combinations."
    ),
    "单价（美元）必须填写有效数字。": "Unit price (USD) must be a valid number.",
    "单价（美元）不能小于 0。": "Unit price (USD) cannot be negative.",
    "请先在库存组合明细中勾选至少一行。": (
        "Select at least one row in the inventory combination details first."
    ),
    "批量设置会先更新当前表格，点击下方保存品类配置后才会同步至飞书。": (
        "Bulk changes update the current table first and sync to Feishu only after you save the category settings below."
    ),
    "勾选一条有效记录可编辑；勾选多条有效记录可批量撤回。": (
        "Select one valid record to edit, or multiple valid records to revoke them in bulk."
    ),
    "勾选一条库存行可编辑；勾选多条可批量删除。": (
        "Select one inventory row to edit, or multiple rows to delete them in bulk."
    ),
    "勾选一个品类可编辑；勾选多个可批量撤回。": (
        "Select one category to edit, or multiple categories to revoke them in bulk."
    ),
    "已选择多条记录，可批量撤回；如需编辑，请只勾选一条有效记录。": (
        "Multiple records are selected for bulk revocation. Select only one valid record to edit."
    ),
    "已选择多条库存行，可批量删除；如需编辑，请只勾选一条。": (
        "Multiple inventory rows are selected for bulk deletion. Select only one row to edit."
    ),
    "已选择多个品类，可批量撤回；如需编辑，请只勾选一个。": (
        "Multiple categories are selected for bulk revocation. Select only one category to edit."
    ),
    "请至少填写一项数量大于 0 的物料。": "Enter at least one material with a quantity greater than zero.",
    "请填写新增物料品类。": "Enter the new material category.",
    "请填写物料品类名称。": "Enter a material category name.",
    "请至少选择或填写一个语种。": "Select or enter at least one language.",
    "请至少选择或填写一个产品型号，或勾选“不按产品型号分类”。": (
        "Select or enter at least one product model, or choose no model classification."
    ),
    "请至少保留或新增一个产品型号，或勾选“无需产品型号”。": (
        "Keep or add at least one product model, or select No Model Required."
    ),
    "修改后的产品型号不能与其他已有型号重名。": (
        "The updated product model cannot duplicate another existing model."
    ),
    "如需取消产品型号，请使用“该品类无需产品型号”选项。": (
        "To remove product models, use the This category does not require a product model option."
    ),
    "请至少保留或新增一个语种，或勾选“无需语种”。": (
        "Keep or add at least one language, or select No Language Required."
    ),
    "请先勾选至少一条有效提交记录。": "Select at least one valid submission record.",
    "请先勾选至少一条库存行。": "Select at least one inventory row.",
    "请先勾选至少一个物料品类。": "Select at least one material category.",
    "请先勾选确认批量撤回。": "Confirm bulk revocation first.",
    "请先勾选确认批量删除。": "Confirm bulk deletion first.",
    "请先勾选确认修正。": "Confirm the correction first.",
    "请先勾选确认撤回。": "Confirm the revocation first.",
    "请先确认品类配置和库存组合。": "Confirm the category settings and inventory combinations first.",
    "请先选择部门": "Select a department first",
    "请选择飞书员工": "Select a Feishu employee",
    "请至少加入一种申请物料": "Add at least one requested material",
    "未上传附件": "No attachments uploaded",
    "未填写客户": "Customer not provided",
    "未填写国家": "Country not provided",
    "未设置状态": "Status not set",
    "待审批发放": "Pending Approval & Issuance",
    "已向申请人发送处理回执。": "A processing confirmation was sent to the applicant.",
    "已自动登记申请人的销售身份。": "The applicant was automatically registered with the Sales role.",
    "已向申请人发送审批结果。": "The approval result was sent to the applicant.",
    "已撤回原提交，并保存新的修正提交。": "The original submission was revoked and the corrected submission was saved.",
    "库存行信息已修改。": "The inventory row was updated.",
    "物料品类已修改。": "The material category was updated.",
    "GitHub 静态缓存更新任务已提交，完成后应用将自动重新部署。": (
        "The GitHub static cache workflow was started. The app will redeploy automatically when it finishes."
    ),
    "登记领取申请并提交至审批发放流程。": "Create a material request and submit it for approval and issuance.",
    "物料编码、物料品类和语种不能为空。": "Material code, category, and language are required.",
    "物料品类名称不能为空。": "Material category name is required.",
    "没有生成新的库存行，可能这些组合已经存在。": "No new inventory rows were generated; these combinations may already exist.",
    "没有写入新的库存行，可能这些组合已经存在。": "No new inventory rows were written; these combinations may already exist.",
    "该物料品类已存在。如需给已有品类补充型号或语种，可以先使用一个新的品类名称。": (
        "This material category already exists. Use a new category name if you need to add models or languages here."
    ),
    "检测到该品类选项已存在但没有库存行，本次会补建对应库存行。": (
        "The category option exists without inventory rows. The missing rows will be created."
    ),
    "该物料品类名称已经存在。": "This material category name already exists.",
    "选中记录包含已撤回或冲销记录，请取消这些记录后再操作。": (
        "The selection includes revoked or reversal records. Deselect those records before continuing."
    ),
    "本页数据刷新失败，请检查飞书连接和数据表权限。": (
        "This page could not be refreshed. Check the Feishu connection and table permissions."
    ),
    "数据库同步失败。": "Database synchronization failed.",
    "提交申请失败。请检查申请单/申请明细表字段、物料组合和飞书写入权限。": (
        "The request could not be submitted. Check the request tables, material combinations, and Feishu write permissions."
    ),
    "飞书多维表格库存更新失败。请检查应用是否有可编辑权限，关联字段和字段类型是否正确。": (
        "Inventory could not be updated in Feishu Bitable. Check edit permissions, linked fields, and field types."
    ),
    "该库存行已经有流水记录。为保证历史可追溯，请先撤回相关库存提交后再修改行信息。": (
        "This inventory row has transaction history. Revoke the related submissions before editing the row."
    ),
    "新的物料编码已经存在。": "The new material code already exists.",
    "新的“品类 + 型号 + 语种”组合已经存在。": "The new category, model, and language combination already exists.",
    "该品类、型号和语种的库存组合不存在或已停用，请重新选择。": (
        "This category, model, and language combination does not exist or is inactive. Select another combination."
    ),
    "该品类已有具体产品型号，不能直接改为无需型号。": (
        "This category has specific product models and cannot be changed directly to No Model Required."
    ),
    "该品类仍有按语种拆分的重复库存行，请先合并后再改为无需语种。": (
        "This category still has duplicate language-specific inventory rows. Merge them before selecting No Language Required."
    ),
    "新的物料品类名称已经存在。": "The new material category name already exists.",
    "该品类已有流水记录。为保证历史可追溯，请先撤回相关库存提交后再修改品类。": (
        "This category has transaction history. Revoke the related submissions before editing it."
    ),
    "批量撤回失败。请检查飞书应用是否有物料主数据和库存流水编辑权限。": (
        "Bulk revocation failed. Check the app's edit access to material master data and inventory transactions."
    ),
    "修正失败。请检查选中物料是否存在、飞书字段类型是否允许写入。": (
        "The correction failed. Check that the selected material exists and the Feishu field types allow writes."
    ),
    "批量删除库存行失败。": "Bulk inventory row deletion failed.",
    "批量撤回物料品类失败。": "Bulk category revocation failed.",
    "保存品类配置失败。数据未全部同步，请刷新页面检查飞书字段和关联后重试。": (
        "Category settings could not be saved completely. Refresh the page, check the Feishu fields and links, and try again."
    ),
    "修改失败。请检查飞书单选字段是否已有对应选项，或改为文本字段。": (
        "The update failed. Make sure the Feishu single-select fields contain the required options, or change them to text fields."
    ),
    "修改物料品类失败。请检查飞书单选字段是否已有对应选项，或改为文本字段。": (
        "The category update failed. Make sure the Feishu single-select fields contain the required options, or change them to text fields."
    ),
    "审批发放失败。请检查实际发放数量、申请明细字段和飞书写入权限。": (
        "Approval and issuance failed. Check the actual quantities, request-line fields, and Feishu write permissions."
    ),
}


def _translate_submission_suffix(value: str) -> str:
    translated = re.sub(
        r"机器人已提醒 (.+?) 位管理员。",
        lambda match: f"The bot notified {match.group(1)} administrators. ",
        value,
    )
    for source in (
        "已向申请人发送处理回执。",
        "已自动登记申请人的销售身份。",
    ):
        translated = translated.replace(source, str(EN_DISPLAY_TEXT[source]) + " ")
    return translated.strip()


_DYNAMIC_RULES: tuple[tuple[re.Pattern[str], Callable[[re.Match[str]], str]], ...] = (
    (
        re.compile(r"^数据来源：(.+?)　更新时间：(.+)$"),
        lambda match: (
            f"Data source: {translate_ui_text(match.group(1), LANGUAGE_EN)}  "
            f"Updated: {match.group(2)}"
        ),
    ),
    (
        re.compile(r"^当前存储：\*\*(.+?)\*\*$"),
        lambda match: f"Current storage: **{translate_ui_text(match.group(1), LANGUAGE_EN)}**",
    ),
    (
        re.compile(r"^当前存储：(.+)$"),
        lambda match: f"Current storage: {translate_ui_text(match.group(1), LANGUAGE_EN)}",
    ),
    (
        re.compile(r"^品类 (.+?) 条 / 库存 (.+?) 条 / 流水 (.+?) 条$"),
        lambda match: (
            f"Categories: {match.group(1)} / Inventory rows: {match.group(2)} / "
            f"Transactions: {match.group(3)}"
        ),
    ),
    (
        re.compile(r"^共 (.+?) 种物料$"),
        lambda match: f"{match.group(1)} material types",
    ),
    (
        re.compile(r"^逐条添加物料，最多 (.+?) 种$"),
        lambda match: f"Add materials one by one, up to {match.group(1)} types",
    ),
    (
        re.compile(r"^当前筛选显示 (.+?) 条物料组合$"),
        lambda match: f"{match.group(1)} material combinations match the current filters",
    ),
    (
        re.compile(r"^当前看板与下方明细联动，共显示 (.+?) 条库存组合。$"),
        lambda match: f"The dashboard and details are linked; {match.group(1)} inventory combinations are shown.",
    ),
    (
        re.compile(r"^发现 (.+?) 条启用库存预警：负库存 (.+?) 条，零库存 (.+?) 条，低库存 (.+?) 条。$"),
        lambda match: (
            f"Found {match.group(1)} alerts among active inventory: {match.group(2)} negative, "
            f"{match.group(3)} zero, and {match.group(4)} low-inventory rows."
        ),
    ),
    (
        re.compile(r"^启用库存组合 (.+?) 条；停用库存组合 (.+?) 条。$"),
        lambda match: (
            f"Active inventory combinations: {match.group(1)}; inactive combinations: {match.group(2)}."
        ),
    ),
    (
        re.compile(r"^下载文件生成时间：(.+?)。筛选条件变化后请重新生成。$"),
        lambda match: f"Downloads generated at {match.group(1)}. Regenerate them after changing filters.",
    ),
    (
        re.compile(r"^全部页面数据已同步，共 (.+?) 条记录；自动启用 (.+?) 条，自动停用 (.+?) 条。$"),
        lambda match: (
            f"All page data is synced. {match.group(1)} records loaded; "
            f"{match.group(2)} automatically enabled and {match.group(3)} automatically disabled."
        ),
    ),
    (
        re.compile(r"^本页数据已刷新，共同步 (.+?) 条记录。$"),
        lambda match: f"This page was refreshed with {match.group(1)} records.",
    ),
    (
        re.compile(r"^审批数据已刷新，共读取 (.+?) 条记录。$"),
        lambda match: f"Approval data was refreshed with {match.group(1)} records.",
    ),
    (
        re.compile(r"^已更新 (.+?) 项物料库存。$"),
        lambda match: f"Updated inventory for {match.group(1)} material items.",
    ),
    (
        re.compile(r"^客户：(.*)；国家：(.*)；申请人：(.*)；部门：(.*)$"),
        lambda match: (
            f"Customer: {match.group(1)}; Country: {match.group(2)}; "
            f"Applicant: {match.group(3)}; Department: {match.group(4)}"
        ),
    ),
    (
        re.compile(r"^物料用途：(.*)$"),
        lambda match: f"Material usage: {match.group(1)}",
    ),
    (
        re.compile(r"^第 (.+?) 条物料明细无效$"),
        lambda match: f"Material line {match.group(1)} is invalid",
    ),
    (
        re.compile(r"^第 (.+?) 条物料缺少品类、型号或语种$"),
        lambda match: f"Material line {match.group(1)} is missing a category, model, or language",
    ),
    (
        re.compile(r"^第 (.+?) 条物料数量必须大于 0$"),
        lambda match: f"The quantity on material line {match.group(1)} must be greater than zero",
    ),
    (
        re.compile(r"^一次申请最多可添加 (.+?) 种物料$"),
        lambda match: f"A request can contain up to {match.group(1)} material types",
    ),
    (
        re.compile(r"^请补充必填信息：(.*)$"),
        lambda match: "Complete the required fields: " + ", ".join(
            str(translate_ui_text(item, LANGUAGE_EN)) for item in match.group(1).split("、")
        ),
    ),
    (
        re.compile(r"^相关附件最多上传 (.+?) 个$"),
        lambda match: f"Up to {match.group(1)} attachments can be uploaded",
    ),
    (
        re.compile(r"^以下附件超过飞书单文件 20 MB 限制：(.*)$"),
        lambda match: f"These attachments exceed Feishu's 20 MB per-file limit: {match.group(1)}",
    ),
    (
        re.compile(r"^该物料组合已在清单第 (.+?) 行，请直接修改原行。$"),
        lambda match: f"This material combination is already on line {match.group(1)}. Edit that line instead.",
    ),
    (
        re.compile(r"^当前库存合计 (.+?)，流水 (.+?) 条，不能撤回。$"),
        lambda match: (
            f"This category cannot be revoked because its inventory total is {match.group(1)} "
            f"and it has {match.group(2)} transactions."
        ),
    ),
    (
        re.compile(r"^已提交申请单 (.+?)，共 (.+?) 条申请明细。(.*)$"),
        lambda match: (
            f"Request {match.group(1)} was submitted with {match.group(2)} lines. "
            f"{_translate_submission_suffix(match.group(3))}"
        ),
    ),
    (
        re.compile(r"^机器人已提醒 (.+?) 位管理员。$"),
        lambda match: f"The bot notified {match.group(1)} administrators.",
    ),
    (
        re.compile(r"^申请已成功，但申请人的销售权限自动登记失败：(.*)$"),
        lambda match: f"The request was submitted, but the applicant's Sales role could not be registered automatically: {match.group(1)}",
    ),
    (
        re.compile(r"^申请已成功，但机器人提醒发送失败。管理员可在审批页查看申请，并检查机器人权限或用户权限表：(.*)$"),
        lambda match: (
            "The request was submitted, but the bot notification failed. Administrators can view the request on the approval page; check bot permissions or the user permissions table: "
            + match.group(1)
        ),
    ),
    (
        re.compile(r"^申请人回执发送失败：(.*)$"),
        lambda match: f"The applicant confirmation could not be sent: {match.group(1)}",
    ),
    (
        re.compile(r"^物料品类“(.*)”已保存：目标组合 (.+?) 条，新增 (.+?) 条，归并删除 (.+?) 条，迁移关联 (.+?) 条。$"),
        lambda match: (
            f'Material category "{match.group(1)}" was saved: {match.group(2)} target combinations, '
            f"{match.group(3)} created, {match.group(4)} merged/deleted, and {match.group(5)} links migrated."
        ),
    ),
    (
        re.compile(r"^物料品类“(.*)”已保存：目标组合 (.+?) 条，新增 (.+?) 条，移除旧行 (.+?) 条，迁移关联 (.+?) 条，库存差额 (.+?)。$"),
        lambda match: (
            f'Material category "{match.group(1)}" was saved: {match.group(2)} target combinations, '
            f"{match.group(3)} created, {match.group(4)} existing rows removed, {match.group(5)} links migrated, "
            f"and an inventory difference of {match.group(6)}."
        ),
    ),
    (
        re.compile(r"^将直接舍弃 (.+?) 件未分配库存，此操作保存后不可自动恢复。$"),
        lambda match: (
            f"{match.group(1)} units of unallocated inventory will be discarded and cannot be restored automatically after saving."
        ),
    ),
    (
        re.compile(r"^目标库存将比当前库存增加 (.+?) 件。$"),
        lambda match: f"Target inventory will increase by {match.group(1)} units.",
    ),
    (
        re.compile(r"^请填写 (.+?) / (.+?) 的库存数量。$"),
        lambda match: f"Enter the inventory quantity for {match.group(1)} / {match.group(2)}.",
    ),
    (
        re.compile(r"^(.+?) / (.+?) 的单价不能小于 0。$"),
        lambda match: f"The unit price for {match.group(1)} / {match.group(2)} cannot be negative.",
    ),
    (
        re.compile(r"^已撤回物料品类“(.*)”。$"),
        lambda match: f'Revoked material category "{match.group(1)}".',
    ),
    (
        re.compile(r"^已撤回 (.+?) 条提交记录。$"),
        lambda match: f"Revoked {match.group(1)} submission records.",
    ),
    (
        re.compile(r"^已删除 (.+?) 条库存行。$"),
        lambda match: f"Deleted {match.group(1)} inventory rows.",
    ),
    (
        re.compile(r"^已撤回 (.+?) 个物料品类。$"),
        lambda match: f"Revoked {match.group(1)} material categories.",
    ),
    (
        re.compile(r"^审批已成功，但申请人结果通知发送失败：(.*)$"),
        lambda match: f"Approval succeeded, but the result could not be sent to the applicant: {match.group(1)}",
    ),
    (
        re.compile(r"^库存不足：(.*)。仍可调整实际发放物料或数量后继续审批。$"),
        lambda match: (
            f"Insufficient inventory: {match.group(1)}. "
            "You can still adjust the issued material or quantity and continue approval."
        ),
    ),
    (
        re.compile(r"^物料品类“(.*)”已创建，共生成 (.+?) 条库存行，初始库存合计 (.+?)。$"),
        lambda match: (
            f'Material category "{match.group(1)}" was created with {match.group(2)} inventory rows '
            f"and an initial inventory total of {match.group(3)}."
        ),
    ),
    (
        re.compile(r"^当前共 (.+?) 条库存行，初始库存合计 (.+?)。$"),
        lambda match: (
            f"{match.group(1)} inventory rows; initial inventory total: {match.group(2)}."
        ),
    ),
    (
        re.compile(r"^(.+?) 个型号$"),
        lambda match: f"{match.group(1)} models",
    ),
    (
        re.compile(r"^(.+?) 个语种$"),
        lambda match: f"{match.group(1)} languages",
    ),
    (
        re.compile(r"^以下实际发放组合不存在或已停用：(.*)$"),
        lambda match: f"These issued material combinations do not exist or are inactive: {match.group(1)}",
    ),
    (
        re.compile(r"^以下库存行不能删除：(.*)$"),
        lambda match: f"These inventory rows cannot be deleted: {match.group(1)}",
    ),
    (
        re.compile(r"^以下品类不能撤回：(.*)$"),
        lambda match: f"These categories cannot be revoked: {match.group(1)}",
    ),
    (
        re.compile(r"^已完成申请单 (.+?) 的审批，新增 (.+?) 条库存流水。(.*)$"),
        lambda match: (
            f"Completed approval for request {match.group(1)} and added {match.group(2)} inventory transactions. "
            f"{translate_ui_text(match.group(3), LANGUAGE_EN)}"
        ),
    ),
    (
        re.compile(r"^飞书通讯录暂时不可用，已切换为手动填写：(.*)$"),
        lambda match: f"The Feishu directory is temporarily unavailable. Switched to manual entry: {match.group(1)}",
    ),
    (
        re.compile(r"^暂时无法生成飞书物料主数据表链接：(.*)$"),
        lambda match: f"The Feishu material master data link is temporarily unavailable: {match.group(1)}",
    ),
    (
        re.compile(r"^当前默认只显示非零库存物料，但应用内库存数量目前全部为 0。完整物料组合仍有 (.+?) 条，取消“仅看有库存”即可查看。$"),
        lambda match: (
            "Only non-zero inventory is shown by default, but all current quantities are zero. "
            f"There are still {match.group(1)} material combinations; turn off the non-zero filter to view them."
        ),
    ),
)


def normalize_ui_language(value: object) -> str:
    return LANGUAGE_EN if str(value or "").lower() == LANGUAGE_EN else LANGUAGE_ZH


def translate_ui_text(value: object, language: str) -> object:
    if not isinstance(value, str):
        return value
    normalized_language = normalize_ui_language(language)
    if normalized_language == LANGUAGE_ZH:
        return ZH_DISPLAY_TEXT.get(value, value)
    exact = EN_DISPLAY_TEXT.get(value)
    if exact is not None:
        return exact
    for pattern, formatter in _DYNAMIC_RULES:
        match = pattern.fullmatch(value)
        if match:
            return formatter(match)
    if "；" in value and "<" not in value:
        return "; ".join(
            str(translate_ui_text(part, LANGUAGE_EN)) for part in value.split("；")
        )
    return value


def localize_column_config(
    data: object,
    column_config: object,
    language: str,
) -> object:
    if not isinstance(data, pd.DataFrame):
        return column_config
    localized = dict(column_config) if isinstance(column_config, dict) else {}
    for column in data.columns:
        current = localized.get(column)
        if isinstance(current, dict):
            current = dict(current)
            if current.get("label"):
                current["label"] = translate_ui_text(current["label"], language)
            else:
                current["label"] = translate_ui_text(str(column), language)
            if current.get("help"):
                current["help"] = translate_ui_text(current["help"], language)
            localized[column] = current
        elif current is None:
            localized[column] = {"label": translate_ui_text(str(column), language)}
    return localized


_PATCHED = False
_LANGUAGE_GETTER: Callable[[], str] = lambda: LANGUAGE_ZH


def install_streamlit_ui_translation(st_module: object, language_getter: Callable[[], str]) -> None:
    """Localize Streamlit's presentation layer without changing widget values."""
    global _PATCHED, _LANGUAGE_GETTER
    _LANGUAGE_GETTER = language_getter
    if _PATCHED:
        return

    from streamlit.delta_generator import DeltaGenerator

    text_methods = {
        "button",
        "caption",
        "checkbox",
        "date_input",
        "download_button",
        "error",
        "expander",
        "file_uploader",
        "form_submit_button",
        "header",
        "info",
        "link_button",
        "markdown",
        "metric",
        "multiselect",
        "number_input",
        "popover",
        "radio",
        "selectbox",
        "spinner",
        "subheader",
        "success",
        "text_area",
        "text_input",
        "title",
        "toggle",
        "warning",
        "write",
    }
    option_methods = {"multiselect", "radio", "selectbox"}
    table_methods = {"data_editor", "dataframe"}
    all_methods = text_methods | table_methods | {"tabs"}

    for method_name in all_methods:
        original = getattr(DeltaGenerator, method_name, None)
        if original is None:
            continue

        def build_wrapper(name: str, original_method: Callable[..., object]) -> Callable[..., object]:
            @wraps(original_method)
            def localized(self: object, *args: object, **kwargs: object) -> object:
                language = normalize_ui_language(_LANGUAGE_GETTER())
                localized_args = list(args)
                localized_kwargs = dict(kwargs)

                if name in text_methods:
                    if localized_args and isinstance(localized_args[0], str):
                        localized_args[0] = translate_ui_text(localized_args[0], language)
                    elif isinstance(localized_kwargs.get("label"), str):
                        localized_kwargs["label"] = translate_ui_text(
                            localized_kwargs["label"], language
                        )
                    for key in ("help", "placeholder"):
                        if isinstance(localized_kwargs.get(key), str):
                            localized_kwargs[key] = translate_ui_text(
                                localized_kwargs[key], language
                            )

                if name == "write":
                    localized_args = [
                        translate_ui_text(item, language) if isinstance(item, str) else item
                        for item in localized_args
                    ]

                if name in option_methods:
                    formatter = localized_kwargs.get("format_func", str)

                    def localized_formatter(option: object, base: Callable[[object], object] = formatter) -> object:
                        return translate_ui_text(base(option), language)

                    localized_kwargs["format_func"] = localized_formatter

                if name == "tabs" and localized_args:
                    labels = localized_args[0]
                    if isinstance(labels, (list, tuple)):
                        localized_args[0] = [
                            translate_ui_text(label, language) for label in labels
                        ]

                if name in table_methods:
                    data = localized_args[0] if localized_args else localized_kwargs.get("data")
                    localized_kwargs["column_config"] = localize_column_config(
                        data,
                        localized_kwargs.get("column_config"),
                        language,
                    )

                return original_method(self, *localized_args, **localized_kwargs)

            return localized

        setattr(DeltaGenerator, method_name, build_wrapper(method_name, original))

    # Streamlit exposes bound methods at module level. Rebind them so direct
    # calls such as st.button and calls on columns/sidebar use the same wrapper.
    main_delta = getattr(st_module, "_main", None)
    if main_delta is not None:
        for method_name in all_methods:
            if hasattr(main_delta, method_name):
                setattr(st_module, method_name, getattr(main_delta, method_name))
    _PATCHED = True
