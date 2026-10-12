# 知识、Milvus 与 Neo4j 数据规范

状态：数据源共 264 条（6 基础 + 32 原目录 + 226 扩展），已导入并实测重复导入幂等。226 条扩展含 20 个项目了解入口、100 条运营 FAQ、40 条内部沟通策略、40 个内部多轮场景、6 条官方品牌概况、20 条权威医学/监管待审摘要。合成供给/政策与公开事实区分来源；内部策略不冒充真实销售经验。用户提供 LLM_* 配置并授权当前全部知识后，239 条非医学资料已完成真实 Qwen 256 维 embedding、Milvus 回执和 Neo4j 投影，状态 published；25 条医学资料（20 摘要 + 5 历史待审任务）保留 draft。正式机构核验仍未完成。

扩展 FAQ 覆盖入口、需求、项目比较、报价、预约、隐私、门店、专业评估、到店后服务及投诉反馈；策略/场景覆盖漏斗阶段、客户拒绝、意向变化、转人工、确认缺失与调用故障。题目变体、来源 URL、查阅日期、适用地区、阶段、允许动作和转人工原因进入不可变版本详情。100 条关联题仅作目录覆盖样例，31 条独立改写问题用于词项降级召回验收，不能替代真实模型语义评测。

## 内容类型与来源

2026-10-12 新增具体演示知识70条（30方向/24运营问答/6医学比较/10内部策略），详见[演示咨询](demo-consultation.md)。旧264条与下文数字保留为扩充前基线。最新用户允许演练完整场景，新增22条medical且review_scope=demo_education的公开科普，只在显式非生产模拟模式走独立模拟复核与正常投影；标准模式仍拒绝医学批准，原25条未标此范围的医学待审不改变。价格/流程是虚构场景，不伪造真实说明书、注册证或执业凭据。模拟科普批准不构成真实医学批准。

- 项目事实：正式名称、分类、介绍、流程、一般注意事项、来源；具体疗效/禁忌等医学内容独立待审。
- 业务政策：门店供给、价格、活动、预约/取消规则。缺少内部资料时生成明确模拟数据，不宣称公司政策。
- 沟通策略：场景、漏斗阶段、目标、允许动作、示例表达、禁止表达、退出条件。合成策略不冒充真实“金牌销售”记录。
- 客户问答：问题变体、必要上下文、答案依据及应转人工条件。
- 图片与详情：图片权利/来源、用途、alt、审核状态、内部详情路径。没有使用权的公开图片不自动下载发布。

统一字段：id、tenant_id、type、title、body、source_type、source_url/source_ref、retrieved_at、simulation、medical、author_id、version、content_hash、review_state、reviewer_id、reviewed_at、publish_state、scope、valid_from、valid_until、supersedes。

source_type = official_public / authoritative_medical / institution_supplied / synthetic。simulation 不等于医学批准；公开内容也不自动可发布。缺少价格/资质/注册证时使用空值与 pending，不生成逼真伪造记录。

当前 KnowledgeDetails 已实现 synthetic / official_public / authoritative_medical；institution_supplied 属于真实资料接入规划。非合成来源必须同时提供 URL 和日期，地区为 CN/US/global/unverified。所有本地导入条目仍带模拟演练标记。品牌名称及定位依据 [美丽田园投资者官网](https://ir.beautyfarm.com.cn/cn/about-us/)；不是某个门店当前供给证明。医学摘要来自国家卫生健康委及 FDA 官方资料，来源逐条记录于 consultation_expanded.json；FDA 内容标为 US，不能视作中国注册/说明书/适应证或实际机构资质。国家卫生健康委一条原文页面本次返回 412，摘要明确限于可见索引、等待原文复核，不能作为已核验医学证据发布。

## 审核与检索

draft → in_review → approved/rejected；approved → publishing → published；撤回为 withdrawn。修改产生新版本并重审。作者不得自审医学内容；模拟审批独立记录 simulation_review=true，真实客户医疗入口不得消费此批准。

正式发布需要审核、范围、来源、有效期完整且投影就绪。模拟资料只能用于显式模拟环境，卡片及答案显著标记；生产入口需要真实供给核验。售卖话术不能支撑医疗结论、覆盖价格事实或形成未经确认的客户适用性。

文档按独立语义单元切块，chunk 保留父文档、版本、标题与来源；禁止跨版本拼接。先权限/发布过滤，再召回，再重排；按 question_type 选择全文/向量/图谱组合。图谱与向量冲突时以权威版本为准，不能通过模型投票解决。

## 图谱规范

| 节点 | 关键属性 |
| --- | --- |
| Brand / Store | id、tenant、正式名称、simulation |
| Project / Product / Device | id、类别、版本引用、供给核验状态 |
| Concern / ServiceCategory | id、受控分类名称 |
| Practitioner | 公开已核验资料引用；模拟人员不能有虚构真实资质 |
| KnowledgeVersion | id、version、hash、审核发布范围与时间 |
| Strategy / ConsultationScenario | 场景、阶段、允许表达、合成标记 |

关系：Brand-HAS_STORE-Store；Store-OFFERS-Project；Project-BELONGS_TO-ServiceCategory；Project-RELATED_TO-Concern；Project-USES-Product/Device；Practitioner-PRACTICES_AT-Store；Practitioner-PROVIDES-Project；Strategy-APPLIES_TO-ConsultationScenario；实体与关系均由 KnowledgeVersion 支撑。

每条事实关系具有 assertion_id、knowledge_version_id、tenant_id、scope、valid_from/until、simulation。Project-RELATED_TO-Concern 仅表达了解入口，不推导客户适合项目。价格采用 PostgreSQL 带门店与有效期的记录；不在图谱形成无版本全局价格。

投影只含审核知识；内部沟通策略使用独立 audience，不能进入公开查询。禁止客户身份、健康信息、聊天和预约进入知识图谱。Cypher 仅由适配器维护的参数化模板执行；唯一性包含 tenant/store/version/key，索引版本字段，生产写入角色与查询角色分离仍待配置。Outbox 乱序使用版本比较避免旧事件覆盖新发布；重建以权威发布快照和事件水位恢复仍待验收。

## 合成沟通策略样例（非真实销售材料）

场景：客户价格顾虑。目标：解释已发布价格范围与包含项，了解客户是否愿意提供预算；提供继续了解或到店咨询的选择。禁止：编造优惠、保证疗效、贬低竞品、反复催促。退出：客户拒绝预约或只想获取知识时停止邀约。正式上线前由机构审核。

## M2 数据与投影实现及限制

`backend/data/consultation_catalog.json` 与 `consultation_expanded.json` 是受版本控制的数据源，`knowledge_import` 先校验全文件结构和关系端点，再通过既有门店授权、版本创建、独立审核与发布服务写入；scope/key/内容摘要唯一导入凭据保证重跑不刷新期限、不复活撤回记录。新增可选详情字段不会改变旧数据导入摘要。内容变化新建版本，仍需独立审核。仅开发/测试显式模拟配置可导入。标准模式医学条目仍draft；最新受控演示科普例外须满足上文全部范围，不能用于真实客户医疗。

公开资料与内部策略通过 knowledge_detail.audience 分开；communication 不能标为 public，策略不会返回给客户检索 API。当前每个短条目一个完整向量，长文语义切块、重排、图文/详情关联及正式医学核验仍待下一批。销售策略供后续 Agent 内部路由选择，尚未实现对话生成。

Milvus 存储 256 维 embedding 和 tenant/store/version/hash/model/audience/模拟标记/期限；HNSW/COSINE、Strong 读取、独立读写账号与受控过滤模板。PostgreSQL vector_projection 保存持久回执与集合，unknown 写入先查询对账，match 复用、不重复 embedding/upsert，冲突拒绝，查询失败不盲写。没有回执、错误集合或摘要不一致均阻断证据。历史 003 的 pgvector 表保留，不再由应用读写；004 为增量迁移并重排历史发布。安装基于 [Milvus 官方 standalone 配置](https://milvus.io/docs/v2.5.x/install_standalone-docker-compose.md) 和 [集合权限接口](https://milvus.io/api-reference/pymilvus/v2.5.x/MilvusClient/Authentication/grant_privilege_v2.md)。实际集群容量、生产证书/备份与恢复仍待验收。

Neo4j 采用 KnowledgeVersion / KnowledgeEntity 两种持久标签，实体 kind 为受控的 Project/Category/Concern/Strategy/Scenario；SUPPORTS 绑定证据，ASSERTION.kind 为受控关系类别。唯一性包含 tenant/store/version/key，禁止跨版本合并关系；所有图谱查询使用适配器参数化模板和 PostgreSQL 允许的版本 ID。这里没有真实医生、产品注册或客户记录。

Outbox 短事务领取任务、90 秒租约、SKIP LOCKED、令牌围栏；外部图谱/模型调用不占用数据库事务，失败写安全代码并指数退避。最终就绪前锁住版本、重新检查审核/期限/门店/新版本和租约，两个投影完成才 published。图谱写入/删除可幂等重放；数据库权威会立即阻断撤回。极端租约过期并发可能短暂留下失效图节点，查询仍须 PostgreSQL 授权过滤；全图校验与重建水位验收尚未完成。

Qwen embedding 适配器实现 `text-embedding-v4` / 256 维请求、12 秒超时、瞬时故障最多两次尝试、进程内熔断及联系方式移除。用户新增的全量知识出口授权以精确摘要快照记录，包含 264 条知识、131 条合成题和固定合成诊断，共 396 个摘要；导入仍不自动扩大，新资料改动需更新授权。真实 embedding/chat 合成探测通过，239 个真实向量已入主 Milvus 集合。31 条独立合成问题全部走 hybrid，recall@5=30/31，未命中 qa-compare-06；这是词项/向量/图谱混合小集，不代表临床安全或向量单独效果。医学、内部资料仍受原审核/audience 边界约束。跨进程熔断、完整响应预算、客户 chat generation 和医学问答均未完成。接口依据 [阿里云 embedding 文档](https://help.aliyun.com/zh/model-studio/embedding) 及 [Qwen Chat 官方文档](https://help.aliyun.com/en/model-studio/qwen-api-via-openai-chat-completions)；Neo4j 幂等事务依据 [官方 Python Driver 文档](https://neo4j.com/docs/python-manual/current/transactions/)。

## 共情知识（2026-10-12）

新增 backend/data/empathy_knowledge.json 30 条合成资料：18 条 operational/public 回应（9 类各两种），12 条 communication/internal 场景策略。使用既有独立开发账号审核、版本/outbox、真实 Qwen embedding、Milvus 与 Neo4j；没有新增医学批准。公开话术才用于本地对客回应，内部策略仍不直接当作项目事实；既有 98 条销售库不能因此称为全部接入生成。当前各库 340 个发布/就绪版本含历史，原 25 个医学 draft 保留，见 [共情设计](empathy-design.md)。
