# 虚拟机完全替换说明 — V3.6.8

访问地址：https://materials.pudu.work/ 。企业文化衫专用入口为
https://materials.pudu.work/corporate-apparel 。两个入口均通过飞书登录。

## 数据流

普通申请、文化周边申请、企业文化衫申领，以及配货、补减库、品类和基础维度
管理，先在 PostgreSQL 的短事务中完成业务校验、库存/额度变更、审计和同步任务
保存。页面从 PostgreSQL 读取。网络调用不占用业务事务。

material_store.jobs 提供本地持久化业务任务；普通、文化、管理和卡片分别调度。
material_store.outbox_worker 将 create/update/delete 发布到对应飞书来源，并保留
失败重试、依赖等待与人工冲突状态。material_store.effects 独立发送/更新卡片。
消息使用稳定 UUID；超出去重窗口且结果不明的消息进入人工核对，避免再次发送。

现有飞书自动化仍可使用后台任务队列。legacy_bridge 将这些任务交给本地事务执行，
待本地业务、对应飞书同步和通知全部完成后，再标记旧队列任务完成。审批回写前
刷新相关申请、明细、库存和流水。两个 token 校验的回调地址保持原路径：
/api/pending-inventory-sync 与 /api/corporate-exchange-sync；回调先持久化再应答。
事件刷新遇到未同步本地变更会等待，不会拿较旧快照覆盖刚提交的操作。

## 服务与备份

- pudu-material-web：网页/API。
- pudu-material-outbox@ordinary、@cultural、@admin：飞书数据同步。
- pudu-material-business：四条本地业务调度通道。
- pudu-material-effects：持久化通知。
- pudu-material-card：飞书长连接、卡片回调与库存机器人。
- pudu-material-bridge：现有飞书工作流队列衔接、库存提醒调度。
- pudu-material-assets：全球之旅素材处理，保留原历史处理状态和轮询间隔。
- pudu-material-english：全球活动英文同步，保留原状态。
- pudu-material-backup.timer：每天北京时间 02:40。
- pudu-material-reconcile.timer：每天北京时间 03:00，以飞书为准全量校验。

数据库、图片、外部配置，以及扩展的配置和 JSON 状态均纳入私有备份。
原始下载素材保存在 shared/extensions/material-automation/downloads；Windows
已有归档文件保留在旧电脑，处理基线已迁移，不会重新初始化历史记录。
备份恢复必须在独立数据库验证所有表指纹和文件哈希，不得覆盖生产库。

管理员只读运行状态接口：GET /api/admin/runtime-status；需要管理员登录。
返回业务任务、通知、飞书同步状态计数及 worker 版本/心跳。

## 旧电脑与手动替换项

旧电脑的物料网页、隧道、提交 worker、卡片、缓存、看门狗、夜间唤醒、素材整理
和英文同步任务均已停用；保留日志、配置和原始文件。独立 Lead Intake 不停用。
Windows 上的旧启动脚本和旧“手动整理”快捷方式不再作为生产入口使用。

对外申领二维码/收藏应使用上述新地址。GitLab 可见性和部署公钥已由项目负责人
设置；VM 项目公钥的私钥只保留在 VM。域名及飞书应用不变时，已有 OAuth、长连接
卡片订阅和原路径 webhook 不需要仅因服务器替换而重新创建。
若另有人工保存的旧域名入口，需要负责人替换为 materials.pudu.work。

## 本次验证范围

虚拟机回归：862 passed、5 skipped、21 subtests passed；前端在 VM 构建成功。
独立恢复库验证了企业文化衫申领/驳回、额度恢复、配货确认、申请撤回、维度编辑，
以及业务、同步和通知队列收尾。企业文化衫本地保存示例耗时约 287 ms。
模拟飞书验证处理了 17 条消息，未重复发送，未向真实员工发测试消息。
线上仅进行健康、读取、权限和进程检查；未用真实库存做文化衫测试扣减。
部署后以实时服务、队列和备份验收报告为准，不以本文测试数字代替运行证据。

V3.6.8 补充：统一通知卡片与默认部署域名为 materials.pudu.work；图片下载将稳定本地编号转换为飞书记录编号，确保夜间校验后仍可读取图片。

通讯录与部门也在 VM 中刷新并写入 PostgreSQL：pudu-material-contacts.timer 每天北京时间 03:10 运行，读取不完整时保留原数据。旧电脑的联系人缓存程序不再承担生产更新。
两条现有飞书云端同步工作流的 HTTP 回调已改为 materials.pudu.work 并回读验证为 enabled；原触发条件、数据映射和密钥保持一致。
