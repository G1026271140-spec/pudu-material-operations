# PUDU Material Operations

V3.5.3：React + TypeScript/Vite 前端、FastAPI/Uvicorn 后端和独立 Python Worker。虚拟机实时读表浏览模式并行读取通讯录与独立源表，并保留飞书附件下载上下文；不使用业务快照缓存。页面、权限和配货列表实时读取飞书，保留企业登录；浏览阶段关闭提交、同步 Webhook 和后台通知。

这是公司 GitLab 交接及 Ubuntu 迁移分支。**代码调整不表示现有 Windows 生产实例已经升级，也不表示虚拟机业务已接通。** Ubuntu 准备状态见 [服务部署说明](deployment/ubuntu/README.md)。

## 业务组成

- 普通物料、文化周边和企业文化衫申领；个人配额按现有品类规则共享。
- 配货工作台、申请明细调整/分装、撤回、库存核实和提醒。
- 采购补库、品类/型号/语种/战区管理、发货模板与运费分摊。
- 飞书企业登录、申请人/提交人区分及管理员/HR 等角色权限。
- 原“营销物料管理”应用身份访问飞书 Base、后台任务队列和通知；不用个人身份替代。
- 后台任务保留幂等键、检查点、租约、失败和重试通知。SQLite 中的写入状态和通知 outbox 是持久业务状态，不能作为读取缓存删除。

## 配置和运行

环境变量优先；配置文件默认 `config/secrets.toml`，可通过 `PUDU_SECRETS_FILE` 指定外部受保护的 TOML。示例见 [secrets.toml.example](config/secrets.toml.example)。密钥、日志、业务快照及本地数据库不提交 Git。

```sh
python -m venv .venv
# 激活虚拟环境后：
python -m pip install -r requirements.txt
python -m uvicorn request_web.api:api --host 127.0.0.1 --port 8501
```

Windows 也可使用 `run_app.ps1`，它仅启动 FastAPI 并由其提供 React 静态资源。前端源码位于 `request_web/frontend/src`，构建后位于 `request_web/frontend/dist`。

`app.py` 现在是既有业务函数模块，保留模块名以兼容 API、Worker 和维护脚本的导入，不再作为页面程序运行。`backend_runtime.py` 提供独立的配置、缓存和请求局部状态工具，不参与身份授权。

## 部署边界

公司拟用域名是 `materials.pudu.work`；DNS、TLS、飞书重定向和工作台入口未验收前，不修改正式旧域名。不能关闭企业身份验证来让 HTTP IP 页面执行真实业务。

虚拟机测试要求实时读取飞书，不复制生产业务缓存。`PUDU_REALTIME_READS=1` 仅能关闭后端数据函数缓存；旧目录的 JSON 读取路径还须完成独立适配和联调，不能只设置这个开关就宣称全站实时读取已经完成。

原应用文档和交接材料包含 V3.4.5 的生产历史，以本分支 README 和 Ubuntu 说明为新部署入口。尚未启用的 Ubuntu Worker 不得与旧生产 Worker 同时接管同一队列。

## 测试

```sh
python -m pytest tests -q
```

业务回归保留；只针对已删除控件/旧页面 CSS 的测试随对应页面退役，现有 React 页面布局和业务规则测试继续保留。导入守卫覆盖 API、发货工具、任务 Worker 和卡片 Worker，确保不再间接导入旧框架。涉及已发布业务快照的集成测试仍需通过受控测试数据单独验收，源码仓库不携带真实员工数据。
