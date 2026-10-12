# 实施与生产就绪记录

## 2026-10-11 M0

已完成：重新建立需求与架构基线；LangGraph 状态与恢复、漏斗、记忆、压缩、知识审核和投影、预约幂等、失败策略、追踪隐私、逻辑数据和接口、30 个验收场景设计。

实际检查：PowerShell `Get-ChildItem -Force`、`git status --short --branch`、上级 AGENTS 文件检查；仓库开始时仅 .git，无提交、无应用文件。阅读用户提供的 AGENTS 指令；PROJECT_SPEC、architecture、open-questions 旧文件不存在，本批重新创建。查阅官方 LangGraph/LangSmith 文档作为设计依据。

验证状态：PowerShell 校验通过：9 个必需文档存在且非空、README 本地链接有效、30 个验收编号唯一。`git diff --check` 返回 0，但文件尚未跟踪，因此该命令不构成新文件内容检查。没有运行应用、迁移、Ruff、类型、浏览器或业务测试，因为本批无应用实现。没有真实模型调用、数据导入、Git 推送或云部署。

尚未完成：M1–M6 全部运行功能、知识样例、依赖锁定、数据库、前端、机构后台与供应商验收。当前不可上线，不将设计文档等同于生产产品。

下一里程碑 M1：工程骨架、持久身份和门店权限、知识版本/独立审核/发布、带明确模拟标识的首批资料、迁移和隔离测试。仅完成一个可验收批次后再记录结果。

生产验收要求：核心功能真实可用、持久化与恢复、权限隔离、客户确认、独立知识审核、证据有效性、审计和幂等均通过；模拟数据与开发故障模拟器独立。真实医生资质、药械注册资料与医学批准不得用虚构记录替代。服务器未提供前不部署。

## 2026-10-11 客户前端预览批次

用户进一步指定 Vue 3 前端和 Apple 现代极简风格；先交付独立可审阅界面，不将前端演示替代 M1–M4 的真实链路。

文件：package.json、package-lock.json（安装后生成）、Vite/TypeScript 配置、index.html、src/App.vue、src/style.css、src/domain.ts、src/domain.test.ts、src/components/BotanicalArt.vue、docs/frontend-design.md。架构改为 Vue 3。

功能：响应式首屏、原创自然主题 SVG、咨询示例、分类/关键词筛选、详情弹窗、预约草稿校验及预览、隐私说明。未调用后端、模型或预约供应商。没有 Git 提交/推送、云部署。

验证：`npm install --registry=https://registry.npmjs.org --no-audit --no-fund --fetch-retries=1 --fetch-timeout=20000` 成功，88 个依赖；默认镜像安装无结果后终止。`npm test` 5/5 通过；`npm run build` TypeScript 与 Vite 构建通过，最终产物 JS 105.53 kB / gzip 40.74 kB。初次沙箱运行因 realpath EPERM 失败，在授权环境重跑成功。

浏览器实测：页面加载、补水示例回复与卡片、医疗美容分类过滤、详情弹窗、意向带入表单、空表单拒绝、合成信息生成脱敏草稿、390×844 手机项目/咨询布局、手机菜单展开/收起。修复桌面菜单误显示和弹窗切换焦点问题；最终弹窗使背景 inert，焦点落在关闭按钮。viewport 检查后恢复默认。`npm run dev` 服务曾在 127.0.0.1:5173 正常运行，浏览器加载成功；沙箱内 Invoke-WebRequest 被套接字权限限制，不把该命令记为成功。未使用独立 Playwright 测试套件，浏览器交互通过受控浏览器工具检查。

已知限制：lucide-vue-next 安装时提示弃用，后续接入生产前迁移到维护包并进行依赖审查；当前 Node 18 为本机开发环境，不代表生产运行时选择。正式上线缺项仍包括知识/模型链路、访客鉴权、持久化、核验、门店确认和机构后台。

验收后停止本批预览服务；用户执行 `npm run dev` 可重新打开预览。所有修改仍为未提交文件，未改变远程仓库。

## 2026-10-11 人物与医美场景视觉修订

用户反馈抽象插画符号化、缺少人及医美元素。替换首屏、4 个项目卡片及详情图；新增 public/images 的五张摄影风格 JPEG，原始素材保存在 assets/source-images，内置 image_gen 的最终提示词和用途记在 docs/image-assets.md。图片带 AI 示意标识，不关联真实人员/资质/效果，未改变咨询或预约业务边界。

已目视检查全部生成素材。桌面项目区、390×844 手机项目区、人物首屏及医美详情裁切正常，专业人员、护理动作及皮肤评估仪器可见。原图转换 JPEG 后总计 878,859 字节；项目图懒加载。`npm run build` 类型检查和构建通过，`npm test` 5/5 通过；五张素材分别 HTTP 200。浏览器 viewport 检查后恢复默认。浏览器 DOM 资源检查因受限求值 URL 失败，未记为成功，以实际截图和独立 HTTP 请求验证。未部署或推送。

本批本地预览保留运行供用户继续审阅视觉，地址 http://127.0.0.1:5173/ ，仅本机监听；最终结束设计预览时再停止，不属于云部署。若进程结束，可 `npm run dev` 重启。

## 2026-10-11 对话内预约协同修订

用户明确预约应从对话中由人机协同触发。src/App.vue 的独立预约弹窗已移除；所有预约入口进入对话，结构化动作生成意向卡，客户在卡内补充、修改和明确确认，回执仍为未提交草稿。src/domain.ts 增加 offer_booking/cancel_booking/handoff 动作，避免答复关键词误触发；方向变化或新提案使旧卡不可操作。新对话清理预约状态与测试联系方式。

验证：`npm run build` 类型检查与 Vite 构建通过，`npm test` 7/7 通过。浏览器实测普通咨询无预约卡、全局按钮进入对话、已有水润护理兴趣方向带入、对话内补充、明确取消勾选后提交被拒绝、勾选后生成脱敏未提交草稿、修改需重新确认。补充字段改变时清除旧勾选，不确定项目时使旧卡失效。当前界面仍不调用真实模型、持久 API 或 LangGraph checkpoint，不等于生产人机协同已接通。

390×844 手机端检查：对话中出现“不确定项目”的意向卡，补充与继续了解按钮完整可见，没有独立预约弹窗；检查后恢复默认 viewport。本地预览继续保留供用户审阅。

## 2026-10-11 M1 Agent 服务端基础

用户明确开始 Agent 开发。本批只实现可验收的 M1，未把 LangGraph/真实模型/知识图谱或前端联通描述为已实现。

文件：backend/app 的配置、领域 Protocol、PostgreSQL 适配器、身份/会话/知识应用服务和 FastAPI；backend/migrations 的基础迁移与审计结果增量迁移；backend/data/synthetic_knowledge.json；backend/tests 的真实数据库隔离、状态与故障验收；backend/scripts 的本地配置生成、验收及 HTTP smoke；锁定依赖、compose.agent-dev.yml 和 backend/README.md。更新 README、PROJECT_SPEC 与数据契约状态。

实现：随机 opaque 凭据只保存摘要，访客门店与会话持久化；员工凭据独立、scrypt 密码及持久失败限流；明确门店 grants，无授权的模拟平台管理员不能管理门店。访客修改需 CSRF，过期或撤销凭据不能恢复旧会话。版本创建串行分配，作者自审拒绝，模拟审核不批准真实内容，医学内容保持待审。发布状态、outbox 与审计同一事务提交；发布重复不重复建任务，撤回首先阻断权威读取。证据读取校验已发布、独立审核、期限、门店、当前版本和两种投影就绪。M2 worker 尚未实现，因此本批导入知识不能检索，返回空列表是明确的 M1 边界，不是生产核心功能交付。

环境与数据：使用实际 Python 3.12.14；安装并冻结依赖，pip check 无冲突。本机旧 medical-aesthetics 容器仍在运行，未读出其密钥、复用其数据库或修改它们。新建独立 medical-agent-m1 Compose、仅 127.0.0.1:55434 的 PostgreSQL 数据卷、ma_m1 与 ma_m1_test 数据库。ma_m1 导入六条标识明确的合成知识：五条运营/沟通经过独立账号模拟复核，状态 publishing；一条医学占位 draft，无医学批准。随机本地配置、种子密码、虚拟环境已由 git check-ignore 确认为忽略项。无 Git 提交/推送或云部署。

实际验证命令与结果：

- `docker compose --env-file runtime/m1.env -f compose.agent-dev.yml up -d --wait`：独立容器 healthy。
- 在 backend 执行 `..\.venv\Scripts\python.exe -m app.migrate`：两条迁移成功；重复迁移测试成功。`-m app.seed`：六条导入；重复执行不覆盖。
- `..\.venv\Scripts\python.exe -m scripts.verify`：最终 **25 passed，32.59 秒**。涵盖持久凭据/新应用实例读取、跨用户/门店隔离、作者自审、无门店授权平台管理员、普通访客调用员工接口拒绝、模拟/真实审核边界、医学阻断、过期/撤回/版本替换/投影未完成证据阻断、事务 outbox 回滚、并发版本唯一、登录限流、生产危险配置拒绝。
- 同一测试还注入真实 PostgreSQL 延迟约束失败，证明 COMMIT 失败返回 503、不发送成功 Cookie、不留下访客行；不是固定 mock 结果。
- `..\.venv\Scripts\python.exe -m ruff check .`：通过。`-m mypy app`：10 个源文件严格检查通过。`-m pip check`：无依赖冲突。当前 TestClient/httpx 有一条 Starlette 弃用提示，未隐藏。
- `-m uvicorn app.main:app --host 127.0.0.1 --port 8001 --no-access-log`：启动成功。`-m scripts.smoke`：实际 HTTP 就绪、模拟访客、创建/读取线程、未投影证据过滤、退出及旧会话拒绝均通过。首次默认 HTTP 环境代理返回 502，直连本机返回 200；smoke 显式 trust_env=False 仅用于本机，不改变后续模型出口配置。

本批未改前端，无新的前端业务或 UI 验收；此前前端结果仍适用。保留本地 API 与独立 PostgreSQL 供继续开发，API 文档 http://127.0.0.1:8001/docs 。重启、验证和停止方法见 backend/README.md。

当前仍不可作为完整咨询产品上线：M2 模型/检索/图谱/checkpoint/记忆/压缩/重试熔断/追踪、M3 前端真实咨询与预约、M4 机构操作均未完成。真实医疗批准、知识来源和实际机构供给需核验；完整拒绝审计、访客防滥用、保留/删除、外部身份、TLS/代理、备份恢复与容量需后续验收。未做真实 Qwen 调用，也未承诺 100 RPS。下一里程碑 M2。

## 2026-10-11 前端目录整理与后台首版批次

用户要求将前端相关代码集中到一个文件夹，并开发机构运营后台前端。本批完成 frontend/customer 与 frontend/admin 双应用；没有将机构业务后端 M4 或 Agent M2 标为完成。

迁移：将原根目录 src、public、assets、index.html、tsconfig.json、vite.config.ts 直接移动到 frontend/customer；锁文件移动并更新为 frontend/package-lock.json。没有重复复制图片、覆盖客户界面或删除旧本机缓存。移动前验证绝对目标位于 D:\medical_aesthetics 内且目标不存在。根 package.json 仅保留命令转发，前端统一 npm workspace；两个应用独立构建产物。新增 frontend/README.md，并更新根 README、PROJECT_SPEC、架构/数据契约/素材/前端说明。源码格式整理仅对新增后台及新配置执行。

后台代码：frontend/admin/src 的 layouts、views、components、services、styles、router/state/types；新增登录、工作台、预约管理、客户跟进、项目目录、知识管理和账号门店页面，保持暖白/浅绿/深绿的简洁风格。搜索/筛选、预约详情/明确核实/状态历史、客户意向历史追加、目录编辑/默认隐藏、知识独立审核/发布申请/撤回等交互已实现。桌面导航、手机菜单、门店切换、抽屉焦点约束和背景 inert 已实现；修复手机关闭导航仍可聚焦的问题。

真实接入：backend/app/api.py 与 services.py 新增 GET /api/staff/me 和 GET /api/stores/{store_id}/knowledge 分页读取，重用既有 bearer 身份、tenant/store grants 和权限边界，不增加客户资源访问权。后台员工登录、授权门店读取、知识列表与创建/审核/发布/撤回接本地 API；账号凭据仅内存，刷新重新登录。真实业务未实现的预约/客户/目录页面保持待接入空状态，不拿模拟数据填补 API 失败。

演练隔离：仅开发构建有“进入界面演练”；该模式无真实员工 token、不能调用真实 API，所有客户/预约/目录/审核资料明确合成标识，仅当前页面会话保存。生产构建无演练入口；知识医疗批准继续阻断，作者不能自审，发布仅进入等待投影。没有模拟注册证、真实医生资质或医学批准。本地 demo 不等于生产业务已完成。

运行：客户仍为 127.0.0.1:5173；5174 已有其他服务，未停止它，后台独立使用 127.0.0.1:5175。后端本任务 API 在 8001 重启加载新接口；默认、示例、生成器及本任务开发 .env 的来源清单同步加入 5175，未打印或提交凭据。Git 确认 node_modules、dist、本地 .env/runtime 均被忽略；所有代码仍未提交/推送，无云部署。

实际验收：

- frontend 的 `npm install --registry=https://registry.npmjs.org --no-audit --no-fund --fetch-retries=1 --fetch-timeout=20000`：统一 workspace 锁文件及两端依赖安装成功，新增 vue-router；使用 Prettier 3.6.2 格式化新增源码。已有 lucide-vue-next 弃用提示保留为后续依赖治理事项。
- 根 `npm run build` / frontend `npm run build`：两端 TypeScript 与 Vite 成功。客户 JS 104.92 kB/gzip 40.51 kB；最终后台 JS 122.62 kB/gzip 47.86 kB，页面按路由拆分。移除初稿空 CSS import 后最终构建无此警告。最终客户入口 URL 配置修正后单独后台构建再次通过。
- 双前端 `npm test`：客户 7/7、后台 12/12，共 19 项通过；覆盖权限、演练禁止真实 API、登录过期清理、预约状态/明确核实、作者自审/医学/过期/撤回操作限制。最终后台修订后 12/12 复验通过。
- backend `..\.venv\Scripts\python.exe -m scripts.verify`：28 passed，31.69 秒；新增三项包括授权门店资料、分页知识、无授权平台管理员/访客拒绝。既有真实数据库身份、发布、事务故障及生产配置场景仍通过。一条 TestClient/httpx 弃用提示未隐藏。
- backend `-m ruff check .`、`-m mypy app`：最终通过，10 个应用源文件严格检查通过。
- `-m scripts.admin_smoke`：经 Vite /api 代理实际 HTTP 登录、门店 grants、越店拒绝、新合成版本、作者自审拒绝、另一账号审核、发布 publishing、分页读取、撤回和退出全部通过。合成验收版本已撤回，审计和 outbox 保留，不伪装已发布。没有输出密码或 bearer。
- 五张迁移客户 JPEG 实际 HTTP 全部 200；受控浏览器客户页面刷新后首屏、项目图片和咨询入口可见。
- 后台桌面/390×844 实测：演练登录、错误真实登录/密码清理、预约未核实拒绝与确认历史、知识未勾选拒绝/独立审核/发布等待投影、医学批准按钮禁用、客户历史追加保留最初意向、目录新增默认隐藏与搜索、手机菜单/门店切换/知识表水平滚动。viewport 已复位；没有独立 Playwright 测试套件。
- 临时 5181 生产构建预览实测登录页：演练按钮数量为 0，未配置客户 URL 时无本机链接。验证后关闭临时标签并停止该预览服务。客户和后台开发预览、本地 API/数据库保留供继续开发审阅。

下一批仍是 Agent M2；再按 M3/M4 实现预约、客户、项目管理业务接口与后台真实闭环。后台当前是有部分真实接口的首版前端，不是完整运营系统或可上线产品；TLS/代理部署、真实业务资料/医学核验、认证治理、记录保留与容量验收仍待补齐。

## 2026-10-11 M2 第一批：知识数据与检索管道

目标：先完成可验收的数据构造、版本化导入与投影/检索管道；没有将完整 M2 或 LangGraph 对话标记完成。

新增文件：backend/data/consultation_catalog.json；app/knowledge_types.py、knowledge_import.py、knowledge_worker.py、model_gateway.py、graph_adapter.py、retrieval.py；migrations/003_knowledge_projection.sql；scripts/graph_config.py；tests/test_knowledge_pipeline.py、test_model_gateway.py。调整 API/config/services、依赖锁、compose、环境模板与相关文档；没有改变客户前端或后台业务界面。

数据：新增 32 条（10 个模拟项目了解入口、12 条运营流程问答、6 条内部沟通策略、4 条医学资料采集待审任务）。独立开发作者/审核账号沿用既有权限服务；真实机构价格/人员/注册和临床医学知识没有编造。重复导入 skipped=32、created=0，不刷新期限、不复活撤回版本。数据库共有 38 条种子/扩充资料，另有此前 HTTP 管理验收的撤回记录，不将其计入知识数据集。医学共 5 条仍 draft。

实现：结构校验、导入摘要凭据、公开/内部 audience、版本绑定 pgvector(256) 与 Neo4j 知识实体/关系投影；outbox 短事务租约/令牌围栏/SKIP LOCKED/退避/安全错误代码、外部调用后重新校验权威版本；两个投影完成才 published。检索仅消费允许门店的有效公开版本，适配器不接任意 SQL/Cypher，返回前复核权限/期限/版本/撤回。模型 HTTP 实现固定中国端点、text-embedding-v4 / 256 维契约、SecretStr、脱敏、超时、有限重试和进程内熔断；保留精确合成出口白名单，未扩大外部出口。

实际验证：

- 安装 neo4j 5.28.6 与 pytz 2026.5，更新 requirements.lock；pip check 无冲突。
- docker compose --env-file runtime/m1.env -f compose.agent-dev.yml up -d --wait：独立 Neo4j 5.26 / PostgreSQL healthy，未修改旧项目容器；凭据仅忽略文件，端口只监听 127.0.0.1。
- python -m app.migrate：003 应用成功；app.knowledge_import 首次 created=32/medical_pending=4，再次 skipped=32。
- python -m scripts.verify：52 passed（55.69s）；真实隔离 PostgreSQL/pgvector，真实本地 Neo4j 重复投影/关系唯一/租户隔离/删除。模型故障使用明确测试替身，未执行真实 Qwen。
- Ruff、mypy app（16 个源文件）及 pip check 通过。后续针对员工停用和补充故障场景的验证结果追加于本节。
- python -m app.knowledge_worker：开发库图谱写入，未经配置的精确出口全部拒绝，vector_ready=false、state=pending，不宣称知识已发布。安全代码 export_not_authorized，不持久化供应商正文或密钥。
- scripts.pipeline_status 实际读取：33 个图谱版本；publication pending/graph_ready=true/vector_ready=false 共 33；医学 draft 共 5；历史 HTTP 管理验收撤回记录 1。没有可检索的已发布证据。
- 最终扩展回归首轮 55 passed / 1 fixture error（数据库单次连接超时，401.26s），不是业务断言失败；没有隐藏该失败。异常回溯包含本地开发连接信息，因此已轮换此独立开发数据库生成口令，同步忽略配置并重启本任务 API；pytest 默认 --tb=short，避免局部连接变量出现在诊断输出。
- 重启后的 scripts.smoke：readiness/session/thread/evidence/search/logout 全部通过，没有模型调用；ready.scope=api-database，只表示 API/数据库检查。
- 连接恢复、员工停用检查和短回溯配置后的最终完整回归：56 passed / 1 warning，58.64s；warning 为既有 Starlette/httpx TestClient 弃用提示。Ruff 检查/格式、mypy app 与 pip check 最终通过。没有新增前端改动，因此未重复前端构建或浏览器视觉验收。

局限：当前未配置 Qwen key/精确授权出口，未验证真实 embedding 或 chat；医学资料只有待审任务，无可发布临床知识。尚无 LangGraph、对话消息/checkpoint、长短期记忆/压缩、完整链路追踪、客户图文关联或预约业务。当前短条目整条向量，长文切块/重排尚未完成；熔断仅单进程，分布式协调、完整响应预算、图谱定期校验/重建、独立读写账号和生产部署仍待验收。租约过期极端并发可能留失效图节点，PostgreSQL 二次过滤必须保留，不能直接信图谱。未测 100 RPS，当前不能上线为完整产品。下一批完成 LangGraph 咨询编排与持久对话。

复现命令与配置在 backend/README.md；既有 8001 API 更新代码后需重启，前端 5173/5175 不受本批影响。

## 2026-10-11 M2 扩展批：Milvus 与 226 条知识数据

用户明确选择 Milvus，并要求知识尽量丰富、完整。本批目标是迁移向量投影与授权检索、扩展数据、验证隔离和未知写入恢复；完整 LangGraph 咨询仍留给下一批，不将 Milvus 空业务集合包装为已完成生产咨询。

文件：新增 backend/app/vector_adapter.py、migrations/004_milvus_projection.sql、scripts/milvus_config.py、scripts/milvus_init.py、tests/test_milvus.py、tests/test_milvus_pipeline.py；新增 data/consultation_expanded.json、retrieval_cases.json、retrieval_holdout.json。调整 config/services/api、knowledge_types/import/worker、retrieval、测试 fixture、pipeline_status/verify、requirements 与锁文件、compose.agent-dev.yml、环境模板及 README/产品/架构/知识/待确认文档。未改前端。

数据：原 6 + 32 + 新 226 共 264 条，不计历史 HTTP 管理验收的撤回版本。新数据为 20 项目了解入口、100 运营问答、40 内部策略、40 多轮场景、6 官方品牌概况、20 医学/监管待审摘要。覆盖发现需求、项目比较、价格范围核实、预约/取消、隐私、门店、到店和售后流程。官方品牌信息附投资者官网来源；医学/监管摘要逐条附来源、2026-10-11 查阅日期及 CN/US 地区。FDA 资料不能作为国内注册或适用性证明；一条 NHC 页面访问 412 的摘要明确标注索引来源和原文待复核。所有导入保留本地模拟标识；医学 25 条全为 draft，未虚构医学批准/资质。策略/场景为 internal，不能直接成为客户证据。原目录和扩展均重复导入 skipped=32/226、created=0，新增字段不导致旧版本重复。

实现：Milvus 2.5.27 + pymilvus 2.5.18，256 维 HNSW/COSINE，Strong 查询；新独立 etcd/MinIO/Milvus 数据卷，只绑定本机 59531/59091。启动前生成随机 root/存储/服务账号密码，不使用默认 root 密码。root 仅离线建集合与授予集合权限；API read 与 worker write 独立角色，实际验证 reader 不能 upsert。PostgreSQL 仍是权威，Neo4j 是知识关系，历史 pgvector 003 不改写、旧表保留但当前应用不读写；004 增量建立 vector_projection 并重排历史发布。新向量 metadata 包含门店、租户、版本、摘要、模型、期限、audience 和模拟标识。

Upsert 前持久 unknown 回执，超时后先查询对账；匹配复用，不重复模型/写入；查询失败不盲写，元数据冲突拒绝。最终 published 前仍重新校验租约、审核、门店与新版本。证据要求 ready 回执/正确集合/内容摘要匹配；向量结果复核模型/版本/摘要，返回前再查 PostgreSQL 权限/期限/撤回。队列按 available_at/id 领取，避免早期失败记录反复占据处理顺序。

实际验收记录：

- Compose 独立五个服务 healthy；本项目旧容器与旧项目数据未读取/修改。已应用 004；迁移校验及重跑在隔离测试库验收。
- 数据首次新增 created=226、medical_pending=20；重复两个文件 skipped=32/226。
- 开发库 worker 处理上限 500 次，安全错误 export_not_authorized，不调用 Qwen；状态读取为 239 publishing / 图谱就绪 / 向量未就绪，25 draft，另有 1 历史 withdrawn。Neo4j 版本 239；主 Milvus owned_vectors=0，回执表为空，符合未授权生成真实向量的状态。
- 新增真实 Milvus 测试覆盖重复写入/Strong 对账/检索/删除、租户与门店/内部/过期/模型/模拟过滤、read 禁写、UUID 注入与无效向量。完整 PostgreSQL worker → 实际隔离 Milvus 集合 → 授权检索使用 test-only 固定向量，结束按随机 ID 删除；无固定向量进入主业务集合。
- 31 条独立改写问题的词项降级 recall@5 在排序修正前两轮为 28/31 和 27/31；随机 UUID 同分排序导致波动，已改为知识条目键稳定排序，最终结果另记下方。仅是本地非语义小集；100 条关联题目是覆盖样例，不能声称生产效果、真实模型或容量达标。
- 首次误用直接 pytest，隔离测试库环境未设置，保护性失败 49 errors / 18 passed，未访问业务库。改用 scripts.verify 后 66 passed / 1 failed（116.93s）：失败测试原本依赖 ID 顺序，和新公平领取顺序不一致；已改为验证有限步内撤回清理及始终未写向量。最终回归结果另记下方。
- 修正撤回测试后完整回归 67 passed / 1 warning（114.07s），之后进一步修正同分排序复验。Ruff 与 mypy app（17 个源文件）及 pip check 通过。真实 Qwen key/精确出口白名单仍未配置；本次扩展没有扩大模型出口。没有前端变更、云部署、Git 提交或推送。
- 本任务 API 8001 重启加载新代码（首次自动审批超时，允许的单次重试启动成功），scripts.smoke 实际 HTTP readiness/session/thread/evidence/search/logout 全部通过。仍保持 239 个待投影版本过滤，无真实模型调用；就绪状态仅表示 API/数据库。

生产限制：LangGraph、自由对话、长期记忆/压缩/追踪、图文关联、真实预约与运营后端仍未完成。真实机构供给、政策和医学审核必须核验；Milvus/Neo4j 生产网络与 TLS、备份恢复、全图重建、依赖安全（本地 etcd/MinIO 版本较旧）、跨实例熔断/预算和容量尚未验收。开发 standalone 配置不能直接用作生产部署配置；没有承诺 100 RPS。

本地复现按 backend/README.md 初始化，再运行 scripts.verify、pipeline_status、smoke；下一批实现 LangGraph 和持久对话。当前不需要用户提供成套数据；实际 Qwen 调用需本地 key 与明确出口范围，正式上线前需真实门店/项目/价格/政策、医学审核与服务器/域名。

最终验收：`python -m scripts.verify -s` **67 passed / 1 warning，118.58s**；同分稳定排序后词项降级 recall@5 **27/31（87.1%）**。警告为既有 Starlette/httpx TestClient 弃用提示。`ruff check .`、`ruff format --check app scripts tests`（35 文件）、`mypy app`（17 文件）、`pip check` 和实际 HTTP smoke 均通过。真实供应商、语义效果、完整 Agent 与生产容量仍未验收。

## 2026-10-11 M2 真实模型配置与全量知识向量化验收

用户明确已在 .env 提供 LLM_MODEL、LLM_API_KEY、LLM_URL，并授权“向量化出口范围现在是全部”。本批接入该配置、记录当前知识授权快照、生成真实 Milvus 向量并验收模型/检索；不跨到完整 LangGraph 开发，不变更医学审核和客户业务出口。前述未配置状态是历史记录，以本节为当前状态。

文件：修改 backend/app/config.py、model_gateway.py、tests/test_model_gateway.py、tests/conftest.py、scripts/smoke.py 与 .env.example；新增 scripts/authorize_knowledge_exports.py、model_probe.py、semantic_retrieval_check.py；同步根/服务端 README、PROJECT_SPEC、架构/知识/待确认文档。本地 .env 只更新授权摘要，保留用户模型参数与密钥；本地 runtime 授权快照/评测报告均忽略，不提交任何真实 Key。

配置：LLM_* 优先于旧 MA_MODEL_BASE_URL / MA_MODEL_API_KEY / MA_CHAT_MODEL，显式构造参数仍可覆盖测试夹具；用户给出的裸 dashscope.aliyuncs.com 自动补全固定 HTTPS compatible-mode/v1，拒绝不安全协议与其他域名。API Key 始终 SecretStr，不输出。Chat 保留 qwen3.7-plus，embedding 独立保持 text-embedding-v4 / 256。默认环境代理本次实际可用，没有调整代理或 TLS。新增固定合成 chat 探测只经过 Model Gateway、精确摘要授权、非流式、enable_thinking=false 和 max_tokens=32；返回连接元数据，不保存供应商正文。

授权：264 条当前版本控制知识、131 条合成检索题、1 条固定合成探测，共 396 个精确摘要，记录 runtime/model-export-authorization.json 与本地 MA_MODEL_EXPORT_HASHES。只取三个知识数据文件及合成评测文件，没有读取客户身份/业务记录，不发送旧项目密钥或数据库。导入仍不自动授权未来内容，变化后需更新授权记录。医学资料获出口授权仍保持 draft，未批准/发布/进入客户检索；内部沟通资料仍为 internal。

实际命令与结果（backend 目录，均使用 ..\.venv\Scripts\python.exe）：

- `-m scripts.authorize_knowledge_exports --record-user-authorization`：documents=264 / synthetic_queries=131 / authorized_hashes=396。
- `-m scripts.model_probe`：真实 text-embedding-v4 connected / 256 维；真实 qwen3.7-plus chat connected。不是 MockTransport 或固定假向量，HTTP 正文与凭据未输出。
- `-m app.knowledge_worker --max-events 300`：239 次 published 后 idle，未出现新的供应商错误。延续短事务/租约和 unknown 对账逻辑，真实向量只写 ma_knowledge_256。
- `-m scripts.pipeline_status`：239 published / ready 双投影 / ready Milvus 回执；Neo4j versions=239；Milvus owned_vectors=239；outbox 空；25 draft；另有 1 历史 withdrawn。数据集仍是 264，不把历史验收撤回记录计入。
- 本任务 8001 API 重启加载真实配置与授权，无改动前端或其他服务。
- `-m scripts.semantic_retrieval_check`：经实际匿名访客 Cookie/CSRF API 发 31 条授权合成独立问题，全部 hybrid，recall@5=30/31（96.8%），未命中 qa-compare-06；结束退出访客会话。报告存 runtime/semantic-retrieval-report.json。这是词项/Qwen/Milvus/Neo4j/权威复核的混合检索小集，不是纯向量效果、临床效果或生产容量结论。
- `-m pytest tests/test_model_gateway.py -q`：19 passed，含 LLM 别名优先、SecretStr、域名归一/危险地址拒绝、聊天授权/非流式参数/无效响应熔断、HTTP 安全状态码及既有脱敏/失败重试。
- `-m scripts.verify -s`：**74 passed / 1 warning，117.92s**；隔离 PostgreSQL 和真实 Milvus 测试集合，测试 fixture 显式覆盖真实模型 Key/摘要，避免意外外发测试业务。独立词项降级 27/31 与真实 hybrid 30/31 分别记录。警告为既有 Starlette/httpx TestClient 弃用提示。
- mypy app（17 文件）通过；Ruff 首次报告新增脚本 UTC 旧别名，已修正，最终静态与实际 HTTP smoke 结果补记下方。

限制：239 条均有本地模拟标记/模拟独立审核，不代表真实公司供给或医疗核验。完整 LangGraph、客户聊天输出/记忆/压缩/追踪和预约/运营闭环仍待实现；医学/说明书/真实资质、云服务器、生产 TLS/备份恢复/跨实例熔断及容量仍需后续验收。当前不需要用户再次提供模型 Key 或再次授权这批知识；下一批继续 LangGraph 持久对话，实际部署仍等待服务器信息。没有云部署、Git 提交/推送或前端变更。

最终复核：Ruff 检查、38 个文件格式检查、mypy app 和 pip check 均通过；新版 scripts.smoke 实际 HTTP readiness/session/thread/evidence/search/logout 全部通过，使用已授权合成问题验证发布后的受限证据与检索。运行方式见 backend/README.md 的“LLM 配置与真实知识向量验收”。

## 2026-10-11 M2 LangGraph 持久咨询后端

目标：在已有真实 Milvus/Neo4j 检索上实现客户自由问题的 LangGraph 后端，验收普通回答/追问、短期记忆、故障恢复及权限/证据失效。本批未跨到 M3 前端接入、图文目录或预约写入。执行前已说明批次目标、影响的后端/测试/迁移/文档及验收标准；读取规范/架构/待确认、检查 Git 和适用指令。不覆盖用户配置或修改其他项目容器，没有 Git 提交/推送或云部署。

实际文件：新增 backend/app/agent_policy.py、agent_repository.py、agent_checkpoint.py、consultation_gateway.py、consultation_agent.py；新增 migrations/005_consultation_agent.sql、006_checkpoint_write_order.sql；新增 tests/test_consultation_agent.py、test_consultation_gateway.py 与 scripts/agent_smoke.py。修改 api.py、model_gateway.py、graph_adapter.py、tests/test_foundation.py、requirements.in/lock，更新根/服务端 README、PROJECT_SPEC、architecture、agent-design、data-contracts、open-questions 及本记录。API 迁移启动门槛为 006，历史迁移不改写。具体代码可按上述文件审查。

实现：LangGraph 1.2.14 / checkpoint 4.2.0，本地有限规则 classify → fixed/handoff/retrieve → generate → validate。先校验持久访客/门店/自有会话；普通问题自动回答，问候固定模板，个人医疗/身份业务/越权或缺证据转人工。检索只取 PostgreSQL 批准、发布、当前有效且投影一致的公开证据；internal 策略/场景不作为客户回答证据，医学仍待审。Qwen 仅通过 Gateway，实际公开咨询出口沿用既有明确授权（脱敏当前问题、必要公开追问及重新核验公开证据），不扩大 396 个批量摘要快照。严格结构化段落核验引用 ID/原文摘录、数字、链接/联系方式与禁用承诺；无效回答或模型失败仅返回仍有效证据摘录。输出保留模拟标识，目录 URL 不由模型编造。

消息/原始输入本地持久化；checkpoint 是自有 JSON，保存有限派生状态，不序列化原始输入/医疗档案/凭据或任意可执行对象。每次 checkpoint/节点访问验证会话、租约与身份，90 秒 lease + fence，旧运行不可覆盖新状态。message_id 持久幂等，同键异文 409；失败/到期原键恢复。最终回答、工单、记忆、幂等结果和审计事务提交后才返回。生成途中登出不送达，撤回证据不引用，重放和历史也复核知识有效性。END checkpoint 后提交失败恢复不重复生成。pending writes 可先于父 checkpoint 保存；006 改为 run 外键而非删校验，保证 run 授权并支持框架异步持久顺序。

短期记忆取最近六条可外发已完成用户问题，给模型最多四条、每条 500 字符；有界抽取摘要带来源消息 ID、版本、意图/阶段及拒绝预约状态，拒绝偏好跨窗口保留到明确改变，不提取医疗事实，不跨 thread。转人工工单 waiting/connected=false；visit_interest action submitted=false。没有真实预约、顾问接通或医学批准。节点 trace 仅名/耗时/安全结果，本地图运行显式禁用 LangSmith 自动外发。chat/embedding 在进程内独立共享熔断，半开单探测；模型每次最多 12 秒/两次尝试并检查 30 秒剩余预算，图谱/向量有读超时，图谱 SDK 重试关闭。外部调用不持有业务数据库事务；初始化异常安全标 failed 并关闭已创建资源。

验收过程（backend，使用 ..\.venv\Scripts\python.exe）：

- 独立开发库应用 005/006；隔离 ma_m1_test 从头迁移及重跑验证。最初 targeted 问候/幂等通过，个人医疗路径暴露 pending writes 先保存时父 checkpoint 外键错误，已增量修复 006；随后 13 项目标测试通过（26.89s）。
- 首次完整 scripts.verify -s：89 passed / 1 failed（143.33s），失败为既有迁移重放测试仍按四个迁移计数；改为六个。补充模型出口、生成中撤回、初始化失败测试后完整回归 98 passed（144.28s）。最后资源部分初始化清理测试及最终结果见下方。
- Gateway MockTransport 独立检验实际公开问题不要求 bulk hash、脱敏电话/邮箱、必要公开追问、只使用重新读取的证据而非调用者伪造正文、固定模型/结构化参数、医学/身份/越权/预约当前或历史输入不外发、过期预算和无效来源不调用供应商。此项不冒充真实供应商验收。
- 实际 scripts.agent_smoke 两轮均通过：固定问候、两个真实 Qwen 生成回答（各三条来源）、个人医疗问题本地 handoff，逐条同键重放/已完成 run、八条持久消息、登出后 401。固定合成问题经过真实本地 API、LangGraph、Qwen、Milvus/Neo4j 和 PostgreSQL；不打印供应商正文、客户业务或密钥，不是 TestEmbedding 结果。
- API 重启至 006 启动门槛；scripts.smoke 实际 HTTP readiness/session/thread/evidence/search/logout 通过。依赖锁更新为本次实测 Python 3.12 Windows 环境，pip check 无冲突。Ruff 检查/46 文件格式检查、mypy app（22 文件）通过。

限制：客户页面仍是本地演示，待 M3 接真实消息与图文目录；预约草稿/客户确认/门店处理与员工运营闭环尚未实现。跨会话长期记忆须注册核验/知情同意/来源和删除机制后启用，不把短期摘要宣称长期记忆。规则守卫及引用/数字校验不是完整语义蕴含或医学安全证明，须更广泛对抗测试和真实知识核验；目前真实机构供给、价格、医学/资质仍未确认。同步请求没有 SSE/后台调度，30 秒为网关剩余预算检查，不是全流程硬取消；统一数据库预算、跨实例熔断/限流、token/成本和完整 trace、访客防滥用、保留/删除、TLS/备份恢复与容量仍未验收。没有 100 RPS 达标或完整产品可上线声明。

本地复现：先按 backend/README.md 初始化、migrate 至 006 并启动 8001，再运行 scripts.agent_smoke 和 scripts.verify -s。下一批 M3 接客户真实对话与项目图片/简介/详情入口；之后做对话内明确预约确认。云部署仍等待服务器/域名，不需要用户再次提供已配置模型 Key。

最终复核：资源部分初始化清理测试补齐后，`python -m scripts.verify -s` **99 passed，144.61s**；Ruff 检查、46 文件格式检查、mypy app（22 文件）通过。最终 API 已重启加载全部代码（本任务 8001），启动成功并保留运行；本地 .env、runtime 配置及授权快照均被 Git 忽略，锁文件不含本地路径依赖。重启后真实 HTTP Agent 复验结果另记下方。

重启后最终 scripts.agent_smoke 通过：fixed → generated（三条来源）→ generated（三条来源）→ handoff/personal_medical；逐条幂等与已完成状态、八条消息历史、登出 401 均通过。仅固定合成输入经过真实 Qwen，无客户业务外发。本批真实 Agent 合成 HTTP 共三轮均通过，最终结果与当前运行代码一致。

## 2026-10-11 M3 首批：客户真实咨询、历史与图文目录

目标：客户首页直接提问，连接已有 LangGraph/Qwen 后端；先回答再展示相关图片、简介与有效详情，刷新可恢复自有对话，门店切换和来源失效保持权限边界。本批仅验收咨询/目录，正式预约草稿、客户确认与门店处理为下一批。执行前已说明目标、影响前端/会话目录 API/测试/文档和验收标准，阅读项目规范并检查 Git/适用指令。不提交/推送、不云部署，不更改其他项目服务或用户模型密钥。

实际文件：新增 backend/app/catalog.py、tests/test_customer_catalog.py、scripts/customer_smoke.py；修改 api.py、services.py、retrieval.py、agent_repository.py、consultation_agent.py、agent_policy.py 和两个 consultation 测试。新增 frontend/customer/src/types.ts、services/api.ts、services/conversation.ts、components/ProjectCard.vue、services 两个测试及 tests/fixtures.ts；替换 ConsultationPanel.vue、domain.ts/domain.test.ts，修改 App.vue/style.css/vite.config.ts。同步根/前后端 README、PROJECT_SPEC、architecture、agent-design、data-contracts、frontend-design、open-questions、acceptance 和本记录。没有新增迁移或依赖，006 门槛不变。

实现：首次匿名会话、current 认证/CSRF 恢复、最小公开门店列表、自有最近 20 个线程、最新 100 条历史分页。读取正文、线程、项目及详情继续服务端鉴权，thread_id/浏览器引用不充当凭据。已有 valid CSRF 不因刷新轮换，缺失才轮换；替换访客仍要求旧 CSRF。浏览器仅保存 visitor/thread 引用，原始消息在本地 PostgreSQL；刷新/重新聚焦读取最新权限与证据，过期/跨身份/越店清理旧数据。网络未知提供核实或同 message_id 重试，不自动重复发送；csrf_invalid 写前拒绝可更新令牌原键重试一次。安全错误不显示供应商正文，不退回固定示例。

目录：从当前已批准、已发布、有效且投影一致的公开 catalog 版本派生，元数据后再次权威复核。30 个上海模拟入口；医疗分类只为非临床了解入口，25 条医学资料仍待审。有限本地 AI 人物/护理/医美咨询图片映射，来源/版本/期限与模拟标识展示；模型不提供 URL。普通回答按问题及安全上一问关联最多三张卡；个人医疗或业务请求无推荐。重放/历史重新过滤已撤回项目，详情 deep link 每次重新授权。删除了本地假回复与预约表单，visit_interest/submitted=false 和 waiting/connected=false 明确尚未预约/接通。

验证与修复：

- 后端 `..\.venv\Scripts\python.exe -X utf8 -m scripts.verify -s` 最终 **110 passed，253.13s**。包括真实隔离 ma_m1_test PostgreSQL、真实 Milvus 测试集合及合成网关 fixture；不把测试向量或 MockTransport 说成真实 Qwen。测试覆盖目录范围、元数据读取中撤回、CSRF/会话/线程授权、最新历史顺序、项目重放失效和无关推荐拒绝。新增术后肿胀/发痒本地医疗转接及 Gateway 当前/历史输入不外发回归；规则依然非完整医疗识别。
- Ruff check 通过，format --check（49 文件）通过；mypy app（23 文件）通过。既有依赖锁不变。
- 根 `npm test`：客户 **17 passed**、后台 **12 passed**。根 `npm run build` 双应用 TypeScript/Vite 通过；最后标识模板修改后 `npm run build --workspace @ma/customer` 再次通过。
- 默认沙箱 Node/Vite/Vitest 发生 EPERM 实路径限制，经过授权的正常本地运行完成验证；未将沙箱失败当作通过。首次浏览器接入发现原生 fetch 未绑定全局导致 Illegal invocation，修复 fetch.bind(globalThis) 并补回归。目录 entity 位置在独立字段，初版误从 guidance 读取，已修复并覆盖目录图文测试。
- 真实 `scripts.customer_smoke` 从 5173 同源代理到 8001，通过真实 Qwen 生成回答、30 目录/1 补水卡、图片/详情、会话刷新、同键重放、历史、换门店后目录为空/旧项目和旧线程 404、退出后 401。只使用固定合成问题，输出元数据，无密钥/供应商正文/客户业务数据。
- 受控浏览器 Playwright 定位器实际验证普通补水问题与到店追问、来源展开、图片详情 deep link/详情刷新、八条消息恢复、预约意愿尚未提交和医疗问题尚未接通。显式切杭州后旧消息/目录清空，上海详情不可读取，再切上海创建新会话。没有新增独立 Playwright 测试套件。
- 浏览器追问曾因引用加分带出无关肤质卡，修复为问题先有明确匹配再按引用加分，新增单元/集成覆盖。手机 390×844 内容宽 376/376，无水平溢出；桌面 1280×1000 内容宽 1265/1265。实际图片加载，既有 AI 图无新增生成。截图在忽略的 runtime/m3-customer-desktop.png 与 m3-customer-mobile.png；测试视口交付前复位。
- 最终 8001 API 重启加载本批完整代码，Vite 5173 保留可体验；不停止旧 5174 服务。Git 所有项目源码仍为未提交文件，.env/runtime 被忽略，没有真实密钥提交。

剩余：本批完成客户真实咨询和图文，不能宣称完整生产产品已可上线。目录仍是模拟机构供给/独立开发审核，AI 图不代表官方/真实效果；医学/注册/执业资质不可虚构有效。正式预约、联系方式供应商核验、客户确认快照/审计/幂等写入和员工接待处理尚未实现；跨线程长期记忆仍需注册和同意。SSE/后台运行、完整语义/对抗验收、访客防滥用、保留/删除、集群熔断、TLS/备份恢复与容量仍待完成，没有 100 RPS 声明。

本地复现：按 backend/README.md 启动已迁移的 8001 API，根 `npm run dev` 后打开 5173，使用上海模拟门店输入公开问题，再执行 backend 目录 `python -m scripts.customer_smoke`。下一批实现对话内预约草稿、核验与明确确认，随后门店处理。实际云部署等待服务器/域名，无需再次提供已有模型 Key。

## 2026-10-11 M3 第二批：对话内持久预约申请

执行前已说明目标、后端/前端/测试/文档范围与验收：预约意愿触发结构化草稿，核验联系方式，客户明确确认后写入持久待门店确认申请；未知结果、越权、旧草稿和缺确认拒绝。按已有授权仅本地模拟业务与固定合成数据验收，没有真实短信发送、机构账号访问、提交/推送或云部署。本节更新首批预约尚未实现的历史状态。

实际文件：新增 backend/app/booking.py、booking_models.py、sms_gateway.py；migrations/007_appointment_requests.sql 和 008_booking_event_scope.sql；tests/test_booking.py、test_sms_gateway.py；scripts/booking_smoke.py、configure_booking_dev.py。修改 api.py、config.py、requirements.in/lock、.env.example、tests/conftest.py 和 test_foundation.py。新增 frontend/customer/src/services/booking.ts、booking.test.ts、components/BookingPanel.vue；修改 api.ts、ConsultationPanel.vue、App.vue、style.css。同步根/前后端 README、PROJECT_SPEC 及架构、Agent、接口、设计、待确认、验收和本记录。没有改写已应用迁移或覆盖用户 LLM 密钥，开发密钥及模拟配置仅追加到忽略的 backend/.env。

实现与边界：

- 007/008 已实际迁移，启动门槛为 008。业务记录通过完整 tenant/store/visitor/thread 范围与复合外键隔离，身份/门店锁及会话锁防止撤权和并发写入穿透。前端引用不是权限；平台管理员/员工访问客户数据未扩权。
- 最新有效预约意愿运行触发草稿；医疗/拒绝/后续其他消息使旧动作失效。草稿绑定门店、主体、触发 run、有效公开预约政策和可选项目版本；当前政策或项目撤回/替换不能继续确认。30 分钟草稿、未来 15 分钟至 90 天期望时间，已有提交不能再次使用同触发运行。
- Fernet 加密完整业务快照，电话/code/内容/请求用 HMAC。称呼、电话和业务记录只在受控本地业务路径，不写模型输入、消息、checkpoint、trace、幂等结果或审计正文。显示掩码，不在浏览器存储保存手机号。
- 发送前事务持久 unknown 核验记录、客户短信同意及请求证据，再通过 SmsGateway Protocol 出站；一次调用，未知结果原键核实，禁止换键盲重发。六位随机码五分钟、最多五次错误，错误次数返回错误也提交；绑定草稿/手机号的有效凭证十五分钟一次消费。手机号或访客每十五分钟三次、最短六十秒，未知发送阻断新请求；全面防滥用仍待工程。
- 客户独立勾选确认，确切文本“确认提交预约申请，等待门店确认”、哈希及核验引用匹配；服务重新核验意愿、权限、有效证据和模拟许可。同事务提交确认时间/方式/请求证据、申请、事件/outbox、持久幂等与审计。未知提交先读权威状态，同键异内容拒绝，并发确认只有一个申请；审计故障全部回滚。
- Vue 对话内草稿、政策审阅、核验、确认、编辑/撤销草稿和当前申请记录已接真实 API。请求体不可变，未知结果保留原键；状态查询可按原 request_key 核实已提交结果。作用域变化清理业务表单，旧异步响应不能回填；鉴权或刷新失败隐藏旧业务状态。历史意愿标明消息发出时状态，当前申请独立显示待门店确认。
- Aliyun SMS 使用官方 SendSms 固定 HTTPS、ACS3-HMAC-SHA256 签名，只有手机/验证码/模板/签名/随机引用出站；来源见 backend/README.md 官方链接。真实供应商凭据未提供，本批只有官方签名向量及 MockTransport 成功/拒绝/超时/畸形返回协议验收，没有实际发送/计费。生产模拟或关闭短信启动失败，不将关闭主功能的配置宣称可上线。

实测命令与结果：

- backend `..\.venv\Scripts\python.exe -X utf8 -m scripts.verify -s`：**138 passed，378.80s**，词项降级 held-out recall@5=27/31。实际隔离 PostgreSQL/Neo4j/Milvus；测试供应商为 MockTransport，不能视为真实 Qwen/SMS 成功。新增 16 项预约集成与 12 项短信/配置测试；覆盖三次缺确认/篡改、持久错码锁定、验证码/凭证/草稿过期、手机号变更、新草稿、最新医疗/拒绝、政策/项目撤回、越权/CSRF/退出、审计整体回滚、并发及持久重放。
- Ruff check/format --check（57 文件）、mypy app（26 文件）、pip check 通过。新 cryptography 47.0.0/cffi 2.1.1/pycparser 3.11 通过现有配置的 PyPI 镜像安装并写入锁文件；未将镜像称为官方供应商来源，Linux/供应链复核仍待执行。
- 根 `npm test`：**客户 25 passed、后台 12 passed（共 37）**；根两端构建经修复客户测试 fixture 类型后分别通过，最终 customer `npm run build --workspace @ma/customer` TypeScript/Vite 再次通过。首次 Node 18 测试 WebCrypto 不可用，加入测试专用 randomUUID stub；生产仍使用浏览器 WebCrypto，不注入固定标识。默认沙箱 Node EPERM 后用正常批准的本地命令验证。
- `scripts.booking_smoke` 经 5173 同源代理验证固定合成草稿/确认原键重放、刷新读取、跨门店拒绝和退出拒绝；模拟供应商检查在发码前执行。脚本输出仅状态元数据，不输出密钥或完整联系方式。configure_booking_dev 显式模拟参数、保留既有密钥且拒绝覆盖真实 provider，本地配置已按相同规则启用。
- 实际受控浏览器定位器完成“预约咨询”→合成草稿→独立短信同意→模拟核验→申请确认→待门店确认，并刷新读取同一 UUID 申请。没有真实短信、预约时段或已接通人工承诺。390×844 手机内容宽 376/376，无水平溢出；截图 runtime/m3-booking-desktop.png 和 m3-booking-mobile.png 已保存，交付前视口复位。没有新增独立 Playwright 套件。
- configure_booking_dev 最终按显式模拟参数执行通过，现有凭据保留且没有输出；pipeline_status 只读复核：239 published/ready 向量及 Neo4j 版本、25 医学 draft，另有一条历史 withdrawn，知识 outbox 空。预约 outbox 待 M4 处理，不与知识 outbox 混淆。
- 8001 API 已重启加载 008 和本批业务代码，客户 5173/后台 5175 保留；旧 5174 服务未动。.env/runtime 被忽略，源码尚未提交，未上传密钥。

已知限制与下一批：本地模拟申请闭环已完成，不等于真实机构生产上线。门店处理/时间确认/改约/取消/到店、员工业务权限、booking_outbox 通知处理器尚未实现，M4 接入。真实短信账号/签名/模板、真实机构政策/供给/资质及医学批准仍须实际核验，模拟记录不可替代。手机号核验不等于注册客户，不做跨设备/手机号字符串自动合并；长期记忆、保留/删除、加密密钥备份/轮换和恢复演练未验。SSE/完整追踪、跨实例预算与熔断、全链路对抗和容量工程仍待补齐，未宣称 100 RPS。

本地复现见 backend/README.md：安装更新依赖，在 backend 执行 `python -m scripts.configure_booking_dev --enable-simulated`、`python -m app.migrate`，重启 API8001 与客户5173；咨询中表达预约意愿，完成模拟核验及明确确认。可执行 `python -X utf8 -m scripts.booking_smoke`，该脚本拒绝真实短信配置。下一批仅 M4 授权门店收件、时间确认及客户状态；云部署仍等待服务器/域名。

## 2026-10-11 M4 首批：授权门店收件、确认与婉拒

用户要求下一步并在执行中明确继续完成工作。执行前已说明本批目标、后端权限/预约结构及后台页面影响、门店隔离/审计/重复操作/客户刷新验收；阅读规范/架构/待确认、检查 Git 和项目指令。范围为最小门店处理闭环，确认仅客户已确认的原期望时间；不假设排班，不让员工自行改时。没有提交/推送、云部署、真实短信或机构账号操作。

实际文件：新增 backend/migrations/009_store_booking_operations.sql、app/staff_booking.py、tests/test_staff_booking.py；修改 api.py、booking.py、services.py、seed.py、tests/test_foundation.py。新增 frontend/admin/src/services/appointments.ts、appointments.test.ts、components/LiveAppointments.vue；修改 views/AppointmentsPage.vue、DashboardPage.vue、SettingsPage.vue、services/api.ts、types.ts、layouts/AdminLayout.vue；客户 services/booking.ts 与 BookingPanel.vue 增加当前确认时间/婉拒原因。同步根/后端/前端 README、PROJECT_SPEC、architecture、agent-design、data-contracts、frontend-design、open-questions、acceptance 和本记录。依赖不变；新增迁移，未改写已应用 001–008，未覆盖用户源码/密钥。

实现：009 扩展独立 appointment_read/manage/contact 门店 grants、申请 version/confirmed_at/decision_reason/updated_at、事件 version/request_id/reason 及员工持久幂等记录。confirmed_at 表示确认的到店时间，事件 occurred_at 为员工操作时间。模拟种子只新增 demo-operator 上海三项预约权限；既有作者/审核员/平台管理员不扩权，杭州无权限；重复种子不重置密码、不恢复被撤回 grant。原知识目录以任意门店 grant 读取的逻辑已收紧为明确 knowledge_*，避免新增预约权限导致知识数据泄露。

StaffBookingService 依赖 Repository Protocol。Bearer 身份验证后，服务重新锁定会话、员工/租户、门店及精确权限；完整作用域查询和复合外键约束，跨访客 Cookie 不可冒充员工。列表/详情掩码号码，独立 contact 权限查看完整号码且先审计，前端仅临时内存，关闭/换身份/门店或一分钟后清除。任何联系人信息均不进入模型/Agent checkpoint/trace/审计正文。

后台使用 PostgreSQL 分页队列、状态筛选、全门店聚合数量和独立详情/客户确认/事件历史。真实登录不回退 demo；旧界面演练仍显著隔离。确认需 accepted、availability_checked、expected_version 与原 request_key，只确认加密客户快照原期望时间，未来有效性及当前政策/项目再次复核；婉拒必须选择有限公开原因。同事务状态/版本、事件、员工幂等和审计，异常全回滚。未知结果保留不可变原键核实，不能另键操作；重放仍检查当前授权；旧响应不回填新作用域，刷新失败隐藏旧详情/号码。客户 booking 权威状态展示确认时间/婉拒原因，不通过模型自然语言推断成功。

验证、修复与证据：

- 首轮 `scripts.verify tests/test_staff_booking.py` 为10通过/1失败，失败因等价 UTC 的 Z 和 +00:00 字符串比较；改为带时区 datetime 比较，未改动业务时间。随后 backend `..\.venv\Scripts\python.exe -X utf8 -m scripts.verify -s` 全量 **149 passed，504.79s**，held-out lexical recall@5=27/31。新增11集成场景覆盖独立权限、越店/资源/访客拒绝、撤回权限/退出、缺确认/接待核实/版本冲突、政策失效、带原因婉拒、实际客户状态、审计回滚、并发及原键重放。实际 ma_m1_test 隔离 PostgreSQL 与既有 Milvus/Neo4j，不调用真实短信；模型测试 MockTransport 不视为供应商成功。
- Ruff check/format --check（59文件）、mypy app（27文件）、pip check 通过。API 启动门槛为009，实际主库 app.migrate 成功；app.seed 返回 already_seeded 并补独立接待账号，原知识、业务和密码保留。
- 根 `npm test` **客户25 passed + 后台18 passed = 43**。后台新增6项测试覆盖明确确认/接待核实、不可变原键未知结果恢复、换门店晚响应拒绝、关闭详情后联系响应拒绝、刷新失败清理/当前版本及权限撤回。初次双前端构建客户通过、后台新增 Permission 映射缺失报 TypeScript 错误，补 SettingsPage 权限名称后 admin TypeScript/Vite 通过；最终两端构建均成功。默认 Node 沙箱 EPERM 使用正常批准本地命令验证，未将失败当成功。
- 实际受控浏览器从5175登录 demo-operator，看到此前客户持久申请，不使用演练按钮。未勾选时确认禁用；核实并明确确认后申请 f644585b-8fa8-44a1-8641-2e06d9e1ae01 状态 confirmed/版本2、时间2026-10-13 14:00（上海），新增事件。客户5173刷新同编号立即看到门店确认时间。另一条固定合成申请以 no_availability 婉拒，版本2、原因和事件可见。没有实际机构接待安排或外部通知承诺。
- 手机390×844登录/工作台/队列/详情验证，当前统计待确认0/已确认1，详情实测内容宽391/391无水平溢出（浏览器像素取整）；表格通过内部横向滚动容器。首次视口对后台非活动标签未生效，发现截图仍为桌面后在活动标签重新验收并覆盖手机证据；不把最初截图当手机通过。临时手机员工会话退出，客户页恢复，视口复位。截图 runtime/m4-store-confirm-desktop.png、m4-store-decline-desktop.png、m4-store-confirm-mobile.png、m4-customer-confirm-desktop.png 保存；没有独立 Playwright 套件。
- API8001重启加载009和本批代码，客户5173、后台5175可体验；旧5174未动。Git仍为未提交源码，.env/runtime忽略，无真实密码/密钥提交。

剩余与下一批：本批完成本地模拟的门店接收/确认/婉拒和客户状态闭环；M4后续补改约客户再确认、客户取消及到店登记，随后M5档案/意向变化。booking_outbox 通知处理器、CRM、排班资源/容量和真实短信尚未接入，直接权威队列可见不等于通知已送达。真实机构政策、供给、医生/资质和医学批准仍需实际核验；模拟确认不可当实际可约承诺。注册/跨设备关联/长期记忆、保留删除、密钥备份/轮换、SSE/完整追踪、集群熔断/预算、运维与容量仍待验，没有100RPS或完整生产上线声明。

本地复现：按 backend/README.md 迁移009、运行模拟种子并重启API8001，根 npm run dev 与 npm run dev:admin。客户5173提交模拟预约，后台5175用 demo-operator 和忽略的 runtime/m1-seed-password.txt 本地种子密码登录，预约页核实后确认原时间或选择原因婉拒，再回客户刷新预约状态。完整回归用 backend `python -X utf8 -m scripts.verify -s` 和根 npm test / npm run build。部署仍等待服务器/域名，已有模型Key不需重发。

## 2026-10-11 M4 第二批：改约本人确认、取消与到店

目标与验收：补齐门店确认后的预约生命周期。门店提出新时间，客户明确接受或拒绝；客户可取消待确认/已确认申请；员工核实身份及实际到店后登记。原申请、确认与意向保留，每次操作有范围授权、版本、持久幂等和审计。不扩大模型出口、员工授权或真实机构资质。

实际文件：新增 backend/migrations/010_booking_lifecycle.sql、app/booking_projection.py、app/booking_lifecycle.py、tests/test_booking_lifecycle.py；修改 app/api.py、booking.py、staff_booking.py、tests/test_foundation.py。新增 frontend/customer/src/components/AppointmentActions.vue；修改客户 services/booking.ts、api.ts、booking.test.ts、components/BookingPanel.vue 及后台 services/appointments.ts、appointments.test.ts、api.ts、components/LiveAppointments.vue。同步 README、PROJECT_SPEC、backend/README、frontend/README 及 architecture、data-contracts、agent-design、frontend-design、open-questions、acceptance 与本记录。依赖未增加，001–009 已应用迁移未改写，用户模型配置/密码未覆盖。

实现：010 增加 arrived_at、门店改约提案和独立 booking_action_confirmation。改约仅待确认/已确认可发起，员工需精确 read/manage、核实接待、明确操作；原状态/时间保留。提案有效30分钟、新提案替代旧提案，客户接受需当前版本/提案摘要/有效期、明确按钮文案、当前有效政策/项目及提案员工仍有效授权。拒绝保留原安排，取消使活动提案失效；到店需已确认、无有效待回应提案以及身份/实际到店核实和明确登记。取消允许失效政策下结束申请，不引入付款/合同规则。

BookingLifecycle 通过 Repository Protocol 使用固定 SQL，API 不直连外部系统；每次重新核验认证、门店/线程/资源范围，事务锁与 expected_version 防止丢失更新，持久幂等请求摘要阻断同键异内容。重放重新鉴权并返回当前状态，不回退后续动作。加密确认快照/文案/方法/服务端时间/证据请求ID、预约版本/状态、事件、幂等和审计原子提交；审计失败全部回滚。业务姓名/号码/操作快照不进入模型与 trace。原 appointment_confirmation 保留不变。

两端 Vue 页面已接实际API。客户在原对话预约记录内审阅提案并勾选接受/拒绝，独立展开取消确认；状态版本变化重置勾选。后台展示提案/期限、已确认时间、到店登记和处理历史，列表增加取消/到店筛选，优先显示已确认时间而非旧期望时间。新时间输入变化取消旧核实勾选。未知写入保留原请求键、版本、提案/摘要和内容，仅重试原请求；切换门店/身份/线程及权限撤回清空缓存，旧异步响应不能恢复业务内容。

实际验证：

- `python -X utf8 -m scripts.verify tests/test_booking_lifecycle.py -x` 首次11通过/1失败（访客隔离测试准备误带旧 Cookie，服务端正确拒绝缺CSRF的身份替换）；修正测试先清Cookie。最终14 passed（136.01s），覆盖接受/拒绝、原时间保留、重复重放/同键异文、过期/替换/摘要/政策/人员权限/确认失效、取消两种状态、CSRF/自有线程/另一访客/另一门店/平台角色拒绝、到店核实、审计回滚及取消与接受并发仅一次变更。
- `python -X utf8 -m scripts.verify -s`：完整163 passed（665.35s），隔离 ma_m1_test 实际迁移、知识/Agent/权限/短信/预约回归；本批没有真实供应商或模型调用测试。
- Ruff check . 通过；format --check app scripts tests：61文件；mypy app：29文件通过；pip check 无冲突。早期从仓库根调用 mypy 未读取后端配置出现既有 Settings 参数诊断，最终在 backend 按配置运行通过。
- 根 `npm test`：客户29、后台21，共50 passed；新增客户4/后台3项生命周期前端测试，包含明确动作、未知结果原快照重试和旧范围结果隔离。两端 vue-tsc/Vite 最终构建通过，详情时间展示修订后再次构建；格式化仅本批修改文件。
- `python -X utf8 -m app.migrate`：本地业务库010应用成功；API8001重启加载，既有记录保留。没有重新种子、重置密码或扩大权限，旧5174未动。客户5173/后台5175继续运行。
- 浏览器实际本地模拟：原申请 f644585b-8fa8-44a1-8641-2e06d9e1ae01 从原确认2026-10-13 14:00提出10-14 14:00，客户接受前时间不变，明确接受后两端改为新时间；员工明确登记到店，version5和五个事件可见。第二份5e0c6bcb-b9d6-46c7-900c-7dc9da92ad67通过自由预约意愿→草稿→模拟验证码→明确提交→客户取消，刷新恢复cancelled，后台筛选可见。所有人名/号码为合成输入，没有真实SMS/真实到店。
- 手机390×844实际客户布局无溢出（innerWidth391/scrollWidth376）；后台详情391/391，原时间、新时间、到店/改约历史可读。临时手机员工会话退出、viewport恢复，客户入口和后台验收详情保留。没有独立 Playwright 套件。截图在忽略的 runtime/m4-lifecycle-*.png，.env、种子密码和截图忽略验证通过；未提交/推送/云部署。

本地步骤：先按 backend/README 迁移010并启动API8001，根 `npm run dev` 和 `npm run dev:admin`。客户5173在对话中提出到店意愿并完成显著标识的模拟核验/确认；后台5175用既有demo-operator接待账号在预约详情提出改约，回客户刷新并明确接受/拒绝或取消；无待回应提案的确认预约可核实并登记到店。API契约见 docs/data-contracts.md，专项及全量命令见上方。

未完成与风险：真实SMS机构凭据/签名/模板及实发送、实际预约政策/接待容量/排班、CRM与通知Worker、人工接待工作流、到店客户档案与意向变更、注册/同意后长期记忆、保留/删除/密钥轮换、医学/注册真实核验、外部观测、TLS/备份恢复/容量/云部署仍未验收；本地模拟不是完整可上线批准，不承诺100RPS。改约30分钟为本地工程默认，不代表机构正式规则；提前模拟到店只演练手动核实记录，不伪造真实客户已到店。

下一里程碑 M5：门店范围内到店咨询档案、原始/新增/最终意向及来源历史、客户明确最终确认、审计和幂等；不凭手机号自动合并既有客户。云端仍等待服务器/域名，模型Key不需用户重新提供。

## 2026-10-11 至 2026-10-12 M5首批：到店咨询档案、意向版本与本人确认

用户要求进入下一阶段。执行前说明本批目标/影响文件/验收：仅已到店预约建档，保留原意向，顾问追加后续意向、客户本人明确确认或拒绝，历史/来源可追溯；越店/旧版本/重复操作拒绝。阅读 PROJECT_SPEC/architecture/open-questions，检查 Git 和适用指令；未调用子代理。本批完成M5首批，回访另批实施，不宣称完整M5或生产上线。

实际文件：新增 backend/migrations/011_consultation_cases.sql、app/consultation_cases.py、tests/test_consultation_cases.py，修改 api.py/seed.py/test_foundation.py。新增两端 services/cases.ts 和 cases.test.ts，客户 components/CaseReviewPanel.vue，后台 components/LiveCases.vue；接入 BookingPanel/BookingApi/ApiClient、CustomersPage、DashboardPage、SettingsPage、Permission及安全错误消息。后台仅类型引用客户DTO，构建移除，不共享客户运行凭据。更新根/后端/前端README、PROJECT_SPEC、architecture、data-contracts、frontend-design、open-questions、acceptance和本记录。依赖不变，001–010迁移不改写，.env用户模型配置/密钥未覆盖。

实现：011完整范围的档案/意向版本/客户处理/独立持久幂等；每预约一份档案，来源已到店，原加密客户申请保留。同手机号不同访客不自动合并，不建立注册客户或长期记忆。员工精确customer_read/manage，创建另需appointment_read；新增模拟上海demo-consultant仅这三项权限，无知识、完整号码、预约处理或杭州权限。既有接待/作者/审核员/平台管理员不扩权，重复seed不重置密码/撤销grants。

ConsultationCases依赖Repository Protocol，API为固定明确业务动作，未暴露Agent工具。顾问追加加密快照和版本，变更说明为客户可见；客户Cookie/CSRF/自有访客线程/预约每次重验。确认/拒绝绑定当前未回应版本、HMAC和固定文案，保存时间/方式/证据请求；接受重验有效公开目录及记录顾问当前权限，拒绝不要求撤回项目恢复。顾问修改产生新的未回应版本，历史确认不继承。认证/门店及档案→预约统一锁顺序，advisory/请求键防并发重复，审计故障整体回滚；重放鉴权后返回最新档案，不确认新版本。业务快照本地Fernet加密，只返回掩码号码，未加入Qwen/embedding/checkpoint/外发trace。

前端真实登录不回退演练；后台到店预约建档、分页队列、目录选项、详情和版本历史，工作台档案数来自授权API；未授权显示未知/原因，不能用0冒充无客户。客户在已到店申请下审阅/确认或继续沟通；版本变化清除勾选，业务未知结果保留不可变原请求/键，换门店/访客丢弃迟到响应，已知失效隐藏旧详情。确认咨询意向不代表治疗、医学判断、收费或合同同意。

实际验证：

- 主库 `..\.venv\Scripts\python.exe -X utf8 -m app.migrate` 成功应用011；`-m app.seed` 返回already_seeded并补模拟顾问，原资料/密码保留。API8001重启，启动门槛011；旧5174不动，客户5173/后台5175保留。
- 专项 `-m scripts.verify tests/test_consultation_cases.py` **13 passed，138.89s**；完整 backend `..\.venv\Scripts\python.exe -X utf8 -m scripts.verify -s` **176 passed，756.23s**，held-out lexical recall@5=27/31。真实隔离ma_m1_test PostgreSQL及既有Milvus/Neo4j；MockTransport不当真实供应商成功。本批无新Qwen调用、真实SMS或外部CRM写入。
- 新13项覆盖原意向/历史保留、确认/拒绝后再修改、旧确认原键重放不确认新版、当前版本/摘要/勾选/文案校验、项目撤回/顾问授权撤回、CSRF/越门店/其他访客线程/接待作者平台管理员拒绝、只读grants、非到店拒绝及无档案null、审计回滚、同键并发修改只有一次追加、修改与确认竞争新版不被旧确认、同手机号不同访客独立且互相拒绝。调整一致锁顺序后完成并发专项与完整回归；没有重置业务库。
- backend Ruff check / format --check **63文件**、mypy app **30文件**、pip check 通过。根 `npm test` **客户33 + 后台25 = 58 passed**；新增8项意向状态/不可变重试/明确审阅/旧响应与权限测试。最终根 `npm run build` 双端TypeScript/Vite通过；客户主JS135.78kB/gzip48.81kB，后台主JS124.10kB/gzip48.37kB，路由分包。Node沙箱EPERM经正常批准本地命令验证，不当代码成功跳过检查。
- 受控浏览器实际用demo-consultant建立来源预约 f644585b-8fa8-44a1-8641-2e06d9e1ae01 的合成档案。版本1原“不确定项目，先咨询”；版本2补水意向→客户选择继续沟通；版本3了解沟通流程→客户本人确认；版本4再明确了解咨询/具体服务待专业沟通→重新待确认→客户本人确认。后台刷新看到版本2拒绝、版本3/4确认及服务端时间，原称呼/意向保留。客户刷新重新读取同一档案和版本4确认，无重新模型生成或业务重复写入；后台控制台错误/警告检查为空。
- 390×844手机实际客户审阅/确认与后台登录、菜单、工作台真实档案数1、档案抽屉/历史均通过。客户innerWidth391/scrollWidth376；后台innerWidth391/scrollWidth391，抽屉约390.68，无页面水平溢出。临时手机顾问会话退出，viewport恢复默认，客户和后台结果保留。没有独立Playwright测试套件，使用受控浏览器定位器交互。截图在忽略runtime/m5-admin-new-version.png、m5-admin-confirmed.png、m5-admin-mobile.png、m5-customer-mobile.png；未将初始合成登记当实际客户到店。
- `git check-ignore backend/.env runtime/m1-seed-password.txt runtime/m5-admin-confirmed.png` 成功；源码仍未提交，无密钥、截图提交/推送，无云部署。

本地复现：按backend/README迁移011/seed并重启API8001，两端Vite5173/5175。demo-operator核实并登记模拟到店；demo-consultant登录“客户跟进”从该预约建档，补咨询方向/项目/公开变更说明并明确追加；客户在原对话刷新、审阅当前版本并确认或继续沟通，再回后台刷新历史。客户需保持原访客Cookie，不能凭手机号找回他人档案。服务命令、权限与接口详见backend/README、frontend/README和data-contracts。

剩余及下一里程碑（首批历史）：M5回访任务/跟进记录当时待实现，第二批更新见下节。CRM、通知Worker、真实SMS/机构政策/排班、人工工单处理、注册/身份找回/同意后长期记忆、资料保留删除/密钥备份轮换、真实医学资质注册与审核、外部观测、TLS/备份恢复/容量和云部署未验收。咨询确认不是治疗同意/合同，模拟档案不能当真实注册/医学批准。服务器/域名未提供前不部署，不宣称100RPS或可直接真实医疗上线。

## 2026-10-12 M5第二批：站内回访计划、本人反馈与门店内部跟进

用户要求继续下一步。执行前说明本批目标、后端/双前端/测试/文档影响和验收：已确认到店意向提出站内回访、本人逐次同意/拒绝/反馈/取消、暂停/恢复与内部记录，跨门店/访客/旧版本/重复操作拒绝。已阅读产品规范/架构/待确认、检查Git及适用指令；没有子代理、提交/推送、云部署、短信/电话/CRM或新的模型调用。

实际文件：新增 backend/migrations/012_followups.sql、app/followups.py、tests/test_followups.py；修改api.py启动门槛与7个接口、test_foundation.py迁移计数。新增两端services/followups.ts及followups.test.ts、customer/components/FollowupPanel.vue、admin/views/FollowupsPage.vue；接入BookingPanel/BookingApi/ApiClient、后台路由/Sidebar与安全错误描述。后台仅type import客户DTO，不共用客户运行凭据。同步根/前后端README、PROJECT_SPEC及architecture/data-contracts/frontend-design/open-questions/acceptance和本记录。依赖不变、001–011不改写，012应用后也未改写；未覆盖.env密钥、模型配置、种子密码或grants。

实现与边界：

- PostgreSQL完整租户/门店/访客/档案/来源版本外键、任务/不可变事件/持久命令；计划与操作快照Fernet加密/HMAC，方式staff_button/customer_button、服务端时间及请求证据保留。有效员工精确customer_read/manage，原访客Cookie/CSRF与自有线程/预约；平台管理员不默认访问。新键状态/事件/命令/审计原子写入，重放重新授权返回当前状态。相同档案统一加锁顺序，接受/取消竞争只有一次变更。
- 仅当前本人已确认意向可提未来90天内计划，awaiting_confirmation不等于已同意。接受再次检查来源/有效项目/创建顾问权限及计划尚未过期；过时可拒绝。客户接受后scheduled，可提前反馈，completed只表示反馈保存。拒绝/取消暂停整个档案新邀请；仅本人resume清除暂停，旧终态不复活、新计划仍需同意。员工只能追加内部note或取消未终结计划，不能代客户确认/恢复/宣布已人工回复。
- 内部note事件与员工取消备注在服务端从客户视图排除；后台只显示掩码号码。业务正文不进入模型、embedding、checkpoint或审计明文，无外部通知出口。已接受计划保存旧来源，意向更新不改写它；反馈/取消继续可用。逾期或来源改变的待同意计划需取消重提，不自行改变已审阅说明或时间。
- 队列/候选真实分页默认25最大100、独立状态计数，客户每预约最近20项；同档案仅一个未终结计划，最多200任务/单任务200版本。是本地工程限制，正式时限/归档策略待确认。Vue内容变化/版本更新清除勾选，未知结果保留不可变原键/正文，不能替换成新备注/取消；换身份/门店丢弃旧响应。已知错误保留原因、清除旧队列/详情与未核实计数。

实际验证与修正：

- 主库 `..\.venv\Scripts\python.exe -X utf8 -m app.migrate` 应用012成功，无需seed；验证旧8001进程命令后仅重启该uvicorn，当前启动门槛012；客户5173/后台5175保留，旧5174不动。
- 专项 `..\.venv\Scripts\python.exe -X utf8 -m scripts.verify tests/test_followups.py` **15 passed，128.71s**。首次沙箱数据库网络受限导致15 errors，获准本地命令后14 passed/1 failed；失败是另一访客测试未清旧Cookie而缺当前CSRF，修正fixture清Cookie创建独立访客后15项全通过，没有放宽CSRF。测试只重置ma_m1_test，不清业务库。
- 完整 `..\.venv\Scripts\python.exe -X utf8 -m scripts.verify -s` **191 passed，790.16s**，held-out lexical recall@5=27/31；隔离PostgreSQL与既有真实Milvus/Neo4j测试集合，供应商MockTransport不描述为实际外部成功。本批没有真实Qwen调用或SMS实发送。
- backend Ruff check / format --check **65文件**、mypy app **31文件**、pip check通过；初始格式/SQL长行已修复后验证。最终frontend目录 `npm test` **客户37 + 后台29 = 66 passed**；`npm run build` 双端vue-tsc/Vite通过。客户主JS143.82kB/gzip50.65，后台主JS124.95kB/gzip48.64，回访路由13.95kB/gzip5.36。最终构建/单元在错误展示修正后重新执行，Node子进程沙箱限制通过获准本地命令验证。
- 受控浏览器真实本地合成档案504626e9-d270-4283-a5de-b9742a00b917/意向4，来源预约f644585b-8fa8-44a1-8641-2e06d9e1ae01。顾问提出10-13 10:00计划，客户拒绝后新邀请409阻断，客户本人恢复；10-13 11:00新计划同意后追加私有记录，客户提交need_help“想继续了解到店沟通需要准备哪些资料。”，后台completed/版本4及实际历史可见。客户展开历史DOM确认内部备注不存在、本人反馈可见。
- 手机390×844提出10-14 10:00计划，客户本人同意后取消，终态cancelled/版本3、opted_out=true，刷新恢复且保持暂停。后台手机真实顾问登录/导航/筛选/完成反馈详情实测宽391/391、抽屉390.68（取整），客户宽391/scrollWidth376无页面溢出；表格内部滚动。截图 runtime/m5-followup-admin.png、m5-followup-admin-mobile.png、m5-followup-customer-mobile.png 已保存并查看。临时手机员工会话退出、viewport恢复，原访客对话及两端标签保留。受控Playwright定位器浏览器验收，不当独立Playwright套件。
- Git仍main、源码未跟踪，没有提交/推送；check-ignore确认backend/.env、runtime种子密码和截图均忽略。演练保留模拟标识，沒有真实机构接待、真实客户或医学批准声明。
- 收尾检查13份文档相对链接无失效；GET /health/ready返回ready，scope=api-database（历史milestone字段仍为M2-knowledge，不把此接口当完整业务或供应商健康检查）；后台浏览器error/warn为空，原客户对话刷新可见已取消/暂停和已保存反馈。

本地复现：见backend/README M5第二批；迁移012重启API8001及双前端，使用既有上海顾问在5175/#/followups提出当前已确认档案的未来计划，原访客在5173原对话刷新后处理；反馈后后台刷新详情，内部记录客户不可见。拒绝/取消后重提会拒绝，需本人恢复再提出新计划。原Cookie丢失不能凭手机号/thread_id找回资料。

下一里程碑M6：先补本地运维与恢复验收。未完成实际SMS/机构政策/供给/接待容量、外部通知Worker/CRM、人工工单接待、注册/身份找回/同意后长期记忆、自助保留删除/密钥备份轮换、真实资质/注册与医学审核、外部追踪、生产TLS/备份恢复/容量及云部署。站内可见不等于通知送达，反馈保存不等于已人工处理；不能用本地模拟替代真实核验或宣称完整可上线/100RPS。云端等待服务器/域名，已有模型Key无需重给。

## 2026-10-12 演示资料包：虚构机构设定与供应商流程讲解

用户明确要求“帮我编一些像真实的数据”，用于向他人演示。执行前说明目标/影响范围/验收：一致的两城机构、团队排班、服务示例价、接待规则、供应商演练及后台只读展示；模拟标识与实际未核验保留，不自动进入Agent知识库。读取产品规范/架构/待确认，检查Git；无子代理。本批是独立演示资料里程碑，不将M6运维/恢复标为完成。

实际文件：新增backend/data/demo_materials.json、app/demo_materials.py、tests/test_demo_materials.py；修改api.py增加只读GET；新增frontend/admin/src/services/demo-materials.ts/test、views/DemoMaterialsPage.vue，修改router/AdminLayout导航及api安全错误描述。新增docs/demo-materials.md完整资料与5分钟讲解方法；同步根/前后端README、PROJECT_SPEC、architecture/data-contracts/open-questions/acceptance及本记录。没有新迁移/seed、授权或依赖修改，.env/模型Key/种子密码/旧业务与知识未改。

数据：晴园美学运营中心为虚构机构，两家体验店（上海420m²/6室、杭州360m²/5室），共10岗位/24服务（每店8美容护理+4医美了解咨询）、12接待规则、4虚构协同供应商/4模拟独立复核、6组接待表达、8条讲解路径。杭州晚班与19:30营业结束统一。所有人员/地址/报价/供应商是设定，机构/执业/注册证号为null；医美类只有免费了解咨询，没有治疗报价/操作。资料演示期2026-10-12至11-12，不表示真实供给有效期；复核demo_result“模拟通过”，actual_result“未验收”，SIM-WALKTHROUGH只为讲解编号，不是假实际凭证/测试回执。讲解化名不是新增客户记录，实际业务演示仍经原确认/权限/幂等流程。

工程边界：API→DemoMaterials应用服务→Repository Protocol，复用员工活跃会话/租户/精确customer_read门店检查后只返回public_code对应店；独立读取审计，失败不给资料。显式非生产模拟环境、活动模拟门店才开放；平台管理员/知识员工/接待/访客默认不读取，上海顾问没有杭州授权。前端切换身份/门店清空旧数据、丢弃晚响应，失权后不能导出旧资料。JSON导出为当前门店DTO，完整两城开发JSON只是虚构源文件。不加入客户业务、知识审核/发布、Milvus/Neo4j、模型或故障模拟器，不发送供应商请求/短信/CRM。

实际验证：

- `..\.venv\Scripts\python.exe -X utf8 -m scripts.verify tests/test_demo_materials.py tests/test_foundation.py` **30 passed，48.73s**（新增4+基础26）。初次29 passed/1 failed是测试错用demo-admin而实际为demo-platform-admin；审计表引用也纠正为audit，重跑全部30项通过，没有扩大平台管理员授权或放宽审计。专用ma_m1_test，业务库未重置。此前M5全量191为历史，未将本次局部回归称为全量195。
- Ruff check与format --check **67文件**、mypy app **32文件**通过；前端 `npm test` **客户37 + 后台31 = 68 passed**，双端vue-tsc/Vite构建通过。后台新增路由JS8.59kB/gzip3.53、CSS1.87kB/gzip0.58，主JS125.32kB/gzip48.75；客户产物不变。首次CIM/本地数据库沙箱限制经获准本地命令验证，没有自动审核拒绝。
- 核实37340是本项目uvicorn app.main:app/127.0.0.1:8001后仅重启该进程，新API30500启动成功（session36045），迁移门槛保持012；不动5174。真实本地demo-consultant登录5175“演示资料”，上海5岗位/12服务/4协同流程、示例¥298补水/¥258清洁和医美只了解入口均可见。
- 浏览器实际点击下载JSON得到 `C:/Users/86152/Downloads/SIM-DEMO-20261012-demo-shanghai.json`，读取验证simulated=true、5人员/12服务、没有demo-hangzhou。下载工具等待较长后返回成功路径，不作为导出性能验收；无对外上传。供应商展开显示模拟通过与实际未验收、不同虚构编制/复核人员及正式所需清单。
- 手机390×844实际报价/供应商详情宽391、scrollWidth376，12张服务卡片、折叠详情可用且无页面横向溢出；viewport已恢复，后台资料页与原客户标签保留。受控Playwright定位器验收，没有独立Playwright套件。截图runtime/demo-materials-prices.png、demo-materials-prices-mobile.png、demo-materials-supplier-mobile.png保存并检查。

本地步骤：重启API8001，两端Vite保留；demo-consultant登录5175→演示资料→门店/报价/规则/供应商/讲解五类；资料JSON及完整说明见docs/demo-materials.md。每店12服务，完整源包共24，不能把两店总数当当前店可用供给。没有实际美丽田园机构资料/医生资质/合同或供应商批准声明。下一里程碑仍M6本地备份恢复与运维，真实核验、渠道与云部署继续等待实际信息。

## 2026-10-12 真实聊天质量与上下文验收

用户要求测试美容/医美聊天是否通顺、是否有上下文。目标/范围/验收已说明，读取规范/架构/待确认并检查Git；仅固定合成问题，经客户5173同源代理→API8001→真实LangGraph/Qwen/混合检索。不导入新知识/演示报价，不改Agent业务或批准状态，没有子代理、真实客户资料、预约提交/短信/CRM/提交推送。实际新增backend/data/chat_quality_cases.json、scripts/chat_quality_check.py、docs/chat-quality-review.md；README新增链接。原始捕获和逐轮文本为忽略的runtime/chat-quality-report.json与chat-quality-transcript.md。

实测14场景50轮，组间独立访客/线程；50/50 HTTP200和原键重放一致，14/14历史条数匹配、14/14退出。模式generated31、evidence_fallback5、fixed4、handoff10；需要检索的36轮全hybrid，真实供应商调用成功与本地降级分别计数。客户端单轮中位6.15s、最大9.20s，是串行小集不是SLA/吞吐声明。五次降级追踪invalid_model_response1、answer_evidence_invalid3、answer_policy_denied1；仅按此次捕获run_id读取节点元数据，不读取其他客户。最终脚本增加GET自有run.trace和单例另存，memory_isolation再实测1轮generated/5.27s、trace非空，单独报告不计入50。

人工审阅结果：基础咨询/短距离指代、护理方向切换、拒绝邀约及重新表意、新会话边界与基本越权/个人医疗转接可用，但质量未通过。主要P1为补水明确追问降级成清洁（卡片仍补水）、第10轮把最初补水说成首次体验、专业转接后风险关联丢失；P2包括光子别名漏识别、否定治疗方案误拦截、助手流程总结答非所问、反复目录/待核验缺实质内容、业务转接原因文案不符。详见chat-quality-review.md逐场景/复现/来源分析。HTTP成功、结构化引用通过不是语义或医学正确性证明；没有全量语言通过率/临床批准声明。

实际浏览器额外2轮：新对话基础补水正常→“先介绍一下咨询流程，不给我定治疗方案”错误转专业人员，截图runtime/chat-quality-browser.png保存并查看；这些UI轮次不计入50。原线程/申请/档案未改写，仅新增测试聊天与现有waiting工单，没有客户预约业务。未改应用源码，因此本轮不重复前端构建或既有单元全量；评测脚本Ruff格式/检查通过，实际50轮及单例1轮是此次验证，不将此前后端191/前端68计为新结果。

结论与下一批：聊天质量和上下文尚不适合作为稳定演示已通过。先修主项目/降级一致、有来源公开主题记忆和本地非敏感风险状态，再修别名/否定语义/公开流程与业务动作识别、精简表达和经独立审核补知识；需要重跑完整50轮与新增确定性回归。当前缺陷仍待修复，M6运维/实际资料/供应商/云部署计划保持，不以扩展模拟资料或外发个人医疗正文绕过审核和出口。

## 2026-10-12 聊天修复：主题、上下文、路由与受控内容重试

用户明确“修正”，执行前已说明目标/文件范围/验收；读取规范/架构/待确认与原评测，检查Git。单里程碑修复，不补造医学事实，不更改知识批准/发布时间、门店/员工权限、用户.env/模型配置/密钥/种子或已应用012迁移，无子代理/提交推送/云部署/短信/CRM。

实际文件：新增app/conversation_context.py、tests/test_chat_quality_regressions.py、scripts/chat_quality_acceptance.py；修改agent_policy.py、consultation_agent.py、consultation_gateway.py、agent_repository.py及两个既有咨询/网关测试。维护原chat_quality_check.py采集、真实回归捕获和原始基线；同步PROJECT_SPEC、README相关说明、architecture/agent-design/data-contracts/chat-quality-review及本记录。前端与依赖不变；消息结构不变，intent新增recall，仍mode=fixed。

实现：PublicTopics当前明确项目优先、比较指代关联双方，证据与卡片同主题；首次/当前方向按本线程原run/client-message来源复核，旧格式最多解析500条本人允许外发且已完成的来源，临时正文不回写/不新增模型出口。公开问答仅generated/evidence_fallback无风险且来源仍有效，Gateway最多4问/3答、答1200字并外发前再验引用；医疗正文、身份和业务记录不传，风险仅本地medical_pending。否定评估不消除真实症状/孕期风险，风险关联短“那这个呢”仍转专业；光子等别名、本地跨域拒绝、收费流程/实际动作分开，业务原因模板一致。最多两段/一句总结，条件“门店确认后才是已确认预约”不误判实际执行。引用/结构失败最多再生成一次、30s总预算/来源与验证不绕过，失败草稿不保存到用户答案或checkpoint；再次失败只回有效相关来源，比较可保留两条。只记录重试元数据和异常类别/源码位置，没有异常消息或客户正文日志。

实际结果与修正过程：

- 既有咨询/网关/目录36 passed/81.89s。新增最初13项一度12 passed/1 failed，是新访客fixture没有清旧Cookie导致CSRF失效；修fixture后与网关10项共23 passed/33.10s，没有放宽CSRF。主题跨窗、新线程/伪造其他线程引用、当前项目降级、风险/否定、公开历史撤回/出口前再验均已覆盖。
- 核心完整 `-m scripts.verify -s` **210 passed/841.22s**，held-out lexical recall@5=27/31；此后补引用内容重试/跨域API提交及4个条件式校验，最终 `-m scripts.verify tests/test_chat_quality_regressions.py tests/test_consultation_agent.py tests/test_consultation_gateway.py tests/test_customer_catalog.py` **57 passed/123.99s**。旧会话兼容进一步专项 **1 passed/17.18s**；没有相加或声称最终216全量通过。仅专用ma_m1_test重置，真实业务库不重置。
- 中间并行专项56 passed/1 failed为测试投影projection_unavailable，独立同测试1 passed/7.40s，最终57独立全过。中间真实复测还出现一次503在跨域/一次在长流程，元数据仅表明节点后失败，未确定根因；新增安全错误类别/位置诊断，独立最后27轮全200、日志未再出现失败。保留原始中间捕获，不把未知故障说成已知原因已根治；依赖与并发可靠性留运维跟踪。
- 真实Qwen/Milvus/Neo4j原14组50轮多次完整复测，中间发现比较卡片缺方、条件状态误拦截及总结断言与真实前文步骤不匹配，分别修代码/补回归；最后相关6组27轮独立复测，完整50原文件chat-quality-final-50.json与补测JSON分开保留。chat_quality_acceptance --supplement显式标记supplemental_capture、按实际前文步骤检查总结，不把门店字样当唯一正确总结；原“多个问题逐项回答”仍不满足断言。16个定向回复断言全部通过，不是全语言/临床通过率。
- 更新后50个位置generated36/fallback1/fixed5/handoff8、37次hybrid，原基线31/5/4/10保留chat-quality-before-fix.json/md。一处比较先引用失败再结构失败，仍安全降级为清洁/补水两条当前有效来源和两张卡；不伪装正常模型成功。单轮合并中位6.22s/max13.66s，含重试不是容量/SLA。原手机号/身份/业务不发送，个人医疗问题本地转接，waiting不代表人工接通。

服务：各次仅按核实uvicorn命令重启8001，当前最终31192/session39051、门槛012；不动5174，5173/5175保留。Ruff全检查/格式、mypy33文件通过；前端没有源码变更，本批不重复构建。Git仍main、源码未跟踪，.env/密码/原始runtime捕获/截图忽略，不提交推送。下一批继续扩大公开知识覆盖、对抗/语义质量和M6运维/恢复；真实医学资质/批准、供应商、长期记忆与云部署仍待验，不能把模拟数据或这套小集当作生产医疗上线批准。

收尾验收：浏览器新增合成会话，实际三轮补水→“不给我定治疗方案，只介绍流程”→首次主题回忆，正常公开流程和基础补水回忆可见。截图runtime/chat-quality-fixed-browser.png已目视检查；runtime/chat-quality-transcript.md按最终带supplemental_capture报告重新生成，保留实际降级回复。临时测试标签已关闭，原客户页仍选对话1，客户/后台原标签保留，没有预约或回访业务提交。最终静态命令 `python -m ruff check app tests scripts`、`python -m ruff format --check app tests scripts`、`python -m mypy app` 均通过（71个格式文件/33个类型源文件）；acceptance/open-questions同步本批结果与未明故障边界。

## 2026-10-12 具体模拟咨询场景落地

用户要求把缺少机构资料的占位答复改成完整场景，执行前说明目标、数据/agent/前端范围与验收。新增data/demo_consultation.json 70条（14生活护理/需求沟通、16医美科普/接待、24运营问答、6医学比较、10内部策略）及demo_chat_cases.json 12组46轮、tests/test_demo_consultation.py、knowledge_scope.py、scripts/demo_chat_acceptance.py。修改config/knowledge_types/services/knowledge_import/knowledge_worker的受控模拟范围、gateway的回答风格/原文候选/逐段数字提示、agent的模拟元数据、topic的收费追问与完整名称、policy的通用风险与激光脱毛识别、授权快照/采集脚本。客户Vue咨询面板/App/项目卡片及类型集中演示标识；后台页面和权限不变。规范/架构/知识/数据/验收/待确认/README同步。没有新依赖、迁移、角色/grants、生产部署或外部业务写入。

新增MA_DEMO_MEDICAL_EDUCATION仅非生产显式模拟，标准模式仍拒绝medical；22条有日期和公开URL的medical/demo_education只能在模拟知识/审核/租户/门店、独立开发审核下发布。理由明确“模拟公开科普演练复核，不代表真实医学批准”，没有伪造注册或执业证。生产启用必须失败。原25条标准医学draft不改变。worker与evidence相同固定SQL范围，当前版本/权限/期限/摘要/投影再验仍执行；个人症状/病史/孕期与个体治疗判断不传模型。一般公开风险问题无个人标记时可科普，不把“我过敏”或“朋友做完后疼痛”删成公开问题。

本地实际导入：旧32/226条全部skipped，新70 created，medical_pending=0仅表示22条模拟科普进入模拟复核，不能说真正医学批准。70个outbox全部published，经真实Qwen256维向量/Milvus/Neo4j，未发现重试事件。后续统一虚构上海团队与既有运营演示包姓名/岗位，1 created/69 skipped并完成投影；不修改账号或客户记录。当前文件资料334条，精确授权快照467摘要（含历史已授权摘要），仅更新被忽略backend.env的MA_MODEL_EXPORT_HASHES和本地演示开关；模型名称/URL/API key和业务密钥原样保留。数据版本变化不会改写历史或复活撤回，新演示用新会话，旧引用仍失效。

验证过程：初次受限沙箱本地数据库连接Permission denied、Node realpath EPERM，按已有本地授权运行网络/Node命令后解决，没有自动审批拒绝。首个新测试要求source必须字面出现“真实”，但合法来源已有“非美丽田园实际供给”与“虚构/模拟”，修为验证这两个披露词；首批81 passed/1失败来自旧断言。随后完整后端 `python -u -X utf8 -m scripts.verify --maxfail=2` 225 passed/961.20s。运行中最后增加原文候选测试及脱毛首问/更具体别名，最终 `scripts.verify tests/test_demo_consultation.py tests/test_consultation_gateway.py --maxfail=2` 20 passed/20.23s；前一次专项19 passed/1失败是同时统一一条数据姓名导致同文件摘要变了、skipped69而非70，资料固定后独立重跑通过，未放宽幂等断言。不将225/20相加或称最终226全套。Ruff74文件全检查/格式、mypy34源文件通过。前端37客户/31后台共68 passed；客户vue-tsc与Vite构建通过（1580模块），没有改后台源码所以不重复后台构建。

真实模型先测试46轮，发现两次原文引用失败、手部数字失败降级及脱毛首问遗漏。增加精确quote_candidates、不计算跨证据金额/时长提示及脱毛关键词后，最后独立重跑全部46轮：HTTP200/原键重放/12访客本人历史与退出一致；39generated/1evidence_fallback/2fixed/4handoff，中位6.39s/max7.89s。19个定向检查均通过：步骤、单次价、关联收费、预算、技术区别、正确项目卡、十轮首次话题、风险本地、预约未提交及模拟元数据。仍有1手部轮answer_fact_unsupported安全降级，未输出不支持的数字。不是全语言/医学/生产或容量通过率。最终捕获runtime/demo-chat-report.json、demo-chat-final-46.json与demo-chat-transcript.md。首轮JSON因备份路径错误被第二轮覆盖，首轮异常仅在终端输出与本记录保留，不声称有完整首轮原文件；上一批chat-quality捕获未覆盖。

API仅核实完整命令后重启8001，最终PID17060/session27824，migration012，5173/5175与5174不动。下一步仍扩大实际公开事实/语义评估、完成M6恢复运维；真实机构/医生/注册/医学批准/供应商仍需核验，云部署等待服务器信息，不能把演示价格或本地模拟审批当成真实医疗上线批准。

现场最终补验：浏览器额外4轮有具体补水步骤/费用、补水水光比较与只咨询选项。第三轮遗漏水光项目演示起价只回答0元咨询费，补保留末句价格quote候选、项目费/咨询费分开提示后，第四轮正确298元/398元、1280元与0元40分钟并展示两张卡片；最后专项20 passed/20.35s、Ruff74/mypy34复核通过。完整46轮捕获在该末句提示调整前，最后通过API页面额外补验，不夸称重新全量46/226。截图demo-consultation-browser.png与demo-consultation-prices-browser.png已目视确认，文本demo-browser-transcript.txt；临时标签关闭并确认恢复原对话4选择，用户客户/后台两页保留，不注销其访客、不删除历史或提交业务。最终8001 API PID27064/session56018、migration012。当前主PG/Milvus/Neo4j310个发布/索引版本（含历史被替代版本，不能称310条当前有效公开知识），25个医学draft/outbox空。15份Markdown本地链接通过，.env/密码/runtime捕获和截图均忽略，Git仍main/未跟踪，无提交推送。

## 2026-10-12 情绪识别与共情咨询落地

用户要求加入情绪识别和安慰话术；按单里程碑完成，执行前说明范围与标准，读取规范并检查Git。实现 app/emotion_support.py，更新 agent_policy、consultation_agent、conversation_context、agent_repository、consultation_gateway；新增 data/empathy_knowledge.json、empathy_chat_cases.json、tests/test_emotion_support.py，补 Gateway 出口测试、导入/授权/采集脚本及客户可选 public_answer 类型。无新增依赖、迁移、grants、医学批准、云部署或业务提交。模型只经Gateway；纯情绪本地回答，混合问题仅公开任务外发，原情绪/关系/临床/身份正文不出站；checkpoints不记录情绪正文或类别，不建长期情绪画像。

30条新增合成知识由独立开发账号按既有流程导入/审核/发布；18公开回应、12内部沟通策略，均真实Qwen256维向量与Neo4j投影。497摘要授权快照仅增加当前数据摘要，LLM_MODEL/URL/API key/业务密钥原样。主库最终只读 pipeline_status：340 published/ready、340本库Milvus向量/Neo4j版本、outbox空，含历史；25原医学draft和withdrawn版本不变。内部98销售策略不因此称为全部生成链路接入。

验收：最初85 passed/1失败发现情绪-only命名主题下一轮没有公开前文而固定澄清，修本人授权来源解析顺序后89通过；安全连续状态33和最终任务/暂停34专项通过。额外输出防护专项94 passed/1失败为PG OperationalError，根因未确定，独立同例1 passed/15.21s；最终冻结语义后独立受影响咨询专项 **96 passed/178.69s**。不忽略失败/放宽断言，不声称根治依赖故障或重跑全后端。最终Ruff检查/格式76文件、mypy35源文件通过；客户37项及TypeScript/Vite构建通过，后台未变。

实际8组合成访客25轮第二轮全HTTP200、幂等重放/本人历史/退出一致：11fixed、9generated、5handoff，无fallback，15个定向检查通过，中位0.78s/max8.05s不是容量。首轮捕获empathy-chat-first.json保留；第二轮empathy-chat-final-25.json与empathy-chat-report.json、empathy-chat-transcript.md另存。25轮早于最后输出拒绝与裸预算严格问题判断，最终版本另做96工程专项与页面4轮，不能称全部语义/临床通过。

页面4轮实际验证低落陪伴、共情开场+明确费用、裸预算压力仅安慰、暂停不追问；后两轮在最终代码重启后完成。runtime/empathy-browser-transcript.txt、empathy-consultation-browser.png、empathy-pause-browser.png已保存并目视检查。仅按核实命令重启8001，最终PID12076/session40092、门槛012，不动5174或用户双端Vite。无预约/回访/CRM/短信提交、无用户数据清理。详细样例、复现、隐私/有限规则边界见 [共情设计](empathy-design.md)；真实医疗、资质、供应商、M6运维/恢复、容量与云地址仍待验。

收尾：确认恢复用户原对话5（15:54:32），临时标签关闭，原客户与后台标签保留且未注销访客。Git仍main/源码未跟踪；.env、种子密码和runtime原始捕获/截图忽略，无提交或推送。

## 2026-10-12 固定咨询Agent运行时沙箱

用户明确要求判断必要性并实现以用于面试说明。执行前说明本批目标、运行进程/固定任务协议/权限资源/故障验收；读取规范/架构/待确认及Git，未发现额外物理AGENTS。仅此里程碑，无子代理/提交推送、无新知识/医学批准/模型出口/客户业务权限、无前端源码改动或部署云端。

新增 app/sandbox_runtime.py、sandbox_broker.py、sandbox_worker.py、sandbox_wire.py、sandbox/Dockerfile/requirements.lock、.dockerignore、tests/test_sandbox.py、scripts/sandbox_acceptance.py、sandbox_smoke.py；独立 sandbox/probe.Dockerfile/probe.py 仅故障验收镜像。API/config接默认Docker运行、生产拒绝进程内、启动/就绪检查；consultation_agent 提取原plan与memory_snapshot供父子复验，仅在未注入远程服务时才建外部客户端。vector_adapter将Milvus SDK延迟到实际调用，pipeline_status显式导入；主依赖锁不变。测试fixture显式inprocess，真实Docker验收显式开关。

容器每轮独立、无网络/端口/宿主或Docker socket挂载、无dotenv/密钥，UID/GID65532、只读根、cap全部移除、禁止提权、默认seccomp、8MiB noexec临时目录、512MiB内存与同额swap总限、1CPU、64PID/128文件描述符、默认45秒执行预算、每API实例2槽。JSON有界，不使用pickle。Broker每调用复验父绑定actor/run/lease，拒绝任意Shell/SQL/业务/额外范围；模型只当前公开任务，历史/证据主服务重建，最终答案/路由/记忆/动作父复验再持久提交。数据库调用连接级5秒statement/2秒lock，未改变PG角色；失败不回退或生成假回答，原键/检查点恢复。子Linux计时器独立于父API防止启动器失联继续执行。45秒不等于全HTTP SLA，可信服务在途调用/前置准备/清理仍分别有预算。

过程：首份全依赖镜像下载慢，终止后改47项最小锁定闭包/延迟Milvus导入并使用常见Aliyun包镜像，pip check通过；没有复制其他项目镜像/密钥。短参数ID前超大帧fixture产生过长输出/setup错误，显式短ID后消失；第一真实专项19通过/1失败是暂停断言只接收一种合法话术，改为验证已审核两种原文、无问号/新项目/动作后通过。首整批受影响9个测试文件 **162 passed/354.90s**，真实Docker+ma_m1_test，模型用测试替身；该批早于最终自主计时器、拒绝调用trace和就绪检查，不能称最终全后端通过。最终冻结后沙箱专项/边界与实际HTTP另追加。

首独立真实资源验收16个边界检查全true，异常JSON/超大帧安全拒绝、OOM资源退出、10秒超时终止、未知操作拒绝，剩余容器空。后续最终镜像追加独立worker计时器退出测试。故障镜像不访问DB或模型；不把临床数据/原客户记录作为测试输入。镜像固定ID、实际验收捕获与面试说明见 [运行时沙箱](runtime-sandbox.md)。这批是容器隔离，未实现微VM/镜像签名/集群配额/daemon故障自动对账；真实生产运维与医学、供应商、云地址仍待验，既有Milvus开发unconfined配置未改动。

最终实测：受影响整批162 passed/354.90s之后，最终沙箱专项 **28 passed/90.21s**（MA_TEST_SANDBOX_DOCKER=1，无跳过）；Ruff检查/格式84文件、mypy39源文件通过。前端未改动，不重复构建；不是最终全后端回归。最终真实故障验收16项边界全部true、异常/超大JSON拒绝、OOM资源退出、10秒父监督超时、未知操作拒绝和子自身计时器全部通过；自身计时器 exit142/14.45s（含镜像启动/导入，不是精确10秒全HTTP SLA），故障结束 remaining_containers=[]。原始runtime/sandbox-boundary-report.json保留。两次清理同时发生的Docker --rm/rm竞争曾输出cleanup pending；只读元数据确认“removal ... is already in progress”，增加不存在确认及安全日志专项，最终仍可能在后台移除尚未完成时记录pending，故障结束和HTTP后均确认无遗留；不把瞬时pending伪装成已发现daemon故障或保证所有故障下清理。

当前本地API已经启用默认Docker路径，PID14340/session57530，迁移012；仅重启已核实8001进程，5173/5175及5174保持。固定独立合成访客真实Qwen/API四轮：问候fixed、预算担忧+补水价格generated、关联步骤generated、暂停fixed；全部HTTP200、同键重放一致、每轮仅1条sandbox/completed trace、历史8消息及退出后401通过，均无预约action或业务提交。每轮沙箱节点5.452/14.467/10.328/5.422秒，包含冷启动/IPC/检索或模型，是实际小集耗时，不是生产SLA/容量。runtime/sandbox-chat-report.json有完整合成回复和元数据，LLM仅当前公开问题/批准证据；低落/临床/身份原文不外发。

实际运行镜像ID：sha256:cf601dd0539f0a63bf24028f10a14601222a31f66a3dc64b30c168b457074b64；独立故障镜像：sha256:13b482db70047361ddde39e5be7f4c9b95b82f83a8a2bcc4e381e3094fe0d17f。代码或配置改变后需重建与重启；当前镜像和启动器使用同一冻结代码。用户.env/LLM配置、知识批准/版本、租户门店授权、客户确认和业务密钥未改动；没有云部署、短信/CRM、提交推送。Git仍main/源码未跟踪，.env/种子与runtime捕获忽略。最终17份Markdown本地链接无缺失。后续仍需生产受控启动器/镜像供应链、daemon故障自动对账、跨实例配额与容量工程；医学/真实资质/供应商、备份恢复、云服务器信息未由本批替代。


## 2026-10-13 云演示部署批次

用户选择演示/面试、提供腾讯云服务器并授权暂停原6容器以部署；模型密钥传输经自动审批拒绝后，用户明确授权再完成，密钥始终不打印/提交。独立项目、网络/存储/权限/SSL、每轮Docker沙箱保留。原项目镜像卷配置保留，原6容器exited；新8容器运行无OOM/重启，核心存储/APIhealthy。HTTPS8080正式IP证书及每6小时cron续期演练通过，443公网未放行，不改安全组。308当前知识实际向量/图谱就绪、31历史不激活、25医学待审。云发现预算数字复述导致answer_fact_unsupported，调整提示及一次有界校验重试，35项Agent/Gateway回归55.45秒、Ruff、mypy42源文件通过；双前端构建/68项Vitest通过。最终真实公网5轮合成聊天、上下文、共情、沙箱trace、预约本人确认→门店确认及跨门店/访客/角色/退出拒绝全通过，医疗个体转人工。只操作脚本自己的合成申请，保留用户在网页中自行提交的记录。

本地复验、文件、角色、恢复脚本及快照详见[云演示交付](cloud-demo-deployment.md)。内存可用约1937MiB、磁盘7.3GiB只是瞬时/单人合成快照，不达到Milvus8GB官方最低要求或100RPS证明。未实际切回原项目、未重启服务器、未完成CI/CD/备份恢复演练/长期监测/真实SMS/医学核验，非真实医疗生产上线。下一批GitHub/CI/CD、独立备份恢复和监测。
