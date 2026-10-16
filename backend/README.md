# Agent 服务端（M1 基础 / M2 LangGraph / M3 预约申请 / M4 门店处理 / M5 到店咨询与回访）

2026-10-15：已增加客户账号与跨会话偏好记忆，启动迁移门槛为 `013_customer_memory.sql`。使用、隔离与发布说明见 [客户账号与记忆](../docs/customer-memory.md)。

当前更新（2026-10-12）：M4预约生命周期和M5到店咨询/站内回访已接入，启动迁移门槛012；历史各节保留对应批次的验收边界。最新本地步骤见本文M5第二批节，完整后端191项通过，结果见 docs/production-readiness.md。外部通知/CRM与生产运维仍未完成。

具体演示咨询：新增data/demo_consultation.json 70条，有步骤、时长、虚构菜单价与公开来源科普；默认medical仍待审，仅显式非生产模拟 `MA_DEMO_MEDICAL_EDUCATION=true` 允许review_scope=demo_education的22条做独立模拟复核/发布。原25条待审不改变，生产拒绝该开关，模拟不是医学批准。导入/真实投影及`chat_quality_check --demo`复现见[演示说明](../docs/demo-consultation.md)。界面集中标明虚构场景，回答先解决实际问题。

聊天质量修正：已补首个/当前公开主题来源、近期公开问答上下文、显式项目/比较卡片一致、医疗风险本地连续标记、否定评估/光子别名/公开费用与业务动作区分、一次有预算的引用格式重试和简短表达。无需新迁移或种子，重启8001 API后生效；不启用长期记忆、不批准医学资料、不扩客户权限。复测 `..\.venv\Scripts\python.exe -u -X utf8 -m scripts.chat_quality_check`，单场景用 `--case` 另存；`-m scripts.chat_quality_acceptance` 是捕获回复的定向行为断言，不是临床/全语义批准。固定50轮及最后相关场景的原始回复、实际结果见../docs/chat-quality-review.md。最终专项使用 `-m scripts.verify tests/test_chat_quality_regressions.py tests/test_consultation_agent.py tests/test_consultation_gateway.py tests/test_customer_catalog.py`。

演示资料补充：backend/data/demo_materials.json 提供虚构机构/门店/人员/服务价/供应商和讲解脚本。新增只读 `/api/stores/{store}/demo-materials`，有效员工与明确customer_read、活动模拟门店、非生产且显式允许模拟资料才可读，读取审计；只返回当前店资料。不是业务种子或已发布知识，不扩权、不自动导入向量/图谱或外发模型。无需新迁移，重启API即可；完整资料与演示方法见../docs/demo-materials.md。此次 `-m scripts.verify tests/test_demo_materials.py tests/test_foundation.py` 30项通过，既有191项全量结果为前批历史，不合并成此次全量结果。

M1 已实现 PostgreSQL 身份、门店授权及独立审核发布。M2 已实现导入、Neo4j/Milvus 投影、授权检索与 LangGraph 客户聊天后端；真实 Qwen 多轮咨询合成 HTTP 验收通过。知识 264 条，239 条非医学 published/真实向量/图谱就绪，医学 25 条待审。短期记忆/压缩、消息幂等恢复、转人工工单及本地节点追踪已实现；M3 客户真实聊天、会话恢复、图文目录及持久预约申请已联调。预约草稿、手机号核验与客户明确确认通过本地模拟验收；真实短信、医学核验、注册后长期记忆及改约/取消/到店未完成。

## 本地启动（PowerShell）

在仓库根目录，用 Python 3.12 创建 `.venv` 后安装锁定依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.lock
.\.venv\Scripts\python.exe backend/scripts/local_config.py
.\.venv\Scripts\python.exe backend/scripts/graph_config.py
.\.venv\Scripts\python.exe backend/scripts/milvus_config.py
docker compose --env-file runtime/m1.env -f compose.agent-dev.yml up -d --wait
Set-Location backend
..\.venv\Scripts\python.exe -m app.migrate
$env:M1_SEED_PASSWORD = Get-Content ..\runtime\m1-seed-password.txt -Raw
..\.venv\Scripts\python.exe -m app.seed
Remove-Item Env:\M1_SEED_PASSWORD
..\.venv\Scripts\python.exe -m scripts.milvus_init
..\.venv\Scripts\python.exe -m app.knowledge_import
# 设置本地 LLM_* 与已授权快照后生成真实向量，否则保留等待状态：
..\.venv\Scripts\python.exe -m app.knowledge_worker
..\.venv\Scripts\python.exe -m scripts.pipeline_status
docker build -f sandbox/Dockerfile -t medical-consultation-sandbox:local .
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

本机 WindowsApps 的 `python` 是空壳；本次实际建环境使用 Codex 的 Python 3.12.14。后续直接使用已创建的 `.venv\Scripts\python.exe` 即可。

配置生成器拒绝覆盖已有文件。随机数据库/开发账号密码只写入被 Git 忽略的本地文件；不打印、提交或用于真实系统。模拟账号 `demo-author` / `demo-reviewer` 有模拟上海店知识权限，`demo-platform-admin` 没有门店授权。模拟杭州店没有员工授权。所有账号使用生成的本地种子密码；种子再次执行不重置密码，不覆盖已有数据。

API 文档：http://127.0.0.1:8001/docs ，就绪接口 `/health/ready` 只确认 API/数据库，不代表模型/完整 Agent 已就绪。数据库仅监听本机 `55434`，Neo4j HTTP/Bolt 分别 `57475`/`57689`；Milvus gRPC/健康端口分别 `59531`/`59091`，etcd/MinIO 不暴露主机端口。独立 Compose project `medical-agent-m1`，不复用旧服务。停止用根目录 `docker compose --env-file runtime/m1.env -f compose.agent-dev.yml stop`，保留数据卷。

Milvus 2.5.27 / pymilvus 2.5.18：离线初始化生成 256 维 HNSW/COSINE 集合，API 使用 `ma_reader`，worker 使用 `ma_worker`；两者独立随机密码和集合范围授权，root 仅离线初始化。真实业务集合 `ma_knowledge_256` 与测试集合 `ma_knowledge_test_256` 分开。生产 Settings 要求 Milvus HTTPS 与不同读写凭据；证书、部署网络、备份、依赖安全和集群容量尚未验收。历史 003 pgvector 表保留迁移兼容，不再用于当前检索或写入；004 新增 Milvus 持久回执并将历史发布重新排队，无需删除旧数据。

## 验收

先在这个独立容器创建一次测试库，再在 `backend` 执行验证：

```powershell
docker exec medical-agent-m1-postgres-1 createdb -U ma_m1 ma_m1_test
..\.venv\Scripts\python.exe -m scripts.verify
..\.venv\Scripts\python.exe -m ruff check .
..\.venv\Scripts\python.exe -m mypy app
..\.venv\Scripts\python.exe -m pip check
# API 启动后，实际 HTTP 检查（仅直连本机，避免环境代理）：
..\.venv\Scripts\python.exe -m scripts.smoke
```

测试只接受 `ma_m1_test` 且端口 `55434`，会清空该测试库的模拟业务表。不会清空 `ma_m1`、旧容器或其他数据库。迁移具有事务、序号、校验和与互斥锁；修改已应用迁移会被拒绝，后续使用新迁移。锁文件是本次 Python 3.12/Windows 环境的确切版本快照；Linux 镜像构建和供应链审查仍需验证。

M2 测试需要上述独立 Neo4j 与 Milvus 可达；只写随机版本节点/测试集合记录，并按 ID 清理，不清空图谱或业务集合。向量完整链路使用仅测试文件中的 TestEmbedding，标记 test-only-embedding，绝不注入开发或生产应用；实际测试包含 PostgreSQL worker → 真正 Milvus → 授权检索和读账号拒绝写入。Gateway 用 httpx.MockTransport 验证供应商请求契约、失败和脱敏。因此测试通过不等于真实 Qwen 成功。`scripts.verify -s` 可显示 31 条独立问题的词项降级召回结果；它不是模型语义效果或生产容量评估。

## API 边界

## 对话内预约申请（M3 第二批）

迁移 007 新增草稿、核验、明确确认、申请、事件/outbox 和持久幂等记录；008 为事件/outbox 增补完整门店主体范围。新增 cryptography，安装更新的 requirements.lock。已应用迁移不可修改；需要保留本地加密密钥，否则无法解密已有申请。

在 backend 目录，仅本地模拟验收可执行：

```powershell
..\.venv\Scripts\python.exe -m pip install -r requirements.lock
..\.venv\Scripts\python.exe -m scripts.configure_booking_dev --enable-simulated
..\.venv\Scripts\python.exe -m app.migrate
# 重启 8001 API 后，由 5173 同源代理运行固定合成预约验收：
..\.venv\Scripts\python.exe -X utf8 -m scripts.booking_smoke
```

生成器要求 development 和 MA_ALLOW_SIMULATED_DATA=true，不覆盖已配置密钥或真实短信供应商。MA_BOOKING_ENCRYPTION_KEY 是 Fernet 密钥，MA_BOOKING_HMAC_KEY 用于内容及幂等摘要；保持私密、持久与可恢复，生产轮换/保留删除流程仍待验。MA_BOOKING_POLICY_KEY 默认 faq-online-application，必须有当前门店有效已发布公开运营政策；项目也必须为有效已发布版本。联系方式和完整业务快照加密保存在 PostgreSQL，审计/幂等只存引用与摘要，不进入模型、checkpoint 或 trace。

生产必须 MA_BOOKING_SMS_PROVIDER=aliyun 及完整 MA_SMS_ACCESS_KEY_ID / MA_SMS_ACCESS_KEY_SECRET / MA_SMS_SIGN_NAME / MA_SMS_TEMPLATE_CODE；模拟或关闭核验启动失败。真实适配器使用固定 HTTPS SendSms 与 ACS3-HMAC-SHA256；持久记录后才发送，未知结果不自动重发，同键只核实原记录。短信出口只有手机号、验证码、配置签名/模板和随机业务引用。签名及供应商成功/拒绝/超时协议由 MockTransport 验证，未实际发送或计费，机构账号/签名/模板尚待提供验收。契约依据 [阿里云 SendSms](https://help.aliyun.com/zh/sms/developer-reference/api-dysmsapi-2017-05-25-sendsms) 与 [ACS3 签名文档](https://www.alibabacloud.com/help/en/sdk/product-overview/v3-request-structure-and-signature)。

所有预约接口嵌套于自有 thread，要求访客 Cookie、写入 CSRF 与完整 tenant/store/visitor 范围。普通问答不能直接写申请；最新完成的 visit_interest/visit_request 运行才可触发草稿。后续医疗、拒绝或其他消息会使旧邀约失效。草稿 30 分钟，期望时间限未来 15 分钟至 90 天；验证码 5 分钟、最多五次错误，有效核验凭证 15 分钟且绑定草稿、手机号并只能消费一次。相同手机号或访客每 15 分钟最多三次、间隔至少 60 秒；未知发送阻断新请求键。客户勾选短信同意与申请确认分别记录。确认校验确切文本、快照哈希、有效政策/项目和最新意愿，同事务写申请/确认/事件/outbox/幂等/审计；任何失败全部回滚。

本批完整后端回归 138 passed；真实隔离 PostgreSQL 并发/重放、越店/登出、审核撤回、验证码/确认过期、审计故障回滚通过。固定合成 HTTP 与实际浏览器模拟闭环通过，不能视为真实供应商成功。预约 outbox 尚无员工通知处理器，门店确认/改约/到店属于 M4，手机号核验不创建注册客户或跨设备长期记忆。

### 通用身份与知识边界

- `POST /api/visitor-sessions` 只接受公开 `store_code`（演练用 `demo-shanghai` 或 `demo-hangzhou`），服务端决定租户与门店。返回 CSRF 凭据，Cookie 为 HttpOnly/SameSite Strict；生产必须 Secure/HTTPS。
- 修改客户资源必须同时携带 Cookie 和 `X-CSRF-Token`。有效旧会话替换需 CSRF；失效会话可重新开始，不能凭旧 thread_id 恢复。会话退出、到期、员工停用或门店停用均重新校验。
- 员工登录签发不同类型的短期 opaque bearer 凭据；持久数据库仅存摘要。密码 scrypt 存储，失败登录持久限流（账户+来源，15 分钟最多五次，代理可信来源尚待部署配置）。客户端不能提交角色。
- 员工知识接口必须有该门店的明确权限。作者不能自审；每次修改建立新版本，审核绑定版本。模拟复核无法批准真实资料；医学审核/资质核验未实现，医学资料保留待审。
- `GET /api/staff/me` 只返回当前账号和有明确 grants 的有效门店及权限，不返回密码摘要；`GET /api/stores/{id}/knowledge` 只允许读取授权门店，limit 1–100、offset 0–10000，返回 items/total。未授权平台管理员无门店目录或知识读取权限。
- 发布同时写状态、publication、outbox、审计；重复发布不创建重复任务。M2 worker 完成向量/图谱投影后才能 `published`。没有暴露客户端强制完成投影接口。撤回先在权威数据库阻断，再异步清理投影。
- 公共证据同时校验身份门店、版本、独立审核、发布、有效期、两种投影就绪以及模拟许可，并要求 Milvus 回执集合及内容摘要匹配。向量命中再核验模型、版本、摘要，不能仅信任向量/图谱返回 ID。更新投影等待期间保守阻断旧版本。
- `POST /api/knowledge/search` 接受 question（1–2000 字符），需要真实访客 Cookie + CSRF；服务端限定当前门店，公开证据过滤后做词项/向量/图谱召回，最后重新校验身份和证据。没有公开证据返回 items=[]/method=none；模型不可用可对已完成发布的证据使用 lexical，不能放行待发布资料。检索接口尚不是对话生成接口，不允许客户端指定 Cypher/模型参数。
- `knowledge_import` 导入原 32 条及扩展 226 条；加上 6 条基础种子共 264 条。重复导入不增加版本。扩展数据含 20 个项目入口、100 条运营 FAQ、40 条内部策略、40 个内部多轮场景、6 条官方品牌信息和 20 条待审医学来源摘要。内部策略/场景 audience=internal，不能作为客户公开搜索答案。来源、日期、适用地区、问题变体、漏斗阶段、允许动作与转人工条件存于版本详情，真实机构政策仍待提供核验。
- 模型只经过 Gateway：中国固定端点，SecretStr 凭据。知识批量向量化仍需精确摘要；QwenConsultationGateway 根据既有公开咨询授权，独立过滤/脱敏当前问题与必要公开追问，并重新获取授权证据，不能加入身份、客户档案、合同或医疗记录。导入不自动扩大摘要名单，不读取旧项目密钥。
- 事务在发送成功响应之前提交；实际 PostgreSQL 延迟提交失败会返回安全错误且不签发 Cookie。验证错误不回显口令或输入；每请求有服务端 request_id。

## 下一批与生产缺项

M3 已接客户真实聊天、回答下的项目图片/简介/详情入口和对话内预约申请。M4 已接授权门店处理、改约客户再确认、客户取消与到店登记；下一批 M5 到店档案和咨询意向变化。通知/CRM 及 M2 的注册/同意后长期记忆、检索切块/重排、图谱重建、完整链路指标与跨实例熔断仍需补齐。

目前真实 embedding 与 Qwen/LangGraph 多轮合成咨询、客户前端及本地模拟预约业务写入已验收；没有真实机构知识、医疗批准、真实短信验收或云部署。后台员工身份、知识及预约操作已联网，客户档案等后续业务待实现。规则守卫和引用校验不是完整语义/医学安全证明；完整拒绝审计、访客防滥用、保留/删除、外部身份、生产 TLS/备份恢复、跨实例预算与容量仍待验收，当前不是完整可上线产品。

## LLM 配置与真实知识向量验收

`backend/.env` 支持用户的 `LLM_MODEL=qwen3.7-plus`、`LLM_API_KEY`、`LLM_URL`；优先于旧 MA_CHAT_MODEL / MA_MODEL_API_KEY / MA_MODEL_BASE_URL。域名 `dashscope.aliyuncs.com` 自动归一为 `https://dashscope.aliyuncs.com/compatible-mode/v1`，拒绝不安全协议或其他域名；API Key 始终 SecretStr 且不输出。聊天和 embedding 模型分开，后者仍是 text-embedding-v4 / 256。默认沿用环境代理；故障诊断可用 model_probe --direct，生产代理设置另行验收。

用户于 2026-10-11 明确授权当前全部知识向量化；授权被记录成精确摘要快照，涵盖 264 条版本控制知识、131 条合成检索题和固定合成诊断文本，396 个摘要。医学待审的出口授权不改变审核或客户检索状态。新资料变化仍需更新授权快照，导入不会自动授权；客户身份、业务记录不在此快照中。

```powershell
# 本次授权已执行；只在已有用户授权对应资料范围时重建：
..\.venv\Scripts\python.exe -m scripts.authorize_knowledge_exports --record-user-authorization
..\.venv\Scripts\python.exe -m scripts.model_probe
..\.venv\Scripts\python.exe -m app.knowledge_worker --max-events 300
..\.venv\Scripts\python.exe -m scripts.pipeline_status
# API 重启加载最新 .env 后，使用合成输入发真实检索请求：
..\.venv\Scripts\python.exe -m scripts.smoke
..\.venv\Scripts\python.exe -m scripts.semantic_retrieval_check
```

真实结果：239 个 Milvus 向量、239 ready 回执、239 图谱版本、25 medical draft，无 pending outbox；真实混合检索 31/31 使用 hybrid，recall@5 为 30/31（96.8%），一条 qa-compare-06 未命中。它是合成小集验收，不是向量单独效果或客户/医学效果保证。授权摘要和结果保存在忽略的 runtime/model-export-authorization.json、runtime/semantic-retrieval-report.json；不保存供应商正文或密钥。完整回归 74 passed，见生产验收记录。

## LangGraph 咨询接口与验收

依赖锁定 LangGraph 1.2.14、checkpoint 4.2.0。启动前须运行 `python -m app.migrate` 至 009，API 检查该版本；不改写已应用迁移。

## M4 首批门店接收与处理

009 已迁移，新增 StaffBookingService 与独立 appointment_read / appointment_manage / appointment_contact 权限。已有知识员工/平台管理员不默认访问预约；新增 demo-operator 仅获模拟上海店三项预约权限，杭州无授权。知识读取要求明确知识权限，不将任意门店 grant 当成知识授权。重新执行本地 app.seed 会创建缺失的模拟接待账号，保留已有密码和撤回的 grant；仍拒绝生产/非模拟环境。

```powershell
# backend 目录，既有本地模拟配置：
..\.venv\Scripts\python.exe -m app.migrate
$env:M1_SEED_PASSWORD = (Get-Content ..\runtime\m1-seed-password.txt -Raw).Trim()
..\.venv\Scripts\python.exe -m app.seed
Remove-Item Env:\M1_SEED_PASSWORD
# 重启 API8001，后台5175用 demo-operator 及该本地种子密码登录。
```

GET /api/stores/{store}/appointments 返回授权门店分页 items/total/counts；GET /{id} 返回掩码联系方式、客户确认及状态历史；POST /{id}/contact 必须独立联系方式权限且先写审计；POST /{id}/decision 明确确认/婉拒，要求原 request_key、expected_version 和 accepted。确认还需 availability_checked，服务端只使用客户确认的原期望时间，重新核验有效政策/项目；不接受员工直接改时。婉拒必须有限公开 reason，客户状态读取显示该原因。完整接口见 docs/data-contracts.md。

会话/员工/门店/权限锁及申请锁、版本、持久员工幂等、事件/审计同事务，失败整体回滚；超时原键核实，重放仍重新鉴权。confirmed_at 是确认的到店时间，操作时刻在事件 occurred_at。后台工作台直接查询 PostgreSQL 权威队列计数，不假设 CRM 或 outbox 已发送通知。

本批 scripts.verify -s 完整 **149 passed**；Ruff、mypy 和 pip check 通过。客户25、后台18项测试通过，两端构建通过；实际浏览器完成原申请确认→客户刷新同编号看到确认时间、带原因婉拒及手机详情。本地操作保留模拟标识，真实短信/机构政策/排班及生产运维仍待验。改约客户再确认、取消/到店、员工通知和 CRM 对接是后续，不代表完整后台业务已实现。

- `POST /api/threads/{id}/messages`：访客 Cookie + CSRF，输入 `message_id`（UUID）与 `question`（1–2000 字符）。同步返回已持久化的回答、意图/阶段、来源、转人工状态及有限 action。原始问题仅本地保存；Graph 不接受客户端任意路由、工具或模型参数。
- `GET /api/threads/{id}/messages?limit=50&offset=0`：仅自有会话的分页历史，重新过滤已撤回来源的回答。
- `GET /api/threads/{id}/runs/{run_id}`：自有运行状态、结果和节点元数据，不返回 checkpoint 或 prompt。
- 同键同正文重放返回原结果并重新鉴权；同键不同正文 `message_id_conflict`/409。运行中 `conversation_busy`/409，其他旧运行待恢复为 `recovery_required`/409；失败或租约到期可原键恢复。每会话运行串行，90 秒租约与 fencing；访客每分钟最多 20 个新 run、每会话最多 500 个。

链路：本地 classify → fixed/handoff/retrieve → generate → validate。读取既有混合检索证据，Qwen 输出严格结构化段落；来源、原文引用、数字/联系方式/链接及禁用承诺校验失败时回有效证据摘录。最终事务再次核验授权及证据，并原子提交回答、摘要、工单、幂等结果和审计。生成过程中登出拒绝送达，撤回知识拒绝继续引用。checkpoint 为授权 run 内 JSON，pending writes 独立写入、run 外键限定；END 后提交失败可恢复且不再生成。

短期上下文取最近六条可外发已完成问题，模型最多四条、每条上限 500 字符；摘要保存来源与拒绝预约状态，不存医疗事实，不跨 thread 使用。压缩是有界抽取，完整 token 配额/注册后长期记忆尚未实现。`visit_interest` 的 submitted 固定 false，工单 waiting/connected=false；不代表预约成功或人工已接通。

模型请求每次上限 12 秒、最多两次，并检查 30 秒剩余预算；chat/embedding 进程内独立共享熔断。图谱与 Milvus 有读取超时，图谱 SDK 重试关闭。同步流程没有 SSE、后台调度、全轮硬取消或集群预算。本地 trace 仅节点/耗时/安全结果，LangSmith SDK 自动外发显式禁用；外部追踪、token/成本和全链路关联未实现。

```powershell
# backend 目录；先启动当前 API，固定合成输入走真实 Qwen：
..\.venv\Scripts\python.exe -m scripts.agent_smoke
# 隔离库回归、静态检查：
..\.venv\Scripts\python.exe -m scripts.verify -s
..\.venv\Scripts\python.exe -m ruff check .
..\.venv\Scripts\python.exe -m ruff format --check app scripts tests
..\.venv\Scripts\python.exe -m mypy app
..\.venv\Scripts\python.exe -m pip check
```

agent_smoke 检查问候、普通回答、关联追问、个人医疗转人工、幂等、历史和登出权限；仅输出模式/阶段/来源数量，不打印模型正文或密钥。M2 批次完整回归 **99 passed（144.61s）**；后续 M3 当前结果见 docs/production-readiness.md。

## M3 客户页面、会话恢复与公开目录

客户 Vite 5173 的 `/api` 已代理到 8001，首访无需员工登录。新增 `GET /api/public/stores` 只返回公开门店 code/name/simulated，生产过滤模拟门店；有有效公开知识的门店优先，避免默认进入空目录。`GET /api/visitor-sessions/current` 验证 HttpOnly 访客凭据，返回当前范围和 CSRF；已有有效 CSRF 可复用，缺失或无效才轮换。辅助 `ma_visitor_csrf` Cookie 可读、SameSite Strict，访客认证 Cookie 仍 HttpOnly；生产使用 Secure。

`GET /api/threads` 返回自己的最近 20 个线程；消息历史支持 `recent=true&limit=100&offset=0`，先取最新分页再按时间正序呈现。客户端引用不构成授权。`GET /api/catalog/projects` 与 `GET /api/catalog/projects/{version_id}` 读取当前门店有效公开目录；目录必须已批准、已发布、有效且投影版本一致，详情返回前再次复核权威层。

目录是现有知识的只读视图，没有独立报价/供给或医学批准。输出包含 title/summary/description/category/topics、知识版本/来源/期限/模拟标识和有限本地图片、详情路径。回答中的 project_ids 由服务端按问题/安全追问关联，不能仅因引用某条目录推荐无关项目；模型不生成图片或 URL。读取历史/重放也重新校验项目，不显示已撤回或越门店资料。

```powershell
# 先启动 8001 API 与 5173 客户 Vite；仅固定合成咨询调用真实 Qwen：
..\.venv\Scripts\python.exe -m scripts.customer_smoke
```

实际通过：真实生成回答、30 个模拟公开目录、1 个补水关联卡片、图片及详情、会话刷新、同键重放、历史、跨门店拒绝和登出。前端 17 + 12 项单元测试与双构建通过；浏览器桌面/390×844 手机验收记录见 docs/production-readiness.md。此为 M3 首批历史边界；后续本地预约/门店操作已实现，人工接通、SSE、注册后长期记忆和云部署未实现。

## M4 第二批：改约、取消与到店

API启动必须迁移至010，001–009不改写。在 backend 运行 `..\.venv\Scripts\python.exe -X utf8 -m app.migrate`，重启8001 API；前端5173/5175通过同源代理调用。既有 demo-operator 门店 read/manage grants 即可操作，不扩大其他账号权限，既有密码无需重置。

后台预约详情填写建议时间，核实接待并明确提出；提案等待客户本人在原对话中刷新预约记录后接受或拒绝。接受前原时间保持，30分钟过期后不能接受。客户展开取消区，勾选并明确取消仅待确认或已确认申请；原历史保留。确认预约且没有未回应提案时，员工核实身份/实际到店并登记，服务端记录时间，客户刷新可见。

接口/状态限制见 docs/data-contracts.md，事务与授权见 docs/architecture.md。新增专项验收 `..\.venv\Scripts\python.exe -X utf8 -m scripts.verify tests/test_booking_lifecycle.py`；完整回归 `-m scripts.verify -s`。测试只重置 ma_m1_test，不清空业务库。改约/取消/到店结构化快照本地加密，不能进入模型出口。未接 CRM、通知、收费取消规则和客户身份合并；真实短信仍待机构供应商实测。

## M5 首批：到店咨询档案与本人确认

M5首批迁移为011；当前 API 要求迁移至012，001–011不改写。先在 backend 执行下列命令，随后重启8001 API。种子只补新的开发模拟顾问，已有密码/撤销的 grants 不重置。不得在生产使用模拟员工、资料或核验。

```powershell
..\.venv\Scripts\python.exe -X utf8 -m app.migrate
$env:M1_SEED_PASSWORD = (Get-Content ..\runtime\m1-seed-password.txt -Raw).Trim()
..\.venv\Scripts\python.exe -X utf8 -m app.seed
Remove-Item Env:\M1_SEED_PASSWORD
..\.venv\Scripts\python.exe -X utf8 -m scripts.verify tests/test_consultation_cases.py
```

本地步骤：客户在5173原对话提交合成申请；demo-operator在5175确认并核实实际到店后登记。demo-consultant 登录后台“客户跟进”，选择该已到店预约、明确勾选后建立咨询档案；选择有效公开项目入口或保持未定，补称呼/咨询意向/客户可见变更说明，勾选追加新版本。客户在原对话刷新预约/到店咨询记录，审阅当前版本后确认或选择继续沟通；后台刷新可查看版本历史与处理时间。修改后必须由客户重新审阅，不将旧确认移到新版本。

demo-consultant 只拥有上海门店 appointment_read/customer_read/customer_manage，无完整联系方式、预约处理、知识或杭州权限。原 demo-operator 仍只处理预约，没有客户档案权限；作者/审核员/平台管理员也不默认访问档案。客户匿名凭据仅关联本次预约/线程，不合并同手机号访客；丢失凭据不能凭 thread_id 或手机号恢复。身份找回/注册与跨设备服务后续另做。

011咨询快照复用持久 Fernet/HMAC 密钥本地加密，意向版本/客户处理/幂等/审计原子提交。接口详见 docs/data-contracts.md；13项 PostgreSQL 专项测试覆盖确认/拒绝、历史与重放、权限/CSRF、证据撤回、审计回滚及修改/确认并发。完整回归结果见 docs/production-readiness.md。站内回访见下节；CRM、外部通知、资料删除/保留运维和实际身份核验尚未接入，咨询意向确认不代替治疗同意或合同。

## M5 第二批：站内回访与私有跟进

在 backend 执行 `..\.venv\Scripts\python.exe -X utf8 -m app.migrate` 应用012，重启 API8001。无需新增种子或扩大员工授权，现有 demo-consultant 上海 customer_read/manage 可用；不覆盖已有密码、grants或模型配置。

本地步骤：先完成上述已到店档案，并由客户确认当前意向。顾问在5175“回访管理”选择档案、未来计划时间与公开说明，勾选提出；客户在5173原对话刷新预约记录，在已到店申请下审阅站内计划，勾选同意或拒绝。同意后可选择有无疑问并明确提交反馈，顾问刷新队列查看结果、在详情追加内部跟进。客户页面看不到内部备注。拒绝/取消暂停新邀请；仅客户本人可恢复，恢复后新计划仍须本人同意。逾期或意向改变的待同意计划需顾问取消后重新提出。既有已同意计划保留历史，可反馈或取消。

专项 `..\.venv\Scripts\python.exe -X utf8 -m scripts.verify tests/test_followups.py`（15项）；完整 `-m scripts.verify -s`（191项）。隔离测试只重置 ma_m1_test，不能用业务库替代。类型/Ruff/pip check与双端66项单元/构建均通过。012任务/事件/命令和快照本地持久加密，授权/CSRF/版本/摘要/有效证据/幂等/审计与并发故障已测。反馈保存不等同人工回复；此服务不会发送短信/电话、调用模型或写CRM，真实外部渠道另行验收。

## 共情咨询与采集（2026-10-12）

现有知识导入 CLI 包含 data/empathy_knowledge.json，仍走独立审核/outbox；无需新增依赖或迁移，当前门槛012。生产不得用模拟审核替代真实医学批准。新增专项可在 backend 执行 `..\.venv\Scripts\python.exe -X utf8 -m scripts.verify tests/test_emotion_support.py tests/test_consultation_gateway.py`；只重置 ma_m1_test。真实合成对话采集 `..\.venv\Scripts\python.exe -X utf8 -m scripts.chat_quality_check --empathy`，输出独立 runtime/empathy-chat-report.json；使用已运行本地 API 和当前公开知识，可能调用已授权公开问题的 Qwen。数据、实现文件和实际结果见 [共情设计](../docs/empathy-design.md)。

## 默认Docker咨询运行时（2026-10-12）

启动前在本目录执行 `docker build -f sandbox/Dockerfile -t medical-consultation-sandbox:local .`；保留现有012迁移/数据库与LLM配置，不把.env传给容器。MA_AGENT_RUNTIME默认docker，生产禁止inprocess；变更app代码须重建镜像及重启API，启动时固定镜像ID。故障验收为独立probe镜像，专项需显式MA_TEST_SANDBOX_DOCKER=1。完整步骤、实际结果、保护范围和面试说明见 [运行时沙箱](../docs/runtime-sandbox.md)。
