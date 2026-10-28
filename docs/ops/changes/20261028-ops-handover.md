# 运维项目文件夹与对话流程归档

- 北京日期：2026-10-28
- 操作人 / 工作区：gaohongyuan1；/srv/pudu-materials-workspaces/gaohongyuan1
- 聊天：梳理系统交接进度；01a175ce-ed88-7f53-bde2-35ccd7de9867
- 轮次：01a1818f-71d1-7c12-a33e-3043ae036c81
- 业务基准：V3.9.5，5d4ab92afb0a38101fbb282b27e07ec2579e4deb

## 需求

用户要求总结成项目文件夹，归档每次对话流程，让新的运维人员能继续功能调整和修改，保持流程不变。

## 处理

新增 docs/ops 运维手册、业务规则、固定发布流程、故障 / 恢复、代码导航、需求沿革、归档规范、验收和记录模板。
修正旧文档入口，明确历史 commissioning 文档不代表现网；更新部分驳回与发货通知说明。
根 AGENTS.md 要求以后每次任务追加工程记录；保留既有个人工作区和统一 sudo pudu-release，不建立新发布通道。
新增 ops_status.py（只读巡检）、new_ops_record.py（不覆盖模板记录）、export_conversations.py（显式导出选定聊天，排除推理及工具载荷并脱敏）。
四个相关聊天按轮次导出，原对话和截图仅受限保存于交接包 / shared/handover-archives，不提交组织可见 GitLab。
源码采用实际发布的 Git archive，附 hash 清单，不打包数据库、凭据、venv 或旧桌面生产状态。

## 验证与发布证据

归档专用测试验证用户后续纠正保留、最终答复、北京时间、凭据脱敏、排除推理 / 工具数据和不覆盖证据。
只读巡检已在实际 VM 运行，确认 23 表 / 366 字段、本地与公网一致、10 个常驻服务及 3 个 timer。
统一发布自动运行全套 tests、Node 前端测试、build、备份、GitLab 推送和生产健康核对；本记录随本次代码一同提交。
最终发布 SHA / 版本和完成结果读取 shared/release-audit.jsonl，并随交接包保存至 04-验收证据；不预填尚未发生的成功。

## 边界

显式聊天导出不等于常驻监听未来对话；未来每次任务按 AGENTS.md 及模板补写，取得聊天文件后再导出。
本次不改变业务数据、角色、库存、通知或定时方向，不向员工发送测试消息。
生产配置、账号凭据、数据库和文件备份需受控单独移交；现有同机备份不等于异地灾备。

## Additional user instructions

Update the root README to the current PostgreSQL VM production architecture and submit one version to the existing GitHub repository. The README now describes active business features, roles, directories, immutable releases, schedules, tests and handover. Publish the exact GitLab release commit to G1026271140-spec/pudu-material-operations on codex/postgres-core; preserve the unrelated legacy master history. GitLab remains the production release source. Record the verified GitHub head in the restricted handover evidence after pushing.
