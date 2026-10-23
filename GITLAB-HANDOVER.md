# 公司 GitLab 源码交接

> 2026-10-23 更新：`codex/remove-streamlit` 的 V3.5.0 已移除旧页面框架及运行配置，改用 `config/secrets.toml` / `PUDU_SECRETS_FILE`；新的 README 与 DEPLOYMENT.md 为当前部署入口。下列 V3.4.5 基线和旧 Windows 节点说明是原交接历史，不代表已切换生产。

- 目标仓库：`git@code.pudu.work:gaohongyuan1/pudu-materials-operation.git`
- 网页地址：`https://code.pudu.work/gaohongyuan1/pudu-materials-operation`
- GitLab 默认交接分支：`main`。保留远程初始化提交 `d8a61e8`，将其与清理版源码历史合并，不强制推送；初始化 README 另存为 `docs/gitlab-initial-README.md`。
- 代码基线：V3.4.5，原 GitHub 提交 `6d1f36ebd624c59b9f31e4b6542768172f5ac177`。
- 本副本来自 2026-10-23 清理版交接包的 `01-source`，保留前后端、dist、业务模板、Worker、Windows 部署、缓存和扩展自动化脚本及测试。
- 不导入旧 Git 历史，不含生产密钥、人员/申请/库存快照、SQLite、通知 outbox、日志、虚拟环境或原安装器。
- 为避免泄露历史默认凭据，交接包已将旧页面密码回退值与对应测试替换为占位值，补全 secrets 示例并标记历史文档。正式生产源码未变更。
- 本次 GitLab 准备额外扩展 `.gitignore`，避免后续误提交运行快照；未修改业务功能。

原交接内容见 `docs/handover/00-请先阅读.md`。历史文档描述旧生产部署，当前代码入口为 React + FastAPI + 飞书 Base + 持久任务状态 + Python Worker。

## 代码提交不等于生产切换

本仓库先用于数字化运营接收源码，尚未将现有生产节点切换到 GitLab。代码内的 GitHub 配置、默认拉取/推送地址及 `.github/workflows` 保留原状作为迁移参考，不会在 GitLab 自动转化为 GitLab CI。

新服务器部署时需统一适配公司 GitLab 主机、仓库和认证、源码/缓存发布策略、Windows 无人值守运行方式、新域名、飞书登录及 Base 回调。源代码仓库不应继续承载员工通讯录和业务快照；迁移后需落实独立的受限缓存发布/状态备份方案。

## 验证基线

原项目现有环境：835 项测试、21 项子测试通过。清理副本的管理员/启动器测试：37 项通过。缺少授权业务快照时，部分集成测试不可直接运行；不把原环境测试结果视为新服务器已完成验收。

先准备备用节点并验收，再约定切换窗口。不要仅为提交代码修改当前运行节点 origin、停止旧系统或启用第二个生产写入节点。
