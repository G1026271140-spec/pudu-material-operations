# 飞书 aPaaS 云函数落地步骤

本文档用于把物料申请与库存系统里的关键业务规则落到飞书 aPaaS 云函数中。

## 先做哪几个

不要一开始写完全部函数。推荐顺序：

1. `apply_inventory_change`：库存变更唯一入口。
2. `batch_issue_request_lines`：市场批量发放，调用第 1 个函数。
3. `submit_material_request`：销售提交申请。
4. `approve_material_request`：市场审批通过/驳回。
5. `revert_inventory_ledger`：撤回库存流水。

第一阶段只要 `apply_inventory_change` 和 `batch_issue_request_lines` 跑通，就能实现库存不足拦截、重复扣库存拦截、实际发放写流水。

## 云函数创建方式

在飞书 aPaaS 应用开发后台：

1. 进入应用。
2. 打开低代码开发区域。
3. 找到函数/云函数。
4. 点击新建。
5. 名称填中文，API 名称填英文。
6. 选择 Node.js。
7. 保存后进入 WebIDE。
8. 先写入参解析、返回值和日志。
9. 用测试入参调试。
10. 发布。
11. 在页面按钮或流程动作里调用该 API 名称。

## 1. apply_inventory_change

中文名称：库存变更写流水

API 名称：

```text
apply_inventory_change
```

用途：所有库存变化都必须经过这个函数。采购入库、销售出库、盘点调整、撤回冲销都调用它。

入参建议：

```json
{
  "material_code": "MAT-0001",
  "ledger_type": "销售领用出库",
  "quantity_delta": -5,
  "source_request_no": "REQ-DEMO-0001",
  "source_line_no": "LINE-DEMO-0001",
  "idempotency_key": "issue:LINE-DEMO-0001",
  "operator": "市场李四",
  "note": "实际发放"
}
```

返回值建议：

```json
{
  "success": true,
  "ledger_no": "TX-20260702-0001",
  "before_stock": 50,
  "after_stock": 45,
  "message": "库存已更新"
}
```

核心校验：

1. `material_code` 必填。
2. `ledger_type` 必填。
3. `quantity_delta` 不能为 0。
4. `idempotency_key` 必填且不能重复。
5. 查询物料主数据。
6. 读取 `当前库存`。
7. 计算 `after_stock = before_stock + quantity_delta`。
8. 如果是出库，且 `after_stock < 0`，直接返回库存不足。
9. 新增库存流水。
10. 更新物料主数据的 `当前库存`。

伪代码：

```js
async function applyInventoryChange(input, context) {
  const {
    material_code,
    ledger_type,
    quantity_delta,
    source_request_no = "",
    source_line_no = "",
    idempotency_key,
    operator = "",
    note = ""
  } = input;

  assert(material_code, "物料编码不能为空");
  assert(ledger_type, "流水类型不能为空");
  assert(Number(quantity_delta) !== 0, "数量变化不能为 0");
  assert(idempotency_key, "幂等键不能为空");

  const existed = await findOne("库存流水", { "幂等键": idempotency_key });
  if (existed) {
    return {
      success: true,
      duplicated: true,
      ledger_no: existed["流水编号"],
      message: "该操作已执行过，本次不重复扣库存"
    };
  }

  const material = await findOne("物料主数据", { "物料编码": material_code });
  assert(material, `未找到物料：${material_code}`);
  assert(material["启用状态"] === "启用", `物料已停用：${material_code}`);

  const beforeStock = Number(material["当前库存"] || 0);
  const afterStock = beforeStock + Number(quantity_delta);

  if (Number(quantity_delta) < 0 && afterStock < 0) {
    return {
      success: false,
      code: "INSUFFICIENT_STOCK",
      before_stock: beforeStock,
      after_stock: afterStock,
      message: `库存不足，当前库存 ${beforeStock}，本次需要 ${Math.abs(Number(quantity_delta))}`
    };
  }

  const ledgerNo = await nextNo("TX");
  await create("库存流水", {
    "流水编号": ledgerNo,
    "发生时间": now(),
    "流水类型": ledger_type,
    "物料编码": material_code,
    "数量变化": Number(quantity_delta),
    "变更前库存": beforeStock,
    "变更后库存": afterStock,
    "关联申请单号": source_request_no,
    "关联明细编号": source_line_no,
    "幂等键": idempotency_key,
    "操作人": operator || context.user?.name || "",
    "操作状态": "有效",
    "备注": note
  });

  await update("物料主数据", material.id, {
    "当前库存": afterStock
  });

  return {
    success: true,
    ledger_no: ledgerNo,
    before_stock: beforeStock,
    after_stock: afterStock,
    message: "库存已更新"
  };
}
```

注意：上面 `findOne/create/update/nextNo/now/assert` 是逻辑占位函数。飞书 WebIDE 里实际操作数据对象的 SDK 方法名，需要以你当前函数模板自动生成的 SDK 为准。先把这个逻辑放进去，再把这些占位函数替换成飞书 SDK 的实际查询、新增、更新方法。

## 2. batch_issue_request_lines

中文名称：批量发放申请明细

API 名称：

```text
batch_issue_request_lines
```

入参建议：

```json
{
  "line_nos": ["LINE-DEMO-0001", "LINE-DEMO-0002"],
  "operator": "市场李四"
}
```

核心逻辑：

1. 查询每条申请明细。
2. 校验 `明细状态 = 待发放`。
3. 校验 `实际发放数量 > 0`。
4. 校验 `实际发放数量 <= 审批通过数量`。
5. 校验没有 `出库流水编号`。
6. 对每条明细调用 `apply_inventory_change`。
7. 成功则写回 `出库流水编号`、`发放人`、`发放时间`、`明细状态 = 已发放`。
8. 库存不足则该行标记 `缺货` 或保留 `待发放` 并写入缺货说明。
9. 汇总成功/失败结果。

入参返回示例：

```json
{
  "success": false,
  "total": 2,
  "success_count": 1,
  "fail_count": 1,
  "results": [
    {
      "line_no": "LINE-DEMO-0001",
      "success": true,
      "ledger_no": "TX-20260702-0001"
    },
    {
      "line_no": "LINE-DEMO-0002",
      "success": false,
      "message": "库存不足"
    }
  ]
}
```

## 3. submit_material_request

中文名称：提交物料申请

API 名称：

```text
submit_material_request
```

触发位置：销售申请页的“提交审批”按钮。

核心逻辑：

1. 查询申请单和申请明细。
2. 校验申请单必填项。
3. 校验至少一条明细。
4. 校验申请数量都大于 0。
5. 写入每条明细的 `提交时库存快照`。
6. 申请单状态改为 `待审批`。
7. 明细状态改为 `待审批`。
8. 推送市场审批提醒。

## 4. approve_material_request

中文名称：审批物料申请

API 名称：

```text
approve_material_request
```

触发位置：市场审批工作台的“通过/驳回”按钮。

入参：

```json
{
  "request_no": "REQ-DEMO-0001",
  "action": "approve",
  "comment": ""
}
```

核心逻辑：

- `action = reject`：申请单改为 `已驳回`，写审批意见。
- `action = approve`：
  1. 校验每条明细的审批通过数量。
  2. 默认 `审批通过数量 = 申请数量`。
  3. 申请单改为 `待发放`。
  4. 明细改为 `待发放`。
  5. 推送市场发放提醒。

## 5. revert_inventory_ledger

中文名称：撤回库存流水

API 名称：

```text
revert_inventory_ledger
```

核心逻辑：

1. 查询原流水。
2. 原流水必须是 `有效`。
3. 新增一条反向流水，`数量变化 = -原数量变化`。
4. 原流水状态改为 `已撤回`。
5. 新流水状态为 `冲销记录`。
6. 更新物料主数据当前库存。

## 页面按钮怎么接

### 销售申请页

按钮：提交审批

调用：

```text
submit_material_request
```

传参：

```json
{
  "request_no": 当前申请单.申请单号
}
```

### 市场审批页

按钮：通过

调用：

```text
approve_material_request
```

传参：

```json
{
  "request_no": 当前申请单.申请单号,
  "action": "approve",
  "comment": 审批意见
}
```

按钮：驳回

传参：

```json
{
  "request_no": 当前申请单.申请单号,
  "action": "reject",
  "comment": 审批意见
}
```

### 市场发放页

按钮：批量发放

调用：

```text
batch_issue_request_lines
```

传参：

```json
{
  "line_nos": 选中的明细编号数组,
  "operator": 当前用户姓名
}
```

## 测试顺序

1. 在 `物料主数据` 找一条物料，把当前库存改成 10。
2. 测试 `apply_inventory_change` 入库 5，确认库存从 10 变 15，并生成流水。
3. 测试 `apply_inventory_change` 出库 3，确认库存从 15 变 12，并生成流水。
4. 测试重复传同一个 `idempotency_key`，确认不会重复扣库存。
5. 测试出库 999，确认返回库存不足，且不生成流水。
6. 测试 `batch_issue_request_lines`，确认成功行写回流水编号，失败行保留错误原因。

## 最容易踩的坑

- 页面直接改 `当前库存`：不要这样做，必须通过云函数写流水。
- 没有幂等键：按钮双击或流程重试会重复扣库存。
- 先更新库存再写流水：失败时会账实不一致。建议先算好，再在同一个函数里连续写流水和更新库存。
- 发放数量没有重新查库存：审批时看到的库存可能已经过期，出库前必须重新查。
- 明细重复发放：只要已有 `出库流水编号`，就不能再次发放。

