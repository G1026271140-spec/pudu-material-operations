# 业务字段、编辑选项与飞书映射

生成依据：当前 React/FastAPI 代码及应用身份导出的实际飞书字段元数据。

发货模板、发货排期按用户要求保持现状，不创建字段定义。以下为主业务表的完整数据库映射，含关联/流程字段，不能将所有流程字段作为普通输入框直接覆盖。

共 23 张来源表、364 个字段（分别注册主业务库及企业文化衫行政源表）。每个字段均保留稳定字段 ID、类型化 SQL 列和原始 JSON 值。

具体页面的业务输入、派生值和权限规则见 [页面字段说明](frontend-edit-contract.md)。机器可读定义为 config/frontend_field_contracts.json。

## 物料主数据

来源：`primary`；实际表名：物料主数据；表 ID：`tbl4UsiEmprnImIY`。

| 字段 | 字段 ID / SQL 列 | 飞书类型 / SQL 类型 | 编辑选项及写入路径 |
|---|---|---|---|
| 物料编码 | `fld2UhHKQd` / `f_fld2UhHKQd` | 文本 / text | 文本；管理员编辑 |
| 物料品类 | `fld3d0RBks` / `f_fld3d0RBks` | 文本 / text | 文本；管理员编辑 |
| 产品型号 | `fld26DOsnW` / `f_fld26DOsnW` | 文本 / text | 文本；管理员编辑 |
| 语种 | `fldwFzY0cn` / `f_fldwFzY0cn` | 文本 / text | 文本；管理员编辑 |
| 当前库存 | `fldxI2P07C` / `f_fldxI2P07C` | 数字 / numeric | 数字；管理员库存调整/补库/配货；同时记录库存流水 |
| 在途库存 | `fld7MD4420` / `f_fld7MD4420` | 数字 / numeric | 数字；管理员库存调整/补库/配货；同时记录库存流水 |
| 是否在申领页显示 | `flddAKyNWW` / `f_flddAKyNWW` | 单选 / text | 单选下拉；管理员编辑；选项：是、否 |
| 启用状态 | `fld2FBhXyL` / `f_fld2FBhXyL` | 单选 / text | 单选下拉；管理员编辑；选项：启用、停用 |
| 是否临时物料 | `fldqdnsA2x` / `f_fldqdnsA2x` | 单选 / text | 单选下拉；管理员编辑；选项：是、否 |
| 单价（美元） | `fldM98XVQT` / `f_fldM98XVQT` | 数字 / numeric | 数字；管理员编辑 |
| 单价（人民币） | `flddFgwqE1` / `f_flddFgwqE1` | 公式 / jsonb | 显示及源字段入口；源字段编辑 |
| 海关编码 | `fldIYVotBW` / `f_fldIYVotBW` | 数字 / numeric | 数字；管理员编辑 |
| 品类关联 | `fldMePIniD` / `f_fldMePIniD` | 双向关联 / jsonb | 关联记录选择；管理员选择关联记录；通过对应业务服务维护双向关联 |
| 型号关联 | `fldFeKk2zw` / `f_fldFeKk2zw` | 双向关联 / jsonb | 关联记录选择；管理员选择关联记录；通过对应业务服务维护双向关联 |
| 语种关联 | `fld1lKlPjC` / `f_fld1lKlPjC` | 双向关联 / jsonb | 关联记录选择；管理员选择关联记录；通过对应业务服务维护双向关联 |
| 库存归零时间 | `fldwBOsC64` / `f_fldwBOsC64` | 文本 / text | 文本；管理员编辑 |
| 申请明细 | `fldtNK1jaN` / `f_fldtNK1jaN` | 双向关联 / jsonb | 关联记录选择；管理员选择关联记录；通过对应业务服务维护双向关联 |
| 库存流水 | `fld6qyIeal` / `f_fld6qyIeal` | 双向关联 / jsonb | 关联记录选择；管理员选择关联记录；通过对应业务服务维护双向关联 |
| 备注 | `fld1Y9bf2w` / `f_fld1Y9bf2w` | 文本 / text | 文本；管理员编辑 |
| 仓库物料位置 | `fldl1JuFXD` / `f_fldl1JuFXD` | 双向关联 / jsonb | 关联记录选择；管理员选择关联记录；通过对应业务服务维护双向关联 |
| 物料货架 | `fldr3SpFag` / `f_fldr3SpFag` | 双向关联 / jsonb | 关联记录选择；管理员选择关联记录；通过对应业务服务维护双向关联 |
| 物料申请单 | `fldT5Va9NV` / `f_fldT5Va9NV` | 双向关联 / jsonb | 关联记录选择；管理员选择关联记录；通过对应业务服务维护双向关联 |
| 战区管理 | `fldbk7CsUV` / `f_fldbk7CsUV` | 双向关联 / jsonb | 关联记录选择；管理员选择关联记录；通过对应业务服务维护双向关联 |
| 父记录 | `fldvYoUQp0` / `f_fldvYoUQp0` | 单向关联 / jsonb | 关联记录选择；管理员选择关联记录；通过对应业务服务维护双向关联 |

## 文化周边管理库存

来源：`primary`；实际表名：文化周边管理库存；表 ID：`tblu3wRpylTj6zJl`。

| 字段 | 字段 ID / SQL 列 | 飞书类型 / SQL 类型 | 编辑选项及写入路径 |
|---|---|---|---|
| 文化周边编码 | `fldcoomJKh` / `f_fldcoomJKh` | 文本 / text | 文本；管理员编辑 |
| 物料品类 | `fldePaHkZ7` / `f_fldePaHkZ7` | 文本 / text | 文本；管理员编辑 |
| 产品型号 | `fldJuPoKgn` / `f_fldJuPoKgn` | 文本 / text | 文本；管理员编辑 |
| 战区管理 | `flde4JIHir` / `f_flde4JIHir` | 单选 / text | 单选下拉；管理员编辑；选项：美洲战区、日本战队、电商（海外）、大中华战区、电商（国内）、品牌&市场营销内部、亚太战区、欧洲战区、HMT战队、澳新战队 |
| 当前库存 | `fld5XxOhp9` / `f_fld5XxOhp9` | 数字 / numeric | 数字；管理员库存调整/补库/配货；同时记录库存流水 |
| 是否可以申领 | `fldxI7a91u` / `f_fldxI7a91u` | 单选 / text | 单选下拉；管理员编辑；选项：是、否 |
| 备注 | `fldRxdcq9Q` / `f_fldRxdcq9Q` | 文本 / text | 文本；管理员编辑 |
| 申请明细 | `fldJabz3qK` / `f_fldJabz3qK` | 双向关联 / jsonb | 关联记录选择；管理员选择关联记录；通过对应业务服务维护双向关联 |
| 库存流水 | `fld7NtPRmz` / `f_fld7NtPRmz` | 双向关联 / jsonb | 关联记录选择；管理员选择关联记录；通过对应业务服务维护双向关联 |
| 物料品类关联 | `fldO5JJjr5` / `f_fldO5JJjr5` | 双向关联 / jsonb | 关联记录选择；管理员选择关联记录；通过对应业务服务维护双向关联 |
| 产品型号关联 | `fldBp7xfWQ` / `f_fldBp7xfWQ` | 双向关联 / jsonb | 关联记录选择；管理员选择关联记录；通过对应业务服务维护双向关联 |
| 战区关联 | `fldGbohvWw` / `f_fldGbohvWw` | 双向关联 / jsonb | 关联记录选择；管理员选择关联记录；通过对应业务服务维护双向关联 |
| 单价（人民币） | `fld3dNnFaZ` / `f_fld3dNnFaZ` | 数字 / numeric | 数字；管理员编辑 |

## 物料申请单

来源：`primary`；实际表名：物料申请单；表 ID：`tbl3eyt8lkl3uQa1`。

| 字段 | 字段 ID / SQL 列 | 飞书类型 / SQL 类型 | 编辑选项及写入路径 |
|---|---|---|---|
| 申请单号 | `fldIKaRgYM` / `f_fldIKaRgYM` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 申请类型 | `fldrmZXQiV` / `f_fldrmZXQiV` | 单选 / text | 单选下拉；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验；选项：普通物料申请、文化周边申请、企业文化衫领取、 |
| 申请人 | `fldvY7xX7F` / `f_fldvY7xX7F` | 人员 / jsonb | 人员选择；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 申请人.部门 | `fld2gDwsST` / `f_fld2gDwsST` | 多选 / jsonb | 多选；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验；选项：营销运营组、美国战队、市场营销部、解决方案部、解决方案中台组、CR业务部、亚太服务部、区域市场组、国内商务交付组、拉美战队、法国战队、日本CR业务组、IR业务部、日本服务组、行政服务部、大中华战区、HMT战队、美澳英战区、中东战队、马来战队、亚太战区、新加坡战队、泰国战队、加拿大战队、德国CR业务组、X LAB、欧洲服务A组、产品营销组、视觉设计组、品牌部、美英OR业务部、海外市场营销组、欧洲IR业务部、日本战队、欧洲服务B组、IR&GR服务组、国内市场营销组、美国KA组、韩国服务组、HMT服务组、项目交付组、服务运营组、服务代表组、大中华服务部、HR业务部、欧洲OR业务部、软件平台架构部、IRPBU、产品市场部、西葡战队、欧洲GR业务部、硬件平台部电机组、运维组、生命周期工具链团队、美洲服务部、校招组、SRPBU硬件组、通用调度团队、海外商务交付组、渠道管理组、英爱战队、GR业务部、SRPBU机械组、KA业务部、质量代表组、SR3D业务部、公共事务部、荷比卢战队、欧日韩战区、中东欧战队、COE、IR部、平台软件测试组、德瑞奥战队、IR测试组、X LAB测试组、销售运营组、采购开发组、ORPBU测试组 |
| 提交人 | `fldHSslDVT` / `f_fldHSslDVT` | 人员 / jsonb | 人员选择；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 所属战区 | `fldTlkQNMU` / `f_fldTlkQNMU` | 单选 / text | 单选下拉；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验；选项：美洲战区、澳新战队、日本战队、亚太战区、大中华战区、欧洲战区、HMT战队、品牌&市场营销内部、电商（国内）、电商（海外）、欧洲战区、品牌&市场营销内部、亚太战区、电商（国内）、品牌&市场营销内部、大中华战区、电商（国内）、品牌&市场营销内部、欧洲战区、电商（海外）、日本战队、电商（海外）、美洲战区、品牌&市场营销内部、大中华战区、电商（国内）、日本战队、品牌&市场营销内部 |
| 客户名称 | `fldwub0TgZ` / `f_fldwub0TgZ` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 国家 | `fldiBYPjyD` / `f_fldiBYPjyD` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 收件人信息 | `fldgReTLDP` / `f_fldgReTLDP` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 运费承担者 | `fldan3JSkP` / `f_fldan3JSkP` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 用途\|活动 | `fld7zkjoNr` / `f_fld7zkjoNr` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 物料明细 | `fldxKqZaya` / `f_fldxKqZaya` | 双向关联 / jsonb | 关联记录选择；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 物料明细文字信息 | `fldhiCjYok` / `f_fldhiCjYok` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 计划库存核实时间 | `fldCGPgaxI` / `f_fldCGPgaxI` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 库存核实提醒状态 | `fldxuAiGYJ` / `f_fldxuAiGYJ` | 单选 / text | 单选下拉；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验；选项：待提醒、已提醒、无需提醒 |
| 临时物料清理状态 | `fldVDVdk5o` / `f_fldVDVdk5o` | 单选 / text | 单选下拉；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验；选项：无临时物料、待清理、已清理、清理失败 |
| 审批状态 | `fld1u1vvtD` / `f_fld1u1vvtD` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 申请部门\|区域 | `fld2BUOnMw` / `f_fld2BUOnMw` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 业务类型 | `fld1ajV6hQ` / `f_fld1ajV6hQ` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 审批意见 | `fld9BmiEH3` / `f_fld9BmiEH3` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 提交时间 | `fld2KQmT2w` / `f_fld2KQmT2w` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 审批时间 | `fld21BlOuh` / `f_fld21BlOuh` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 备注 | `fld5HODlXJ` / `f_fld5HODlXJ` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 申请明细 | `fldkaC2CtD` / `f_fldkaC2CtD` | 双向关联 / jsonb | 关联记录选择；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 库存流水 | `fldUgdNAWa` / `f_fldUgdNAWa` | 数字 / numeric | 数字；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 物料用途 | `fldp5QU0Vb` / `f_fldp5QU0Vb` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 标题 | `fldp331NUd` / `f_fldp331NUd` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 费用合计（人民币） | `fldyn6IUF3` / `f_fldyn6IUF3` | 数字 / numeric | 数字；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 物料发货时间 | `flda1qNhWt` / `f_flda1qNhWt` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 相关附件 | `fldH9boU0e` / `f_fldH9boU0e` | 附件 / jsonb | 附件新增/替换/移除；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 库存审查状态 | `fldM84QaMC` / `f_fldM84QaMC` | 单选 / text | 单选下拉；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验；选项：待核实库存、已核实库存、编辑处理中 |
| 库存审查结论 | `fld53o1Z42` / `f_fld53o1Z42` | 单选 / text | 单选下拉；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验；选项：库存充足、部分库存不足、全部库存不足 |
| 库存审查人 | `fld5IBBxNX` / `f_fld5IBBxNX` | 人员 / jsonb | 人员选择；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 库存审查时间 | `fldMjmAtyk` / `f_fldMjmAtyk` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 申请物料更改信息说明 | `fld345mD6f` / `f_fld345mD6f` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 申请物料最后修改人 | `fldQMdxNPt` / `f_fldQMdxNPt` | 人员 / jsonb | 人员选择；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 申请物料最后修改时间 | `fldgOk4g1Q` / `f_fldgOk4g1Q` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 申请变更次数 | `fldVHKwBq4` / `f_fldVHKwBq4` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 库存快照时间 | `fldUwEiuAI` / `f_fldUwEiuAI` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 库存确认消息ID | `fldDPeYfXS` / `f_fldDPeYfXS` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 提交幂等键 | `fldxMO4LL2` / `f_fldxMO4LL2` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 审批实例Code | `flddbjQm1N` / `f_flddbjQm1N` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 管理员通知状态 | `fldtCgN2I6` / `f_fldtCgN2I6` | 单选 / text | 单选下拉；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验；选项：待发送、已发送、发送失败 |
| 管理员通知时间 | `fldpj4QDuF` / `f_fldpj4QDuF` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 文化周边处理状态 | `fldDSSeahV` / `f_fldDSSeahV` | 单选 / text | 单选下拉；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验；选项：待处理、处理中、已发放、处理失败、驳回处理中、已驳回 |
| 文化周边通知状态 | `fldvFgVxMI` / `f_fldvFgVxMI` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 要求达到开始日期 | `fldbq8OvU1` / `f_fldbq8OvU1` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 要求到达结束日期 | `fldO9pYIW3` / `f_fldO9pYIW3` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 需要下单日期 | `fldLFMnKmx` / `f_fldLFMnKmx` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 预计完成制作日期 | `fldsfugJKH` / `f_fldsfugJKH` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 申请时角色快照 | `fld7uAG4Nq` / `f_fld7uAG4Nq` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 时间判定 | `fldIKEtnNm` / `f_fldIKEtnNm` | 单选 / text | 单选下拉；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验；选项：普通申请、加急申请、时间豁免、待补充日期 |
| 排期编辑版本 | `fldrFmvW8s` / `f_fldrFmvW8s` | 数字 / numeric | 数字；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 物料到货状态 | `fldcPL9SP9` / `f_fldcPL9SP9` | 单选 / text | 单选下拉；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验；选项：全部已到货、部分未到货、部分已到货、待下单 |
| 物料使用时间 | `fldoXPxVw4` / `f_fldoXPxVw4` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 物料到货时间 | `fld2xK9ypy` / `f_fld2xK9ypy` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 物料下单时间 | `fldn6RaSH0` / `f_fldn6RaSH0` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 是否发货 | `fld3UftBmz` / `f_fld3UftBmz` | 复选框 / boolean | 复选框；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 发货单号及文字信息 | `fldQZYSjSZ` / `f_fldQZYSjSZ` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 发货图片 | `fldB2J7eCX` / `f_fldB2J7eCX` | 附件 / jsonb | 附件新增/替换/移除；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 文化周边消息ID | `fldIT5LsN2` / `f_fldIT5LsN2` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| INV/PL | `fldXsnbzgf` / `f_fldXsnbzgf` | 附件 / jsonb | 附件新增/替换/移除；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 申请原因 | `fldwIgWFbO` / `f_fldwIgWFbO` | 单选 / text | 单选下拉；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验；选项：代理商支持、展会需求、客户来访、其他、代理活动 |
| 待核实标签 | `fldx0dDBjm` / `f_fldx0dDBjm` | 文本 / text | 文本；仅管理员配货台跟进；不触发库存核实、审批或通知 |
| 待核实备注 | `fldC20Nrr6` / `f_fldC20Nrr6` | 文本 / text | 文本；仅管理员配货台跟进；不触发库存核实、审批或通知 |

## 申请明细

来源：`primary`；实际表名：申请明细；表 ID：`tbl6i0F9UZjTuTV1`。

| 字段 | 字段 ID / SQL 列 | 飞书类型 / SQL 类型 | 编辑选项及写入路径 |
|---|---|---|---|
| 明细编号 | `fldgtXS0w5` / `f_fldgtXS0w5` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 所属申请单 | `fld3QWa92E` / `f_fld3QWa92E` | 双向关联 / jsonb | 关联记录选择；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 明细业务类型 | `fldiIKb3ab` / `f_fldiIKb3ab` | 单选 / text | 单选下拉；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验；选项：普通物料、文化周边、企业文化衫 |
| 物料编码 | `fld7t8G0oI` / `f_fld7t8G0oI` | 双向关联 / jsonb | 关联记录选择；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 品类 | `fldMWDekXk` / `f_fldMWDekXk` | 单向关联 / jsonb | 关联记录选择；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 产品型号 | `fld4HLcaoo` / `f_fld4HLcaoo` | 单向关联 / jsonb | 关联记录选择；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 语种 | `fldgitw8bJ` / `f_fldgitw8bJ` | 单向关联 / jsonb | 关联记录选择；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 品类名称 | `fldePX6DdL` / `f_fldePX6DdL` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 产品型号名称 | `fldPIPGplV` / `f_fldPIPGplV` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 语种名称 | `fldLIm2RCK` / `f_fldLIm2RCK` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 申请数量 | `fld1w2ilYr` / `f_fld1w2ilYr` | 数字 / numeric | 数字；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 附件 | `fldBQSdsMx` / `f_fldBQSdsMx` | 附件 / jsonb | 附件新增/替换/移除；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 提交时库存快照 | `fld1rUKkE6` / `f_fld1rUKkE6` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 审批通过数量 | `fld1UqEEjy` / `f_fld1UqEEjy` | 数字 / numeric | 数字；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 实际发放数量 | `fld2hHCqLQ` / `f_fld2hHCqLQ` | 数字 / numeric | 数字；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 明细状态 | `fld3abUfLi` / `f_fld3abUfLi` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 原申请数量 | `fldsckhLZC` / `f_fldsckhLZC` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 库存审查时库存 | `flddH4KaBt` / `f_flddH4KaBt` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 库存满足状态 | `fld5qIxpGl` / `f_fld5qIxpGl` | 单选 / text | 单选下拉；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验；选项：库存充足、库存不足，需要制作 |
| 明细变更说明 | `fldbowOA0t` / `f_fldbowOA0t` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 发放人 | `fld1PVBGY4` / `f_fld1PVBGY4` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 发放时间 | `fld1An7An4` / `f_fld1An7An4` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 出库流水编号 | `fld6zpyz74` / `f_fld6zpyz74` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 缺货说明 | `fld4CRNs1f` / `f_fld4CRNs1f` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 备注 | `fld12FS5Sr` / `f_fld12FS5Sr` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 库存流水 | `fldR1YiJBA` / `f_fldR1YiJBA` | 双向关联 / jsonb | 关联记录选择；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 实际发放物料品类 | `flddNVrcdq` / `f_flddNVrcdq` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 实际发放产品型号 | `fldRTGRUce` / `f_fldRTGRUce` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 实际发放语种 | `fldDPjW8dw` / `f_fldDPjW8dw` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 实际发放物料编码 | `fldIsVgogX` / `f_fldIsVgogX` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 文化周边物料 | `fldGk1ZNVB` / `f_fldGk1ZNVB` | 双向关联 / jsonb | 关联记录选择；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 文化周边战区 | `fldGc1jrJH` / `f_fldGc1jrJH` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 申请时单价（人民币） | `fldz3ai7O8` / `f_fldz3ai7O8` | 数字 / numeric | 数字；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 费用小计（人民币） | `flducRL8iq` / `f_flducRL8iq` | 数字 / numeric | 数字；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 下单表生成状态 | `fldVVLOXK4` / `f_fldVVLOXK4` | 单选 / text | 单选下拉；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验；选项：未生成、生成中、已生成 |
| 物料发货时间 | `fld0A0xddO` / `f_fld0A0xddO` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 物料使用时间 | `fldkYFqjU7` / `f_fldkYFqjU7` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 物料到货时间 | `fldo9OyLHU` / `f_fldo9OyLHU` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 物料下单时间 | `fldZAXPcbF` / `f_fldZAXPcbF` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 物料到货状态 | `fldllUWV3y` / `f_fldllUWV3y` | 单选 / text | 单选下拉；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验；选项：未到货、已到货、制作中、已下单、已发货、已取消、已完成、待安排、无需下单 |
| 计划到仓日期 | `fldTO7yEIU` / `f_fldTO7yEIU` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 是否到货 | `fldMTQIFxq` / `f_fldMTQIFxq` | 复选框 / boolean | 复选框；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |

## 物料品类

来源：`primary`；实际表名：物料品类；表 ID：`tbl45q6s50SzEnFI`。

| 字段 | 字段 ID / SQL 列 | 飞书类型 / SQL 类型 | 编辑选项及写入路径 |
|---|---|---|---|
| 物料品类编码 | `fld1EmAuru` / `f_fld1EmAuru` | 自动编号 / text | 显示及源字段入口；系统生成 |
| 物料品类 | `fld1ZnsQu3` / `f_fld1ZnsQu3` | 文本 / text | 文本；管理员编辑 |
| 中文页面名称 | `fldHqYYXAs` / `f_fldHqYYXAs` | 文本 / text | 文本；管理员编辑 |
| 英文页面名称 | `fldBdHDY4j` / `f_fldBdHDY4j` | 文本 / text | 文本；管理员编辑 |
| 是否在申领页显示 | `fld08wAirE` / `f_fld08wAirE` | 单选 / text | 单选下拉；管理员编辑；选项：是、否 |
| 品类定义 | `fldOm98U6v` / `f_fldOm98U6v` | 单选 / text | 单选下拉；管理员编辑；选项：印刷物料、周边礼品、文化周边 |
| 申领页图片 | `fld0j2HWb9` / `f_fld0j2HWb9` | 附件 / jsonb | 附件新增/替换/移除；管理员编辑 |
| 装箱单产品类型 | `fldXV6SxKa` / `f_fldXV6SxKa` | 单选 / text | 单选下拉；管理员编辑；选项：Flyers、Brochures、Banners、Give aways |
| 商业发票产品名称 | `fldx1V2W7q` / `f_fldx1V2W7q` | 文本 / text | 文本；管理员编辑 |
| 启用状态 | `fldWb00SO9` / `f_fldWb00SO9` | 单选 / text | 单选下拉；管理员编辑；选项：启用、停用 |
| 是否无需型号 | `fld4PycTvg` / `f_fld4PycTvg` | 单选 / text | 单选下拉；管理员编辑；选项：否、是 |
| 是否无需语种 | `fld2EtY2BE` / `f_fld2EtY2BE` | 单选 / text | 单选下拉；管理员编辑；选项：否、是 |
| 单价（美元） | `fldeQIH0jS` / `f_fldeQIH0jS` | 数字 / numeric | 数字；管理员编辑 |
| 单价（人民币） | `fldwycKSSj` / `f_fldwycKSSj` | 公式 / jsonb | 显示及源字段入口；源字段编辑 |
| 海关编码 | `fldSU06dXK` / `f_fldSU06dXK` | 数字 / numeric | 数字；管理员编辑 |
| 库存行数 | `fld361H4lB` / `f_fld361H4lB` | 数字 / numeric | 数字；管理员编辑 |
| 产品型号数量 | `fld51TXwMI` / `f_fld51TXwMI` | 数字 / numeric | 数字；管理员编辑 |
| 语种数量 | `fld4SHmqeB` / `f_fld4SHmqeB` | 数字 / numeric | 数字；管理员编辑 |
| 创建时间 | `fld5kk2zPo` / `f_fld5kk2zPo` | 文本 / text | 文本；管理员编辑 |
| 备注 | `fld2yBCSie` / `f_fld2yBCSie` | 文本 / text | 文本；管理员编辑 |
| 物料主数据 | `fldv4U0nYW` / `f_fldv4U0nYW` | 双向关联 / jsonb | 关联记录选择；管理员选择关联记录；通过对应业务服务维护双向关联 |
| 父记录 | `fld02EVY2i` / `f_fld02EVY2i` | 单向关联 / jsonb | 关联记录选择；管理员选择关联记录；通过对应业务服务维护双向关联 |
| 文化周边 | `fldm5SsXdh` / `f_fldm5SsXdh` | 双向关联 / jsonb | 关联记录选择；管理员选择关联记录；通过对应业务服务维护双向关联 |

## 产品型号

来源：`primary`；实际表名：产品型号；表 ID：`tbl233OjVUgT4cJ5`。

| 字段 | 字段 ID / SQL 列 | 飞书类型 / SQL 类型 | 编辑选项及写入路径 |
|---|---|---|---|
| 产品型号编码 | `fld2VgEeIo` / `f_fld2VgEeIo` | 自动编号 / text | 显示及源字段入口；系统生成 |
| 型号类型 | `flduNGc5os` / `f_flduNGc5os` | 单选 / text | 单选下拉；管理员编辑；选项：普通物料、文化周边 |
| 产品型号 | `fldCdm4wzb` / `f_fldCdm4wzb` | 文本 / text | 文本；管理员编辑 |
| 中文页面名称 | `fldfS1pn1E` / `f_fldfS1pn1E` | 文本 / text | 文本；管理员编辑 |
| 英文页面名称 | `fldMvJ3K47` / `f_fldMvJ3K47` | 文本 / text | 文本；管理员编辑 |
| 产品线 | `fldMeouiFj` / `f_fldMeouiFj` | 单选 / text | 单选下拉；管理员编辑；选项：IR、CR、SR、GR、新项目、GT、Hulk、 、OR |
| 启用状态 | `fldg5lzBU0` / `f_fldg5lzBU0` | 单选 / text | 单选下拉；管理员编辑；选项：启用、停用 |
| 物料主数据 | `fld9D1ZQzw` / `f_fld9D1ZQzw` | 双向关联 / jsonb | 关联记录选择；管理员选择关联记录；通过对应业务服务维护双向关联 |
| 文化周边 | `fldguqypG5` / `f_fldguqypG5` | 双向关联 / jsonb | 关联记录选择；管理员选择关联记录；通过对应业务服务维护双向关联 |

## 物料语种

来源：`primary`；实际表名：物料语种；表 ID：`tblYZ3XpkUkQWevb`。

| 字段 | 字段 ID / SQL 列 | 飞书类型 / SQL 类型 | 编辑选项及写入路径 |
|---|---|---|---|
| 语种编码 | `fldtPMkPZE` / `f_fldtPMkPZE` | 自动编号 / text | 显示及源字段入口；系统生成 |
| 语言种类 | `fldEYVyr3e` / `f_fldEYVyr3e` | 文本 / text | 文本；管理员编辑 |
| 启用状态 | `fldhwy00QI` / `f_fldhwy00QI` | 单选 / text | 单选下拉；管理员编辑；选项：启用、停用 |
| 物料主数据 | `fld2xd0znp` / `f_fld2xd0znp` | 双向关联 / jsonb | 关联记录选择；管理员选择关联记录；通过对应业务服务维护双向关联 |

## 战区管理

来源：`primary`；实际表名：战区管理；表 ID：`tblFEKwM1kw9QZAx`。

| 字段 | 字段 ID / SQL 列 | 飞书类型 / SQL 类型 | 编辑选项及写入路径 |
|---|---|---|---|
| 战区编号 | `fldmDGD9wO` / `f_fldmDGD9wO` | 自动编号 / text | 显示及源字段入口；系统生成 |
| 战区名称 | `fld5zJ7eBQ` / `f_fld5zJ7eBQ` | 单选 / text | 单选下拉；管理员编辑；选项：美洲战区、澳新战队、日本战队、亚太战区、大中华战区、欧洲战区、HMT战队、品牌&市场营销内部、电商（国内）、电商（海外） |
| 启用状态 | `flda3E0y9s` / `f_flda3E0y9s` | 单选 / text | 单选下拉；管理员编辑；选项：是、否 |
| 文化周边 | `fldrbLBGG4` / `f_fldrbLBGG4` | 双向关联 / jsonb | 关联记录选择；管理员选择关联记录；通过对应业务服务维护双向关联 |
| 物料数据关联 | `fldQveqXsI` / `f_fldQveqXsI` | 双向关联 / jsonb | 关联记录选择；管理员选择关联记录；通过对应业务服务维护双向关联 |

## 库存流水

来源：`primary`；实际表名：库存流水；表 ID：`tbljMfuTeGM7VC3v`。

| 字段 | 字段 ID / SQL 列 | 飞书类型 / SQL 类型 | 编辑选项及写入路径 |
|---|---|---|---|
| 原Supabase ID | `fld1Owurqa` / `f_fld1Owurqa` | 文本 / text | 文本；内部流程写入；只提供业务状态及审计展示 |
| 流水业务类型 | `fld1wkD9IZ` / `f_fld1wkD9IZ` | 单选 / text | 单选下拉；内部流程写入；只提供业务状态及审计展示；选项：文化周边、营销物料、文化周边申领驳回 |
| 发生时间 | `fld2UDZN6m` / `f_fld2UDZN6m` | 日期时间 / timestamptz | 日期时间；内部流程写入；只提供业务状态及审计展示 |
| 流水类型 | `fld4HaCw9o` / `f_fld4HaCw9o` | 文本 / text | 文本；内部流程写入；只提供业务状态及审计展示 |
| 物料编码 | `fld2DuHL0N` / `f_fld2DuHL0N` | 双向关联 / jsonb | 关联记录选择；内部流程写入；只提供业务状态及审计展示 |
| 物料品类 | `fld74FABY1` / `f_fld74FABY1` | 文本 / text | 文本；内部流程写入；只提供业务状态及审计展示 |
| 产品型号 | `fld3VHZTcA` / `f_fld3VHZTcA` | 文本 / text | 文本；内部流程写入；只提供业务状态及审计展示 |
| 语种 | `fld2y4NB3H` / `f_fld2y4NB3H` | 文本 / text | 文本；内部流程写入；只提供业务状态及审计展示 |
| 数量 | `fld1u247sT` / `f_fld1u247sT` | 数字 / numeric | 数字；内部流程写入；只提供业务状态及审计展示 |
| 变更前数量 | `fld2VaWJr4` / `f_fld2VaWJr4` | 数字 / numeric | 数字；内部流程写入；只提供业务状态及审计展示 |
| 变更后数量 | `fld6OsbTdg` / `f_fld6OsbTdg` | 数字 / numeric | 数字；内部流程写入；只提供业务状态及审计展示 |
| 库存变化 | `fld1ici2uJ` / `f_fld1ici2uJ` | 数字 / numeric | 数字；内部流程写入；只提供业务状态及审计展示 |
| 幂等键 | `fld4180xUe` / `f_fld4180xUe` | 文本 / text | 文本；内部流程写入；只提供业务状态及审计展示 |
| 操作人 | `fld5y4D8CQ` / `f_fld5y4D8CQ` | 人员 / jsonb | 人员选择；内部流程写入；只提供业务状态及审计展示 |
| 操作状态 | `fld5Y7P89H` / `f_fld5Y7P89H` | 文本 / text | 文本；内部流程写入；只提供业务状态及审计展示 |
| 撤回时间 | `fld4pbNnmP` / `f_fld4pbNnmP` | 日期时间 / timestamptz | 日期时间；内部流程写入；只提供业务状态及审计展示 |
| 原流水ID | `fld5c229Tz` / `f_fld5c229Tz` | 文本 / text | 文本；内部流程写入；只提供业务状态及审计展示 |
| 备注 | `fld4LBeRQm` / `f_fld4LBeRQm` | 文本 / text | 文本；内部流程写入；只提供业务状态及审计展示 |
| 关联明细 | `fldB7SHc5g` / `f_fldB7SHc5g` | 双向关联 / jsonb | 关联记录选择；内部流程写入；只提供业务状态及审计展示 |
| 文化周边物料 | `fldA4ooChD` / `f_fldA4ooChD` | 双向关联 / jsonb | 关联记录选择；内部流程写入；只提供业务状态及审计展示 |
| 文化周边战区快照 | `fldGkM9ZD7` / `f_fldGkM9ZD7` | 文本 / text | 文本；内部流程写入；只提供业务状态及审计展示 |

## 申请物料变更记录表

来源：`primary`；实际表名：申请物料变更记录表；表 ID：`tblZKYpNhA5aw3HV`。

| 字段 | 字段 ID / SQL 列 | 飞书类型 / SQL 类型 | 编辑选项及写入路径 |
|---|---|---|---|
| 文本 | `fldxapsDPC` / `f_fldxapsDPC` | 文本 / text | 文本；内部流程写入；只提供业务状态及审计展示 |
| 申请单号 | `fldexIhO6d` / `f_fldexIhO6d` | 文本 / text | 文本；内部流程写入；只提供业务状态及审计展示 |
| 操作人OpenID | `fldmvuhwk2` / `f_fldmvuhwk2` | 文本 / text | 文本；内部流程写入；只提供业务状态及审计展示 |
| 操作时间 | `flda0yOu91` / `f_flda0yOu91` | 日期时间 / timestamptz | 日期时间；内部流程写入；只提供业务状态及审计展示 |
| 变更说明 | `fldsrHK2Kb` / `f_fldsrHK2Kb` | 文本 / text | 文本；内部流程写入；只提供业务状态及审计展示 |
| 变更前JSON | `fldjLdmuVW` / `f_fldjLdmuVW` | 文本 / text | 文本；内部流程写入；只提供业务状态及审计展示 |
| 变更后JSON | `fldCiKntAO` / `f_fldCiKntAO` | 文本 / text | 文本；内部流程写入；只提供业务状态及审计展示 |
| 变更版本 | `fldIFJ2RJ5` / `f_fldIFJ2RJ5` | 数字 / numeric | 数字；内部流程写入；只提供业务状态及审计展示 |

## 物料货架

来源：`primary`；实际表名：物料货架；表 ID：`tblqz8xmpgtv4Q9C`。

| 字段 | 字段 ID / SQL 列 | 飞书类型 / SQL 类型 | 编辑选项及写入路径 |
|---|---|---|---|
| 货架编号 | `fld1R8ShBf` / `f_fld1R8ShBf` | 文本 / text | 文本；管理员编辑 |
| 货架地面位置 | `fldaxUFtpz` / `f_fldaxUFtpz` | 文本 / text | 文本；管理员编辑 |
| 货架图片 | `fld9hcgSVr` / `f_fld9hcgSVr` | 附件 / jsonb | 附件新增/替换/移除；管理员编辑 |
| 放置物料 | `fldwjN2hgu` / `f_fldwjN2hgu` | 文本 / text | 文本；管理员编辑 |
| SourceID | `fldjOmKe18` / `f_fldjOmKe18` | 文本 / text | 文本；管理员编辑 |
| 关联货架行 | `fldHciBo7u` / `f_fldHciBo7u` | 双向关联 / jsonb | 关联记录选择；管理员选择关联记录；通过对应业务服务维护双向关联 |
| 关联物料 | `fld2MnIrLH` / `f_fld2MnIrLH` | 双向关联 / jsonb | 关联记录选择；管理员选择关联记录；通过对应业务服务维护双向关联 |

## 仓库物料位置

来源：`primary`；实际表名：仓库物料位置；表 ID：`tbldA8qhSeIfJp3k`。

| 字段 | 字段 ID / SQL 列 | 飞书类型 / SQL 类型 | 编辑选项及写入路径 |
|---|---|---|---|
| 货架行 | `fldX30nMua` / `f_fldX30nMua` | 文本 / text | 文本；管理员编辑 |
| 关联货架 | `fld5lebrRH` / `f_fld5lebrRH` | 双向关联 / jsonb | 关联记录选择；管理员选择关联记录；通过对应业务服务维护双向关联 |
| 放置物料文字说明 | `fldYBBCDb9` / `f_fldYBBCDb9` | 文本 / text | 文本；管理员编辑 |
| 图片 | `fldt7YUjNs` / `f_fldt7YUjNs` | 附件 / jsonb | 附件新增/替换/移除；管理员编辑 |
| 关联物料 | `fldY59fk7a` / `f_fldY59fk7a` | 双向关联 / jsonb | 关联记录选择；管理员选择关联记录；通过对应业务服务维护双向关联 |

## 用户权限表

来源：`primary`；实际表名：用户权限表；表 ID：`tblytA4DHQVbJiIJ`。

| 字段 | 字段 ID / SQL 列 | 飞书类型 / SQL 类型 | 编辑选项及写入路径 |
|---|---|---|---|
| 用户编号 | `flde9SGwYo` / `f_flde9SGwYo` | 自动编号 / text | 显示及源字段入口；系统生成 |
| 用户账号 | `fldjvS5kat` / `f_fldjvS5kat` | 人员 / jsonb | 人员选择；管理员授权管理；额度通过申领/撤销流程累计 |
| 角色 | `fldIRrp9Mt` / `f_fldIRrp9Mt` | 多选 / jsonb | 多选；管理员授权管理；额度通过申领/撤销流程累计；选项：管理员、销售、区域市场经理、HR、中台 |
| 是否启用 | `fldAkxcnfu` / `f_fldAkxcnfu` | 单选 / text | 单选下拉；管理员授权管理；额度通过申领/撤销流程累计；选项：是、否 |
| POLO申领数量累计 | `fldq1O6Sjs` / `f_fldq1O6Sjs` | 数字 / numeric | 数字；管理员授权管理；额度通过申领/撤销流程累计 |
| 文化夹克申领数量累计 | `fldH0n3EhG` / `f_fldH0n3EhG` | 数字 / numeric | 数字；管理员授权管理；额度通过申领/撤销流程累计 |
| T恤-黑色（短袖）申领数量累计 | `fldZviMA22` / `f_fldZviMA22` | 数字 / numeric | 数字；管理员授权管理；额度通过申领/撤销流程累计 |
| 冲锋衣-黑色申领数量累计 | `fldM9P8Y4Q` / `f_fldM9P8Y4Q` | 数字 / numeric | 数字；管理员授权管理；额度通过申领/撤销流程累计 |
| 商务衬衫-黑色（长袖）神灵数量累计 | `fldvHGX5Mf` / `f_fldvHGX5Mf` | 数字 / numeric | 数字；管理员授权管理；额度通过申领/撤销流程累计 |
| 文化衫申领数量累计 | `fldJafoPOr` / `f_fldJafoPOr` | 数字 / numeric | 数字；管理员授权管理；额度通过申领/撤销流程累计 |
| 父记录 | `fldtGAg9eT` / `f_fldtGAg9eT` | 单向关联 / jsonb | 关联记录选择；管理员授权管理；额度通过申领/撤销流程累计 |

## BUG反馈收集

来源：`primary`；实际表名：BUG反馈收集；表 ID：`tblkwz5617lcUEII`。

| 字段 | 字段 ID / SQL 列 | 飞书类型 / SQL 类型 | 编辑选项及写入路径 |
|---|---|---|---|
| 编号 | `fldiOcTKNd` / `f_fldiOcTKNd` | 自动编号 / text | 显示及源字段入口；系统生成 |
| 人员 | `fld6sz5Ntp` / `f_fld6sz5Ntp` | 人员 / jsonb | 人员选择；管理员编辑 |
| 人员.部门 | `fld7xQEXlj` / `f_fld7xQEXlj` | 多选 / jsonb | 多选；管理员编辑 |
| BUG | `fldxi0GHxq` / `f_fldxi0GHxq` | 文本 / text | 文本；管理员编辑 |
| 优化 | `fldvPb9tAC` / `f_fldvPb9tAC` | 文本 / text | 文本；管理员编辑 |

## 后台任务队列

来源：`primary`；实际表名：后台任务队列；表 ID：`tblqkM5h34IJc1o5`。

| 字段 | 字段 ID / SQL 列 | 飞书类型 / SQL 类型 | 编辑选项及写入路径 |
|---|---|---|---|
| 任务ID | `fldh251Xg3` / `f_fldh251Xg3` | 文本 / text | 文本；内部流程写入；只提供业务状态及审计展示 |
| 任务类型 | `fldQBywunj` / `f_fldQBywunj` | 文本 / text | 文本；内部流程写入；只提供业务状态及审计展示 |
| 幂等键 | `fldc6MRjZ4` / `f_fldc6MRjZ4` | 文本 / text | 文本；内部流程写入；只提供业务状态及审计展示 |
| 状态 | `fld7co3b4n` / `f_fld7co3b4n` | 文本 / text | 文本；内部流程写入；只提供业务状态及审计展示 |
| 载荷JSON | `fldkxECJbb` / `f_fldkxECJbb` | 文本 / text | 文本；内部流程写入；只提供业务状态及审计展示 |
| 提交时间 | `fldqZHccF4` / `f_fldqZHccF4` | 日期时间 / timestamptz | 日期时间；内部流程写入；只提供业务状态及审计展示 |
| 开始时间 | `fld9HkV8ns` / `f_fld9HkV8ns` | 日期时间 / timestamptz | 日期时间；内部流程写入；只提供业务状态及审计展示 |
| 完成时间 | `fldoTcXGX5` / `f_fldoTcXGX5` | 日期时间 / timestamptz | 日期时间；内部流程写入；只提供业务状态及审计展示 |
| 租约到期时间 | `fldLSzLniZ` / `f_fldLSzLniZ` | 日期时间 / timestamptz | 日期时间；内部流程写入；只提供业务状态及审计展示 |
| 重试次数 | `fldfCEQVkp` / `f_fldfCEQVkp` | 数字 / numeric | 数字；内部流程写入；只提供业务状态及审计展示 |
| 下次重试时间 | `fld5aJVWS0` / `f_fld5aJVWS0` | 日期时间 / timestamptz | 日期时间；内部流程写入；只提供业务状态及审计展示 |
| Worker标识 | `fld2bTELtV` / `f_fld2bTELtV` | 文本 / text | 文本；内部流程写入；只提供业务状态及审计展示 |
| 结果JSON | `fld8ZmhDJd` / `f_fld8ZmhDJd` | 文本 / text | 文本；内部流程写入；只提供业务状态及审计展示 |
| 错误信息 | `fld7N139Oi` / `f_fld7N139Oi` | 文本 / text | 文本；内部流程写入；只提供业务状态及审计展示 |
| 完成状态 | `fldHmNjeec` / `f_fldHmNjeec` | 单选 / text | 单选下拉；内部流程写入；只提供业务状态及审计展示；选项：未完成、已完成 |

## 后台任务载荷

来源：`primary`；实际表名：后台任务载荷；表 ID：`tbl0L6FyQocgHlZS`。

| 字段 | 字段 ID / SQL 列 | 飞书类型 / SQL 类型 | 编辑选项及写入路径 |
|---|---|---|---|
| 任务ID | `fld5vbI3F6` / `f_fld5vbI3F6` | 文本 / text | 文本；内部流程写入；只提供业务状态及审计展示 |
| 分片序号 | `fldt1uMUmm` / `f_fldt1uMUmm` | 数字 / numeric | 数字；内部流程写入；只提供业务状态及审计展示 |
| 分片内容 | `fld9jXgMkN` / `f_fld9jXgMkN` | 文本 / text | 文本；内部流程写入；只提供业务状态及审计展示 |

## 后台任务节点列表

来源：`primary`；实际表名：后台任务节点列表；表 ID：`tblvcbMPOaNUGwpO`。

| 字段 | 字段 ID / SQL 列 | 飞书类型 / SQL 类型 | 编辑选项及写入路径 |
|---|---|---|---|
| 节点标识 | `fldU5SJT59` / `f_fldU5SJT59` | 文本 / text | 文本；内部流程写入；只提供业务状态及审计展示 |
| 电脑名称 | `fldKBmw7rb` / `f_fldKBmw7rb` | 文本 / text | 文本；内部流程写入；只提供业务状态及审计展示 |
| 优先级 | `fldCJLwrek` / `f_fldCJLwrek` | 数字 / numeric | 数字；内部流程写入；只提供业务状态及审计展示 |
| 最后心跳时间 | `fldBl0ffap` / `f_fldBl0ffap` | 日期时间 / timestamptz | 日期时间；内部流程写入；只提供业务状态及审计展示 |
| 应用版本 | `fld07GONzV` / `f_fld07GONzV` | 文本 / text | 文本；内部流程写入；只提供业务状态及审计展示 |
| 节点状态 | `fldJ7Kyh6v` / `f_fldJ7Kyh6v` | 单选 / text | 单选下拉；内部流程写入；只提供业务状态及审计展示；选项：在线、离线、失联 |
| 是否启用 | `fldpy2bmPQ` / `f_fldpy2bmPQ` | 单选 / text | 单选下拉；内部流程写入；只提供业务状态及审计展示；选项：是、否 |

## 项目周边礼品物料筹备详情list

来源：`primary`；实际表名：项目周边礼品物料筹备详情list；表 ID：`tblIK0aWEMcMIbxt`。

| 字段 | 字段 ID / SQL 列 | 飞书类型 / SQL 类型 | 编辑选项及写入路径 |
|---|---|---|---|
| 项目名称 | `fldGoBPnLQ` / `f_fldGoBPnLQ` | 单选 / text | 单选下拉；管理员编辑；选项：巴拿马活动、公共项目、周边电商化、__CODEX_OWNER_FIELD_REGRESSION__、测试项目、AAA、巴西新活动、澳洲ISSA |
| 物料名称 | `fldT3IPEsj` / `f_fldT3IPEsj` | 文本 / text | 文本；管理员编辑 |
| 项目状态 | `fld8YtnV0L` / `f_fld8YtnV0L` | 单选 / text | 单选下拉；管理员编辑；选项：筹备中、已完结 |
| 物料状态 | `fldgazMZbB` / `f_fldgazMZbB` | 单选 / text | 单选下拉；管理员编辑；选项：已提需、寻源中、待确认下单、设计制作中、已到货、在库有库存、已发货 |
| 物料图片 | `fldrARXhUa` / `f_fldrARXhUa` | 附件 / jsonb | 附件新增/替换/移除；管理员编辑 |
| 供应商联系方式 | `fldtRwJF6V` / `f_fldtRwJF6V` | 文本 / text | 文本；管理员编辑 |
| 物料品类关联 | `fldWETvWXK` / `f_fldWETvWXK` | 单向关联 / jsonb | 关联记录选择；管理员选择关联记录；通过对应业务服务维护双向关联 |
| 备注 | `fld4aQuoqH` / `f_fld4aQuoqH` | 文本 / text | 文本；管理员编辑 |
| 负责人 | `fldhUH5fo2` / `f_fldhUH5fo2` | 人员 / jsonb | 人员选择；管理员编辑 |
| 参与人 | `fldbeCjKuG` / `f_fldbeCjKuG` | 人员 / jsonb | 人员选择；管理员编辑 |
| 父记录 2 | `fldik2eETL` / `f_fldik2eETL` | 单向关联 / jsonb | 关联记录选择；管理员选择关联记录；通过对应业务服务维护双向关联 |

## 物料下单批次

来源：`primary`；实际表名：物料下单批次；表 ID：`tbl0s6IFfjPsYIen`。

| 字段 | 字段 ID / SQL 列 | 飞书类型 / SQL 类型 | 编辑选项及写入路径 |
|---|---|---|---|
| 下单批次号 | `fldrlQp44d` / `f_fldrlQp44d` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 批次状态 | `flde6O9x5a` / `f_flde6O9x5a` | 单选 / text | 单选下拉；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验；选项：生成中、生成失败、已生成、已作废 |
| 下单表文件 | `fldl5ti5ei` / `f_fldl5ti5ei` | 附件 / jsonb | 附件新增/替换/移除；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 生成人 | `fld6Hboct1` / `f_fld6Hboct1` | 人员 / jsonb | 人员选择；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 生成时间 | `fldqwogT4X` / `f_fldqwogT4X` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 生成幂等键 | `fldakjTWAm` / `f_fldakjTWAm` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 启用自动补库 | `fldS2BUgyZ` / `f_fldS2BUgyZ` | 复选框 / boolean | 复选框；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 批次备注 | `fldkxgBC0v` / `f_fldkxgBC0v` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 物料使用时间 | `fldv5AJCLL` / `f_fldv5AJCLL` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 物料发货时间 | `fldbwbn4ps` / `f_fldbwbn4ps` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 物料到货时间 | `fldVNGS8kr` / `f_fldVNGS8kr` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 物料下单时间 | `fldDhLpEg6` / `f_fldDhLpEg6` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |

## 物料下单批次明细

来源：`primary`；实际表名：物料下单批次明细；表 ID：`tblOI5DtJydIREVu`。

| 字段 | 字段 ID / SQL 列 | 飞书类型 / SQL 类型 | 编辑选项及写入路径 |
|---|---|---|---|
| 批次明细编号 | `fldQVgdgeO` / `f_fldQVgdgeO` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 所属下单批次 | `fldGFyEbPJ` / `f_fldGFyEbPJ` | 单向关联 / jsonb | 关联记录选择；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 来源申请单 | `fldMixIryy` / `f_fldMixIryy` | 单向关联 / jsonb | 关联记录选择；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 来源申请明细 | `fldoKB0UqF` / `f_fldoKB0UqF` | 单向关联 / jsonb | 关联记录选择；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 关联物料 | `fld8C18lqz` / `f_fld8C18lqz` | 单向关联 / jsonb | 关联记录选择；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 关联文化周边库存 | `fldFPeOXMk` / `f_fldFPeOXMk` | 单向关联 / jsonb | 关联记录选择；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 品类名称快照 | `fld6CHdrHI` / `f_fld6CHdrHI` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 型号或尺码快照 | `flde7eKKsb` / `f_flde7eKKsb` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 语种快照 | `fldPOP4d4n` / `f_fldPOP4d4n` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 战区快照 | `fld8lChhdg` / `f_fld8lChhdg` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 下单数量 | `fldOFQRbHH` / `f_fldOFQRbHH` | 数字 / numeric | 数字；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 申请用途快照 | `fldvDe9M26` / `f_fldvDe9M26` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 明细备注快照 | `fldUPmbYap` / `f_fldUPmbYap` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 计划到仓日期 | `fldwgopsCW` / `f_fldwgopsCW` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 补库状态 | `fldvfPZB1f` / `f_fldvfPZB1f` | 单选 / text | 单选下拉；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验；选项：待补库、补库中、已补库、补库异常、已取消 |
| 实际补库时间 | `fldFOKlsOW` / `f_fldFOKlsOW` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 关联库存流水 | `fldTTn7weu` / `f_fldTTn7weu` | 单向关联 / jsonb | 关联记录选择；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 补库幂等建 | `fld2JgQWVq` / `f_fld2JgQWVq` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 补库异常说明 | `fldUKbnszg` / `f_fldUKbnszg` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 物料发货时间 | `fldq3IESYB` / `f_fldq3IESYB` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 物料到货状态 | `fld17f2xDO` / `f_fld17f2xDO` | 单选 / text | 单选下拉；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验；选项：已到货、未到货、制作中、已下单、已发货、已取消、已完成、待安排、无需下单 |
| 物料使用时间 | `fldVGU8aRc` / `f_fldVGU8aRc` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 物料下单时间 | `fldItzchlw` / `f_fldItzchlw` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 物料到货时间 | `fldxPdOLR1` / `f_fldxPdOLR1` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |

## 文化周边编码及库存数量

来源：`primary`；实际表名：文化周边编码及库存数量；表 ID：`tblOUvklAihp8g34`。

| 字段 | 字段 ID / SQL 列 | 飞书类型 / SQL 类型 | 编辑选项及写入路径 |
|---|---|---|---|
| 物品分类 | `fldf5SRSn5` / `f_fldf5SRSn5` | 单选 / text | 单选下拉；行政源表维护；本表为同步副本，系统兑换数量由兑换流程更新；选项：文化衫、文创周边、【说明】
1.产品正式名称采用“一级分类-产品名称-款式/主题名称”统一命名。
2.产品编码采用“分类前缀 + 三位流水号”形式。文化服饰类编码建议统一使用CF（Corporate Fashion），文创周边类编码建议统一使用 CG（Cultural Goods）。
3.颜色、尺码等库存维度信息，在库存SKU层单独管理。 |
| 款式 | `fldgWL0cJR` / `f_fldgWL0cJR` | 文本 / text | 文本；行政源表维护；本表为同步副本，系统兑换数量由兑换流程更新 |
| 编码 | `fldy0UjLOf` / `f_fldy0UjLOf` | 文本 / text | 文本；行政源表维护；本表为同步副本，系统兑换数量由兑换流程更新 |
| 图片 | `fldyXPihmv` / `f_fldyXPihmv` | 附件 / jsonb | 附件新增/替换/移除；行政源表维护；本表为同步副本，系统兑换数量由兑换流程更新 |
| 文化币售价/个 | `fldwqdnecL` / `f_fldwqdnecL` | 文本 / text | 文本；行政源表维护；本表为同步副本，系统兑换数量由兑换流程更新 |
| 码数 | `fld1q7jLm6` / `f_fld1q7jLm6` | 单选 / text | 单选下拉；行政源表维护；本表为同步副本，系统兑换数量由兑换流程更新；选项：标品、2XS、XS、S、M、L、XL、2XL、3XL、4XL、5XL、6XL、7XL、8XL |
| 原始库存数量 | `fld1daDFDB` / `f_fld1daDFDB` | 数字 / numeric | 数字；行政源表维护；本表为同步副本，系统兑换数量由兑换流程更新 |
| 入库/纠正 | `fldgo3lmnA` / `f_fldgo3lmnA` | 数字 / numeric | 数字；行政源表维护；本表为同步副本，系统兑换数量由兑换流程更新 |
| 表格兑换数量 | `fldd2msnXE` / `f_fldd2msnXE` | 数字 / numeric | 数字；行政源表维护；本表为同步副本，系统兑换数量由兑换流程更新 |
| 最新库存 | `fld9wnPdsv` / `f_fld9wnPdsv` | 数字 / numeric | 数字；行政源表维护；本表为同步副本，系统兑换数量由兑换流程更新 |
| 备注 | `fldt0RG8Ai` / `f_fldt0RG8Ai` | 文本 / text | 文本；行政源表维护；本表为同步副本，系统兑换数量由兑换流程更新 |
| SourceID | `fldBYQeDOO` / `f_fldBYQeDOO` | 文本 / text | 文本；行政源表维护；本表为同步副本，系统兑换数量由兑换流程更新 |
| 系统兑换数量 | `fldkk4LsEO` / `f_fldkk4LsEO` | 数字 / numeric | 数字；行政源表维护；本表为同步副本，系统兑换数量由兑换流程更新 |
| 父记录 | `fldzM8Ou4A` / `f_fldzM8Ou4A` | 文本 / text | 文本；行政源表维护；本表为同步副本，系统兑换数量由兑换流程更新 |
| 父记录 2 | `fldA00ml9C` / `f_fldA00ml9C` | 文本 / text | 文本；行政源表维护；本表为同步副本，系统兑换数量由兑换流程更新 |
| 父记录 2 (1) | `fldpIrGTcV` / `f_fldpIrGTcV` | 文本 / text | 文本；行政源表维护；本表为同步副本，系统兑换数量由兑换流程更新 |
| 父记录 2 (1) (1) | `fld7oQPDmq` / `f_fld7oQPDmq` | 文本 / text | 文本；行政源表维护；本表为同步副本，系统兑换数量由兑换流程更新 |
| 申领款式编号 | `fldscalEfH` / `f_fldscalEfH` | 文本 / text | 文本；行政源表维护；本表为同步副本，系统兑换数量由兑换流程更新 |
| 申领显示名称 | `fldafrogkF` / `f_fldafrogkF` | 文本 / text | 文本；行政源表维护；本表为同步副本，系统兑换数量由兑换流程更新 |
| 申领页显示 | `fld8ykP0ku` / `f_fld8ykP0ku` | 单选 / text | 单选下拉；行政源表维护；本表为同步副本，系统兑换数量由兑换流程更新；选项：是、否 |
| 每人累计领取上限 | `fldtQW0HM8` / `f_fldtQW0HM8` | 数字 / numeric | 数字；行政源表维护；本表为同步副本，系统兑换数量由兑换流程更新 |

## 文化周边兑换

来源：`primary`；实际表名：文化周边兑换；表 ID：`tbl555oQLUh7BiC8`。

| 字段 | 字段 ID / SQL 列 | 飞书类型 / SQL 类型 | 编辑选项及写入路径 |
|---|---|---|---|
| 兑换方式 | `fldjFHS6l8` / `f_fldjFHS6l8` | 单选 / text | 单选下拉；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验；选项：公司配置申领、文化币兑换、外联活动事宜 |
| 创建人 | `fldedOWYwZ` / `f_fldedOWYwZ` | 人员 / jsonb | 人员选择；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 兑换人 | `fldsMccLor` / `f_fldsMccLor` | 人员 / jsonb | 人员选择；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 兑换人.部门 | `fld6tDLNff` / `f_fld6tDLNff` | 多选 / jsonb | 多选；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验；选项：X LAB测试组、X LAB、美国战队、证券事务组、HRBP部、Dream组、GRPBU、欧洲服务B组、PBG、AI Infra部、COE、中东战队、M LAB、美澳英战区、法务部、IRPBU软件组、渠道管理组、意大利战队、通用导航及底盘团队、IR&GR服务组、项目交付组、GRPBU软件组、法国战队、项目成员挂靠、GR测试组、GRPBU算法组、平台软件测试组、IR产品组、校招组、设计部、SRPBU、成本管理组、GRPBU机械组、通用交互团队、硬件平台部电机组、硬件平台部、软件平台架构部、基座模型部、品牌部、行政服务部、海外商务交付组、硬件测试组、销售运营组、收入成本核算组、采购部、GR产品组、项目管理部、产品营销组、国内商务交付组、解决方案部、质量代表组、市场营销部、业务运营平台团队、GRPBU电机组、采购开发组、视觉设计组、通用互联团队、数字化组、知识产权部、英爱战队、营销运营组、GRPBU硬件组、AI变革部、物料计划组、服务代表组、拉美战队、生命周期工具链团队、东莞仓储物流组、IR业务部、欧洲服务A组、IRPBU机械组、端到端导航组、招聘部、NPI组、SRPBU机械组、SR产品组、区域市场组、SR测试组、CRPBU算法组、IRPBU硬件组、M LAB测试组、报告&税务组、机械平台部、SQE组、德瑞奥战队、GR项目管理组、解决方案中台组、CRPBU机电测试组、美洲服务部、韩国服务组、服务运营组、欧洲IR业务部、技术客服组、通用调度团队、基座模型数采实习生组、质量部、财经BP组、工程部、大中华服务部、HMT服务组、采购执行组、需求计划组、IRPBU、SR3D业务部、SQM组、欧日韩战区、CR业务部、SRPBU应用软件组、CRPBU软件组、CRPBU硬件组、马来战队、营销招聘组、美国KA组、亚太服务部、亚太战区、新加坡战队、泰国战队、HMT战队、HR业务部、中东欧战队、美英OR业务部、欧洲OR业务部、西葡战队、日本CR业务组、加拿大战队、澳新战队、德国CR业务组、欧洲GR业务部、大中华战区、KA业务部、SR2D业务部、日本服务组、建湖仓储物流组、计划部、产品市场部、IRPBU交付运营组、刘如蓓、集成供应链中心、SE管理部 |
| 职位名称 | `fldkg8Gpe9` / `f_fldkg8Gpe9` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 物品分类 | `fldephD2R3` / `f_fldephD2R3` | 单选 / text | 单选下拉；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验；选项：文化衫、其他文化周边 |
| 款式 | `fld3dj3vAk` / `f_fld3dj3vAk` | 单选 / text | 单选下拉；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验；选项：文化衫-休闲T恤-黑色（短袖）、文化衫-休闲冲锋衣-黑色、文化衫-休闲商务POLO-黑色（短袖）、文化衫-休闲商务夹克-黑色（长袖）、文化衫-商务衬衫-黑色（长袖）、文创周边-开瓶器-贝拉、文创周边-定制渔夫帽-黄色、文创周边-机器人冰箱贴-贝拉、文创周边-机器人冰箱贴-贝拉Pro、文创周边-机器人冰箱贴-欢乐送2、文创周边-机器人冰箱贴-闪电匣、文创周边-机器人冰箱贴-葫芦、文创周边-机器人冰箱贴-SH1、文创周边-机器人冰箱贴-T300、文创周边-机器人冰箱贴-MT1、文创周边-机器人冰箱贴-CC1、文创周边-机器人徽章-欢乐送2、文创周边-机器人徽章-葫芦、文创周边-机器人徽章-贝拉Pro、文创周边-机器人徽章-欢乐送2&葫芦&贝拉、文创周边-机器人徽章-贝拉、文创周边-机器人徽章-闪电匣、文创周边-机器人徽章-SH1、文创周边-机器人徽章-T300、文创周边-机器人徽章-MT1、文创周边-机器人徽章-CC1、文创周边-LOGO徽章-CC1、文创周边-定制鼠标垫-黑色、文创周边-定制笔记本-灰/蓝色、文创周边-定制马克杯-白色、文创周边-定制靠垫-“靠谱青年款”、文创周边-机器人滴胶公仔-贝拉、文创周边-机器人毛绒公仔-CC1、文创周边-机器人毛绒公仔-贝拉、文创周边-机器人树脂手办-IP与贝拉、文创周边-机器人树脂手办-IP与T300、文创周边-机器人树脂手办-IP与CC1、文创周边-机器人积木玩具-CC1、文创周边-小米保温壶-标品、文创周边-小米智能台灯-标品、文创周边-膳魔师保温杯-标品、文创周边-小米音响-标品、文创周边-大疆云台-标品、文创周边-大疆无人机-标品、文化衫-10周年纪念款（短袖） |
| 码数 | `fldoFTRnyE` / `f_fldoFTRnyE` | 单选 / text | 单选下拉；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验；选项：标品、2XS、XS、S、M、L、XL、2XL、3XL、4XL、5XL、6XL、7XL、8XL |
| 数量 | `fldvrxTecO` / `f_fldvrxTecO` | 数字 / numeric | 数字；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 兑换日期 | `fldm00LvfT` / `f_fldm00LvfT` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 申请事由 | `fldxMMETqS` / `f_fldxMMETqS` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| 备注 | `fldcTimd1j` / `f_fldcTimd1j` | 日期时间 / timestamptz | 日期时间；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |
| SourceID | `fldM2xx4zX` / `f_fldM2xx4zX` | 文本 / text | 文本；申请/审批/配货/撤销/补库流程编辑，保留状态与数量校验 |

## 企业文化衫行政源表

来源：`apparel_admin`；实际表名：文化周边编码及库存数量；表 ID：`tbledtC3RafsHNh0`。

| 字段 | 字段 ID / SQL 列 | 飞书类型 / SQL 类型 | 编辑选项及写入路径 |
|---|---|---|---|
| 物品分类 | `fldbPvpaQP` / `f_fldbPvpaQP` | 单选 / text | 单选下拉；具备行政维护权限的入口编辑来源；系统兑换数量由兑换/撤销事务更新；选项：文化衫、文创周边、【说明】
1.产品正式名称采用“一级分类-产品名称-款式/主题名称”统一命名。
2.产品编码采用“分类前缀 + 三位流水号”形式。文化服饰类编码建议统一使用CF（Corporate Fashion），文创周边类编码建议统一使用 CG（Cultural Goods）。
3.颜色、尺码等库存维度信息，在库存SKU层单独管理。 |
| 款式 | `fldh7hypPE` / `f_fldh7hypPE` | 文本 / text | 文本；具备行政维护权限的入口编辑来源；系统兑换数量由兑换/撤销事务更新 |
| 编码 | `fldxhYwvcT` / `f_fldxhYwvcT` | 文本 / text | 文本；具备行政维护权限的入口编辑来源；系统兑换数量由兑换/撤销事务更新 |
| 图片 | `fldZPa9bGC` / `f_fldZPa9bGC` | 附件 / jsonb | 附件新增/替换/移除；具备行政维护权限的入口编辑来源；系统兑换数量由兑换/撤销事务更新 |
| 文化币售价/个 | `fldcQPYeVi` / `f_fldcQPYeVi` | 文本 / text | 文本；具备行政维护权限的入口编辑来源；系统兑换数量由兑换/撤销事务更新 |
| 码数 | `fldLBx0iY0` / `f_fldLBx0iY0` | 单选 / text | 单选下拉；具备行政维护权限的入口编辑来源；系统兑换数量由兑换/撤销事务更新；选项：标品、2XS、XS、S、M、L、XL、2XL、3XL、4XL、5XL、6XL、7XL、8XL |
| 原始库存数量 | `fld5EdgT0j` / `f_fld5EdgT0j` | 数字 / numeric | 数字；具备行政维护权限的入口编辑来源；系统兑换数量由兑换/撤销事务更新 |
| 入库/纠正 | `fldrIT2TnY` / `f_fldrIT2TnY` | 数字 / numeric | 数字；具备行政维护权限的入口编辑来源；系统兑换数量由兑换/撤销事务更新 |
| 表格兑换数量 | `fldsSm4peE` / `f_fldsSm4peE` | 查找引用 / jsonb | 显示及源字段入口；源字段编辑 |
| 系统兑换数量 | `fld8fO8DM2` / `f_fld8fO8DM2` | 数字 / numeric | 数字；具备行政维护权限的入口编辑来源；系统兑换数量由兑换/撤销事务更新 |
| 最新库存 | `fld6RjVT0Q` / `f_fld6RjVT0Q` | 公式 / jsonb | 显示及源字段入口；源字段编辑 |
| 备注 | `fld887Hnp2` / `f_fld887Hnp2` | 文本 / text | 文本；具备行政维护权限的入口编辑来源；系统兑换数量由兑换/撤销事务更新 |
| 父记录 | `fldD5ajkrv` / `f_fldD5ajkrv` | 单向关联 / jsonb | 关联记录选择；具备行政维护权限的入口编辑来源；系统兑换数量由兑换/撤销事务更新 |
| 父记录 2 | `fldhAwDsaE` / `f_fldhAwDsaE` | 单向关联 / jsonb | 关联记录选择；具备行政维护权限的入口编辑来源；系统兑换数量由兑换/撤销事务更新 |
| 父记录 2 (1) | `fld2K4HadH` / `f_fld2K4HadH` | 单向关联 / jsonb | 关联记录选择；具备行政维护权限的入口编辑来源；系统兑换数量由兑换/撤销事务更新 |
| 父记录 2 (1) (1) | `fldZM4Bs5c` / `f_fldZM4Bs5c` | 单向关联 / jsonb | 关联记录选择；具备行政维护权限的入口编辑来源；系统兑换数量由兑换/撤销事务更新 |
