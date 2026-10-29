# 队列入队和申领图片性能

- 北京时间：2026-10-29
- 工作区：gaohongyuan1 / `/srv/pudu-materials-workspaces/gaohongyuan1`
- 修改前生产：V4.0.1 / 15d0cc7c2fb29f4318910b36f7602bbe2dd7cb32
- 状态：核心隔离验证和文件预备完成；正式发布回执及最终验收以受限证据为准

## 用户要求与诊断

用户指出品类图片编辑、配货等所有类型任务入队慢，并询问申领图片为何没有从 VM 同步文件快速读取。

确认原因：jobs.submit 在 HTTP 请求内调用 run_one，最后提交模式下最多处理 32 个前置任务；图片接口每次到飞书重新读取记录、下载并压缩，所有图片占用业务 HTTP 共用线程。通讯录 / 兑换回调也在原 admin 线程执行，历史通讯录任务耗时 33～45 秒。

同一图片旧读取连续实测 3.709 / 2.769 秒。截图对应产品折页的 09:22 品类任务有真实失败“品类图片已发生变化，请刷新后重新编辑”；保留图片并发 / 源冲突校验，不重放过期图片草稿，不将失败当排队。

## 修改

- material_store/jobs.py：持久化及幂等确认后直接返回，任务只由专用 Worker 执行。外部回调独立 inbound 线程；数据库仍存原 admin lane，不需迁移。统一 reconciliation → business-lane 锁顺序；普通与文化通道并行、同通道 FIFO 不变。
- material_store/image_assets.py：图片文件按附件令牌 / 本地摘要生成 WebP，原子写入 shared/media/image-assets，同图并发只生成一次。校验当前 PG 关联后才读文件，本地已上传图片优先本地字节，未准备的来源只补取一次。109 张图片已完成预备。
- request_web/api.py、apparel_api.py、database_api.py：普通物料、文化周边、文化衫图片统一使用 VM 文件；外部图片请求走独立 4 线程执行器，后台 2 线程每 60 秒预备新图片。保持原款式可见性、HR 和企业登录约束。图片 private/immutable，业务 JSON 仍 no-store；替换图片的令牌 / 摘要改变 URL / 文件版本。
- deployment/ubuntu/70-image-assets.conf：独立 drop-in 启用图片预备，不覆盖现有认证、工作目录和其他 drop-in。无新业务表字段或 SQL 迁移，不替换既有 assets 自动化服务。

## 验证

隔离 PG + 假飞书验证：忙碌业务 lane 不阻塞入队，任务保持 pending 且 HTTP 不调用业务执行；幂等、失败标识、独立 inbound 执行；同图重复 / 并发只有一次下载，移除关联即拒绝旧图，令牌变化读取新图，图片阻塞不占业务线程池，HTTP 返回 WebP 和专用缓存头。已修正旧 PNG 字节相等测试为内容 / 尺寸 / 可见性检查。

六类队列各 5 次隔离回滚实测：入队保存 1.17～16.53 ms，未留下测试任务；这不含浏览器网络、业务执行和飞书同步耗时。109 张图片预备成功、错误 0；本地图片文件命中 0.04～0.15 ms，不把文件读取用时当浏览器端到端耗时。完整 HTTP 图片基准及最终运行证据分别见 shared/audits/image-http-performance-20261029.json 和 performance-live-20261029.json。

完整测试 / 构建 / 备份 / GitLab / 发布 / 公网验证走 sudo pudu-release。不得向员工发送性能测试通知，不在生产创建测试申请。

## 运维与回退

后台预备心跳为 material_ops.documents 的 worker:image-assets，记录 ready / errors / 用时；只有图片文件在本地复用，业务数据、日校验、发货规则和原卡片更新保持原约束。新增文件首读可能需飞书，提前预备和后续文件命中避免重复下载。关闭 PUDU_IMAGE_PREWARM_ENABLED 只停止后台预备；版本化文件仍可按需读取。应用回退走统一发布，保留业务任务、媒体和审计。
