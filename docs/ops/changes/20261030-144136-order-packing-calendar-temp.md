# 下单分装日历筛选及生产临时目录修复

- 北京时间：2026-10-30T14:41:36+08:00
- 操作人 / Linux 工作区：gaohongyuan1 / /srv/pudu-materials-workspaces/gaohongyuan1
- 状态：针对性检查通过，实际发布与业务恢复结果见 shared/release-audit.jsonl 及 shared/audits/order-packing-filter-live-20261030.json。
- 业务基准：V4.2.2 / 89dafe4f1d5453141cbdfbeded863402df42921b。

## 用户需求与后续补充

日历区分有 / 无印刷物料，默认不显示无印刷物料申请；随后反馈生成历史任务因 No usable temporary directory 失败。

## 原因与修改

- Worker 的 ProtectSystem=strict / ProtectHome=read-only 使默认 /tmp、/var/tmp 和发布目录不可写。先前隔离 Python 测试未模拟此 systemd 文件系统保护，因而漏检。
- deployment/ubuntu/pudu-material-business.service 及同目录 .service.d/70-temp-directory.conf 增加 TMPDIR=共享目录/runtime-tmp、ExecStartPre mkdir，沿用 UMask=0077。补丁安装至对应 /etc/systemd/system drop-in，统一发布时 daemon-reload 后重启；不扩大写权限。后续新安装使用主单元模板；现网兼容使用 drop-in。
- OrderPackingPage.tsx / orderPacking.ts / order-packing.css 增加默认印刷筛选、有 / 无 / 全部切换、蓝灰日历计数与图例、申请标记。保留有印刷关联警告的申请及已选集合，日期 / 搜索 / 分页和全选沿用当前筛选。
- README、固定业务规则和本记录同步。

## 验证

- 已在 systemd-run 中以生产相同 User、ProtectSystem、ProtectHome、ReadWritePaths、UMask 和指定 TMPDIR 实际调用导出器。成功生成并读回两张表，每表3件；不写业务库或发员工消息。
- Node 现有3项检查通过，涵盖默认隐藏、无印刷筛选、全部、未设日期及警告申请保留；tsc -b 通过。
- 正式发布运行完整后端 / Node 测试和生产构建；回执按实际发布采集。
- 精确恢复用户本次失败的导出任务 217ac264-9dc3-4cc0-a101-0b9ef60e363a，仅在仍为该临时目录错误且冻结快照存在时重排；保存原错误与恢复证据，等待实际 Worker 完成并用下载代码校验 SHA256、双表数量。实际结果写受限审计，不预填成功。

## 提交与上线

变更和记录同次提交。统一 sudo pudu-release；保留双管理员并发规则、库存 / 审批 / outbox / 通知流程。随后同步 GitHub 和默认首页 README。实际版本与 SHA 由发布回执确定。

## 遗留与回退

浏览器自动化当前关闭，未做浏览器点击验收；使用前端编译、逻辑检查、生产源数据分类与实际导出 / 下载结果回读。按统一发布回退；专用 TMPDIR 可保留，文件权限不扩展。禁止为此重放任何采购、配货、库存或通知任务。
