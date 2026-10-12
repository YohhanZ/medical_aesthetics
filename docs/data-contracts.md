# 数据与接口契约

2026-10-12 聊天修正保持消息/运行/历史API结构及版本/幂等不变。intent新增本地recall，mode仍fixed；回忆只说明有来源的本会话公开主题，无法确定时明确说明。业务意愿仍action.visit_interest/submitted=false；实际付款/取消只说明业务处理原因，不执行。公开历史来源失效时不传给模型，重放仍按当前证据/目录过滤；内部medical_pending与主题引用不是前端传入授权或医疗判断。没有新增访客写权限、业务字段、通知或长期记忆。

## 机构运营演示资料（2026-10-12）

GET `/api/stores/{store}/demo-materials`：有效员工Bearer、当前门店customer_read，非生产且显式allow_simulated_data、活动模拟门店；成功200、读取审计。未登录401，未授权门店/角色403，生产/关闭模拟/不适用门店404。不新增写接口、权限或迁移。

返回pack_id/version/simulated/disclosure/created_on/valid_until/rag_status=presentation_only_not_published、虚构institution、唯一store、仅当前店personnel/services/policies/journeys，以及包级虚构suppliers/review_records/scripts。原JSON的stores全量不返回；机构/医师/产品证号为空，供应商review.actual_result始终“未验收”，demo_result明确“模拟通过”，evidence_reference为SIM流程编号。JSON导出为同一当前门店DTO，不包含实际员工凭据、手机号或客户业务。日期为资料演示期，不授予实际供给/资质有效性。完整内容见demo-materials.md。

状态：M1 身份/知识与 M2 Milvus 回执、005/006 Agent 消息、运行、checkpoint、短期摘要、转人工工单及本地 trace 已迁移。M3 已实现客户会话恢复、线程列表、公开门店、图文目录/详情及 007/008 持久预约申请；009 已接 M4 授权门店收件、确认与婉拒。本地模拟核验已验；真实短信待验。下文通用 API 表仍为规划，实际接口见末尾；注册、长期记忆、SSE、改约/取消/到店及其他员工业务仍待实现。

后台首批读接口已实现：GET /api/staff/me（当前员工和明确授权门店），GET /api/stores/{id}/knowledge（授权门店内部知识分页，items/total，limit 最大 100）。没有扩展客户数据读取权，也不通过前端门店选项赋权。后台前端员工登录和知识操作已接这些接口；其他管理业务仍待实现。

## PostgreSQL 逻辑实体

| 实体 | 关键内容 |
| --- | --- |
| tenant / brand / store | 机构、品牌、门店、公开目录范围与状态 |
| staff / store_grant | 员工身份、角色、明确门店授权 |
| visitor / customer / identity_link | 持久访客、核验客户、经确认的关联证据 |
| thread / message / run | 所有权、输入去重、运行状态及并发版本 |
| memory / consent | 来源、偏好确认、用途、撤回与期限 |
| project / offer / media_asset | 项目版本、门店供给、价格期限、图片权利 |
| knowledge_version / review / publication | 内容版本、独立审核、发布与投影状态 |
| appointment_draft / confirmation | 草稿快照、内容哈希、确认时间/方式/证据 |
| appointment / appointment_event | 申请状态、期望时间、确认时间及历史 |
| consultation / intent_event | 本次需求、最初与后续意向、最终客户确认引用 |
| handoff_ticket | 转人工原因、分配、等待及处理状态 |
| idempotency / audit / outbox | 持久幂等、审计、事务事件 |

业务表必带 tenant_id；门店资源带 store_id。查询带完整授权谓词，禁止只按 id 查后由前端判断。审计无明文密钥和联系方式；联系方式加密并通过受限业务接口访问。审计最小字段为 actor/action/resource/version/time/result/trace_id。

## 预约状态

draft → pending_store_confirmation → confirmed → arrived → completed。

待确认或已确认可取消；已确认可标 no_show；门店不能接受时标 declined 并给原因。改约为 change_requested，保留旧确认与新请求；新时间确认后生成事件，拒绝修改则保留原安排。终态不能靠普通 PATCH 任意恢复。

跨门店变更重新校验授权与供给，并重新取得客户确认。客户最初意向不被到店项目覆盖。报价或最终项目变更不能仅由 Agent 摘要表示客户同意。

## 客户 API 提案

| 接口 | 契约 |
| --- | --- |
| POST /api/visitor-sessions | 建立持久访客，签发安全 cookie，不接受员工角色 |
| POST /api/threads | 创建自有会话，入口 scope 服务端确定 |
| POST /api/threads/{id}/messages | message_id 去重，返回 run_id，校验所有权 |
| GET /api/runs/{id}/events | SSE：progress、answer_segment、project_cards、confirmation_required、done、error；event_id 支持重连 |
| GET /api/catalog/projects、/stores | 仅有效公开资料，模拟环境返回显著标识 |
| POST /api/contact-verifications | 验证联系方式；供应商未定，本地模拟不得进入生产 |
| POST /api/appointment-drafts | 校验门店与意向，返回草稿快照和过期时间 |
| POST /api/appointment-drafts/{id}/confirm | 明确客户动作、草稿哈希、有效确认凭证、Idempotency-Key；返回 pending_store_confirmation |
| GET /api/appointments/{id} | 仅本人记录，不通过手机号即可查他人预约 |
| POST /api/appointments/{id}/change-requests、/cancel | 核验身份、版本与明确确认 |
| POST /api/handoffs | 建立转接工单，不假装人工已接通 |

内部员工接口单独鉴权，知识发布/门店确认/客户档案写入必须使用明确动作接口及审计。确认接口同时驱动预约图的授权恢复，客户端不能直接提交 LangGraph goto/update 指令。

幂等键唯一范围 tenant+actor+operation+key；同键同请求返回原结果，同键不同内容返回 409。持久结果与业务事务一起提交；重放仍先鉴权，不能泄露原主体结果。乐观版本冲突返回 409，未知外部结果标 reconciliation_required。

错误响应：code、safe_message、retryable、request_id；禁止把 SQL、供应商响应正文或 secret 返回客户端。SSE 状态持久化且分页/保留受限，不保存未经校验的模型 token。

## M2 消息实际契约

POST /api/threads/{id}/messages 接受 message_id(UUID) 和 question(1–2000 字符)，要求访客 Cookie + CSRF；同步返回已提交的 run_id/message_id/thread_id、answer、intent、funnel_stage、mode、evidence_ids/evidence、handoff_reason/handoff、action。来源 metadata 含 id/title/source/version/simulated，不由模型生成目录 URL。mode 为 fixed/generated/evidence_fallback/handoff，旧来源失效读取为 stale。

GET 同一路径返回分页历史；GET /api/threads/{id}/runs/{run_id} 返回运行状态、结果和节点元数据。所有操作校验凭据与自有会话；completed 重放不免除授权/证据检查。visit_interest action 的 submitted=false 仅为该消息时的意愿记录；当前预约状态另读 booking 接口。waiting 工单 connected=false，无员工处理接口。消息接口尚未改为异步/SSE，提案事件接口当前不可用。

## M3 第二批实际预约契约

路径前缀均为 `/api/threads/{thread_id}`，访客 Cookie 重新验证自身及当前门店，写入同时要求 X-CSRF-Token；客户端不能指定租户、员工角色或他人资源。

| 方法与路径后缀 | 实际输入与结果 |
| --- | --- |
| GET /booking | configured、simulated_verification、trigger_run_id、draft、verification、appointments、blocked_reason；只读自身当前状态 |
| POST /appointment-drafts | request_key、trigger_run_id、name、phone、desired_at（含时区）、intention、可选 project_version_id；201 草稿，含 request_key、snapshot_hash、phone_masked、policy 和过期时间 |
| POST /appointment-drafts/{draft_id}/verification | request_key、sms_consent=true；持久发送记录，返回核验引用/状态；simulated_code 仅显式开发模拟返回 |
| POST /contact-verifications/{verification_id}/verify | 六位 code；错误次数即使返回错误也提交，成功凭证绑定该草稿/手机号 |
| POST /appointment-drafts/{draft_id}/confirm | request_key、snapshot_hash、verification_id、accepted=true、confirmation_text=确认提交预约申请，等待门店确认；返回持久待门店确认申请 |
| POST /appointment-drafts/{draft_id}/discard | 撤销自身活动草稿；不取消已提交申请 |

007 实体为 appointment_draft、contact_verification、appointment_confirmation、appointment、appointment_event、booking_outbox、booking_idempotency；008 将事件/outbox 绑定 tenant/store/visitor 及复合申请外键。草稿加密快照包含身份用途信息、期望时间、意向、项目及公开政策版本；确认含时间、customer_button 方式与请求证据引用。phone/code/内容/幂等摘要使用 HMAC，不在审计记录明文电话。

草稿 30 分钟、验证码 5 分钟/最多五次错误、有效核验 15 分钟且只能消费一次。新草稿替代旧草稿，旧核验不能用于新内容；当前政策/项目撤回、触发运行不再是最新预约意愿、凭据失效均拒绝确认。同键同内容返回原业务结果并先鉴权，同键异内容 409；确认、申请、事件/outbox、幂等与审计同事务。未知短信发送先核实原记录，不盲重试。本批只能创建 pending_store_confirmation；后续状态变化、员工通知/处理、改约/取消仍待 M4，不能将计划状态图视为已实现接口。

## M4 首批实际门店契约

所有路径为 `/api/stores/{store_id}/appointments`，使用有效员工 Bearer 凭据，重新验证精确 tenant/store grant。知识和平台管理员权限不授予客户访问。009 新增版本/当前状态及独立员工幂等；以下更新 M3 阶段仅待确认的历史实现边界。

| 方法与后缀 | 实际契约 |
| --- | --- |
| GET 根路径 | appointment_read；可选 state（pending_store_confirmation/confirmed/declined）、limit 1–100 默认25、offset 0–10000；items/total/counts，全门店状态计数不受分页筛选影响 |
| GET /{id} | appointment_read；掩码号码、客户确认时间/方式、当前 version/state、desired_at、confirmed_at、有限公开 decision_reason 和事件历史 |
| POST /{id}/contact | appointment_read + appointment_contact；单独审计后返回本次联系号码，前端一分钟或关闭详情后隐藏，无本地持久缓存 |
| POST /{id}/decision | appointment_read + appointment_manage；request_key(UUID)、expected_version、action(confirm/decline)、accepted=true、availability_checked、reason |

confirm 要求 availability_checked=true、reason=null、有效政策/项目及未来有效期望时间；服务端从客户加密快照读取原时间，接口不接受新时间。decline 需 reason 为 no_availability / unable_to_contact / other。相同请求键重放重新鉴权并返回当前记录；同键异内容 409，版本或状态冲突 409。状态变更、version+1、事件 actor/time/request_id/reason、幂等与审计同事务；没有随机默认授权或绕过审核的模拟分支。

客户 `/api/threads/{id}/booking` 的 appointments 增加 version、confirmed_at（到店时间，不是操作时间）、decision_reason。首批允许 pending_store_confirmation→confirmed/declined；后续接口见下方第二批。通知 outbox 未处理，客户需要刷新权威状态。

## M4 第二批实际生命周期契约

| 路径（POST） | 输入与权限 |
| --- | --- |
| /api/stores/{store}/appointments/{id}/change-proposals | 员工 read/manage；request_key、expected_version、accepted=true、availability_checked=true、proposed_at（带时区，15分钟之后/90天以内） |
| /api/threads/{thread}/appointments/{id}/change-response | 自有访客 Cookie + CSRF；request_key、expected_version、accepted=true、proposal_id、snapshot_hash、decision=accept/reject、confirmation_text=确认接受新的到店时间/保留原安排，拒绝此次改约 |
| /api/threads/{thread}/appointments/{id}/cancel | 自有访客 Cookie + CSRF；request_key、expected_version、accepted=true、confirmation_text=确认取消本次预约 |
| /api/stores/{store}/appointments/{id}/arrive | 员工 read/manage；request_key、expected_version、accepted=true、identity_checked=true |

输入禁止多余字段，不接受员工代客户确认或临时角色。所有接口返回权威预约DTO（员工含事件）；增加 arrived_at、change_proposal（id/version/snapshot_hash/proposed_at/expires_at，或null）。掩码号码不变，提案不含解密业务快照。staff列表筛选另支持 cancelled/arrived/completed/no_show；后两种仅允许查询，不表示实现状态写入。

提案30分钟有效，仅待确认/已确认预约能发起，不能与原时间相同。原状态/确认时间保持到客户接受；拒绝保持原安排，过期/替换不自动变更。存在有效提案时原时间确认和到店登记409。接受再次校验有效知识和提案人员门店权限；无效提案、版本冲突、同键异内容409，缺明确确认422。取消保留申请与历史，允许知识撤回后取消；已到店/婉拒等终态不能取消。到店登记不会自动新建注册客户或修改医疗档案。

010独立 booking_action_confirmation 保存每次操作的加密业务快照、摘要、固定文案、customer_button/staff_button、服务端时间及请求ID。状态version+1、事件、幂等、审计同事务；同键重放鉴权后返回当前状态，不能恢复过时安排。通知/外部CRM尚未处理，超时先刷新核实/原键重试。

## M3 已实现契约补充

| 接口 | 实际返回与限制 |
| --- | --- |
| GET /api/public/stores | 公开门店 items：code/name/simulated；不返回租户/客户/员工记录，生产排除模拟门店 |
| GET /api/visitor-sessions/current | 当前访客 visitor_id/store_id/store_code/store_name/simulated/csrf_token；需有效访客 Cookie |
| GET /api/threads | 自己的最近 20 个 thread_id/created_at；同门店、同主体 |
| GET /api/threads/{id}/messages?recent=true | 最新分页按时间正序返回；limit/offset 有界，默认旧接口顺序保持 |
| GET /api/catalog/projects | items 为当前门店有效公开项目视图，不能指定其他门店 scope |
| GET /api/catalog/projects/{version_id} | 单个当前有效目录 DTO；不可见/撤回/越店统一 project_unavailable/404 |

Project DTO：id（knowledge version UUID）、key/title/category(care/medical)/summary/description/topics/image_url/image_alt/image_provenance/detail_url/source/version/simulated/valid_until。图片为有限本地 `/images/*-v2.jpg`，详情为 `/#project/{id}`。medical 类仅公开了解入口，不代表医学资料获批准或个人方案。

消息结果新增 project_ids/projects；仅普通 generated/evidence_fallback、无风险原因且问题有明确匹配时输出最多三张卡片。安全关联追问允许沿用上一条公开问题方向；引用本身不能引入无关卡片。历史/重放按当前权威版本过滤。HTTP 客户端不自动重试未知写入，仅服务端写入前拒绝的 csrf_invalid 可刷新令牌并原键重试一次；网络未知提供核实/原键恢复。

## M5 首批到店咨询实际契约

员工路径前缀为 `/api/stores/{store}`，有效 Bearer + 精确门店 grants；访客路径为 `/api/threads/{thread}/appointments/{appointment}/consultation`，有效自有访客 Cookie，写入另需 CSRF。所有命令禁止多余字段，不接受租户、员工角色、客户确认时间或任意工具参数。

| 方法与路径 | 实际契约 |
| --- | --- |
| GET /consultations | customer_read；limit 1–100 默认25、offset 0–10000；items/total，仅授权门店 |
| GET /consultations/{case} | customer_read；完整咨询意向历史、当前版本、原意向及掩码号码；读取审计 |
| GET /consultation-options | customer_read；有效已发布公开 catalog-* 版本的最小 id/title/simulated；不开放内部知识 |
| POST /consultations | customer_read/manage + appointment_read；request_key(UUID)、accepted=true、appointment_id、expected_appointment_version；必须 arrived，每预约仅一份；200 |
| POST /consultations/{case}/revisions | customer_read/manage；request_key、accepted=true、expected_version、name 1–40、intention/reason 1–300、project_version_id(UUID或null)；追加版本，不覆盖原意向；200 |
| GET 访客根路径 | 自有预约/线程；返回同一 VisitCase 或无档案时 null，越权404；不返回其他预约档案 |
| POST 访客 /decision | request_key、accepted=true、expected_version、snapshot_hash(64位hex)、decision=accept/reject、confirmation_text；只允许客户本人；200 |

VisitCase：id、appointment_id、version、simulated、initial(name/intention/project_title)、phone_masked、current、history。每个意向版本含 version/name/intention/reason/project_version_id/project_title/source(original_application或staff_record)/snapshot_hash/recorded_at/decision(accept/reject或null)/confirmed_at。confirmation_time 与摘要由服务端生成；DTO 不含完整手机号、员工凭据、加密正文或内部评估。

接受固定文案为“确认本次咨询意向（不代表治疗或合同同意）”，拒绝为“暂不确认，继续沟通”。accepted 是客户已审阅/员工已明确操作的勾选，decision 为客户实际选择，不把勾选当作同意治疗。只允许当前未回应版本；顾问修改后新版本 decision=null，旧确认保留。接受再次校验项目与记录顾问权限，缺明确确认422、版本/摘要/作者权限变化或同键异内容409、失效项目404；拒绝可在项目撤回后执行。

011 保存完整租户/门店/访客范围、原申请加密引用、append-only版本和客户处理快照/固定文案/方式/服务端时间/请求证据，以及独立持久幂等。重放先重新鉴权再返回当前档案，不能以旧确认操作新版本。读写审计不含业务正文，事务失败不留部分确认；同手机号不合并其他访客。历史目录标题仅为记录来源，不构成有效医学推荐或正式服务/合同确认。回访接口见下节。

## M5 第二批站内回访实际契约

启动迁移门槛012。员工根路径 `/api/stores/{store}` 使用有效Bearer及 customer_read，写入另需 customer_manage。访客根路径 `/api/threads/{thread}/appointments/{appointment}` 使用原访客自有Cookie，POST另需当前CSRF。所有命令继承 request_key(UUID)/accepted=true，禁止多余字段；服务端生成版本、确认方式、确认时间与请求证据，不接受客户端身份/授权字段。

| 方法与路径 | 实际契约 |
| --- | --- |
| GET 员工 /followups | state可选 awaiting_confirmation/scheduled/completed/declined/cancelled；limit默认25/最大100，offset最大10000；items/total/counts（counts为门店全状态聚合） |
| GET 员工 /followup-cases | 同样分页；当前意向已获本人确认的候选，items/total；name为原申请称呼、phone_masked；创建时仍校验暂停/已有计划/有效证据 |
| POST 员工 /followups | case_id、expected_case_version、带时区 due_at（未来90天内）、message 1–300且非空白；来源当前已确认，仅提出awaiting_confirmation；200 |
| GET 员工 /followups/{task} | 任务及完整门店内部历史、来源版本和掩码号码；读取审计 |
| POST 员工 /followups/{task}/actions | expected_version、action=note/cancel、note 1–500且非空白；note追加内部记录，cancel只允许未终结计划；200 |
| GET 访客 /followups | 此预约自有任务最近20项，items；无计划为空数组，越权404 |
| POST 访客 /followups/{task}/response | expected_version、snapshot_hash（64位hex）、action=accept/reject/feedback/cancel/resume、confirmation_text；feedback另需 result=resolved/need_help，feedback可选0–500；其他动作不得携带result/feedback；200 |

任务DTO：id/case_id/case_version/source_current/version/state/due_at/message/snapshot_hash/opted_out/simulated/channel=in_app/history。员工另有来源意向的name及phone_masked。history为版本/kind/actor_kind/recorded_at/text/result/feedback/confirmation_text；客户服务端排除内部note事件和员工备注正文，不能通过UI切换读取。计划说明与时间不可变；版本每次操作递增，确认绑定当前版本及计划摘要。

固定客户文案：accept“同意本次站内回访计划”；reject“拒绝回访并暂停这份档案的邀请”；cancel“取消回访并暂停这份档案的邀请”；feedback“确认提交本次回访反馈”；resume“恢复这份档案的站内回访邀请”。只有当前awaiting_confirmation能accept/reject，accept还复核来源/证据/创建顾问权限与未过期时间。scheduled能feedback/cancel，反馈后completed仅表示已保存；客户reject/cancel置opted_out，阻断该档案新邀请。只有原客户在declined/cancelled且opted_out时resume清除暂停，不改变旧终态。员工取消不等同客户退订，内部note不改变客户状态。

缺明确确认或无效计划422，版本/摘要/来源变化、过期、暂停、已有计划或同键异内容409，证据不可用404，越权403或安全404。拒绝/取消/恢复不因项目撤回而剥夺客户选择。新键写入原子保存状态、加密事件、HMAC、staff_button/customer_button、服务端时间、请求证据与审计；未知结果仅原键核实，重放重新授权并返回当前状态。没有联系号码出口、通知发送或模型调用。

## 2026-10-12 演示咨询元数据

咨询result新增simulated布尔值、disclosure字符串，公开evidence新增review_scope（standard/demo_education）；旧记录可缺字段，旧来源空scope按standard兼容。正文不再重复“模拟机构资料”，页面在咨询面板和项目卡片集中披露虚构场景。KnowledgeDetails新增review_scope，demo_education必须public、有非合成公开来源URL及日期；医疗category不改成operational。只在显式非生产模拟配置允许独立模拟科普复核，生产启动拒绝；个人医疗正文仍本地转接。消息/预约/客户确认/回访契约不变。

## 共情结果兼容扩展（2026-10-12）

咨询结果 intent 增加 support；可选 public_answer:string 是已经验证的公开事实部分，完整 answer 仍为客户展示文字。support-only 和临床/危机固定回应 public_answer 为空；历史旧结果缺字段时兼容读取，Gateway 再次过滤与检查来源。纯情绪消息 exportable=false，混合消息只允许规范化公开投影；这不是原正文可外发授权。无新增迁移、员工角色或业务写入。短期 crisis_pending 为本地流程布尔值，不是心理诊断/长期客户标签。见 [共情设计](empathy-design.md)。

## 沙箱协议与对外兼容（2026-10-12）

客户消息接口不接受运行镜像、工具、Shell、SQL或执行参数。内部v1 SandboxJob仅固定运行/message/thread引用、模拟范围布尔与10–60秒超时，无真实lease或凭据；有界JSON白名单绑定父actor，最终Completion不能直接写业务。消息结果仍使用既有结构；run trace新增sandbox/sandbox_rpc_denied，health/ready增加agent_runtime并检查隔离依赖。没有数据库迁移或客户权限变更，详见 [运行时沙箱](runtime-sandbox.md)。
