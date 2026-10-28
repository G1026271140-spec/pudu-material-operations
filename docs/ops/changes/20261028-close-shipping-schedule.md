# 关闭物料管理中的发货排期页面

- 日期：2026-10-28（北京时间）
- 操作人 / 工作区：gaohongyuan1；/srv/pudu-materials-workspaces/gaohongyuan1
- 聊天：梳理系统交接进度，01a175ce-ed88-7f53-bde2-35ccd7de9867
- 基准：V3.9.7，03c89163b2c7582f68585539128ad21c57cd206b

## 用户需求与决定

用户要求“把物料管理里面的发货排期页面关闭了吧”。此要求替换此前保持该页面的约定。
移除物料管理页签、前端类型/路由映射及组件加载；旧 /management/shipping-schedule 地址跳转品类管理。
保留单独的配货与发货日历、发货模板和飞书原始排期数据；不改库存、日期、worker 或通知规则。

## 代码与验证

修改 ManagementPage.tsx、Portal.tsx 与 API 的旧地址处理，更新既有导航和直达路由测试。
更新 README、AGENTS.md 和固定业务规则。先运行受影响测试，再按 sudo pudu-release 执行完整回归、前端构建、GitLab 推送及 VM 部署。
发布终态以 shared/release-audit.jsonl 为准；部署后只读验证旧地址、构建入口、正常发货日历和健康，不写真实业务数据、不发送测试通知。

## 回退

需重新开放时在最新代码上提交恢复页签/组件的前向变更，按同一发布入口处理，不回退数据库。
