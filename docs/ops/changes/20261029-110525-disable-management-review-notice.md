# 停用物料管理任务需核对通知

- 北京时间：2026-10-29
- 工作区：gaohongyuan1 / /srv/pudu-materials-workspaces/gaohongyuan1
- 修改前生产：V4.0.3 / a8fc32e6fbaca00be8eb41cfac8258e73c134a8f
- 用户要求：停用截图标题“物料管理任务需核对”的飞书通知。

## 规则范围与实现

按 task_result_card.section_for 的同一分类识别物料管理八类任务。停用其额外管理员失败 / 核对卡片；此前成功回执继续关闭。保留原卡片更新、申请人业务通知、配货 / 发货失败提醒及后台错误、冲突、重试记录。用户最新要求覆盖 AGENTS 及固定规则中原先统称保留失败提醒的规定，已同步明确例外。

admin_completion 在生成处跳过物料管理核对通知，并清理已排队 / 待重试的旧回执；effects 在发送前再次校验，关闭重试也保留 attempts / first_attempt_at 供核对。仅跳过带 _admin_completion、状态为任务需核对、任务分类为物料管理的额外回执，不修改业务任务、库存、申请或原有通知。已经送达的历史消息不撤回。

## 验证与发布

隔离 PG / 模拟飞书验证全部八类管理失败回执关闭，错误和业务 outbox 保留；排队 / 已尝试重试均不调用发送接口；原卡片更新、配货及发货核对提醒仍按原规则运行。测试不向员工发送消息。

统一发布走 sudo pudu-release，包括完整检查、构建、GitLab push、备份和实际服务 / 公网版本回读。实际 SHA / 版本见 shared/release-audit.jsonl，通知策略线上验收见 shared/audits/management-review-disabled-20261029.json。不预填尚未得到的发布成功。

## 回退

按统一发布流程回退应用，保留业务错误和通知审计。已按政策跳过的历史额外回执不因回退自动补发。
