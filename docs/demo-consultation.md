# 具体场景的咨询演示

2026-10-12 用户要求补齐缺失机构资料，模拟完整咨询场景；本批替换“只有目录、缺说明”的占位体验。数据是虚构机构演示，不能表示美丽田园实际供给或真实医学批准。

## 数据与回答

`backend/data/demo_consultation.json` 共70条：14个生活护理/沟通方向、16个医美科普与接待方向、24条运营问答、6组医学项目比较、10条内部顾问策略。30个项目沿用原项目key，新内容产生新的知识版本，不修改历史版本。补水、清洁、舒缓、眼周、手部、背部、芳香等包含具体内容、时长、虚构单次价；公开问答包含预算、首次到店、带妆、办卡、门店、隐私、预约确认和回访。内部策略不进入对客证据或模型载荷，本轮自然表达由公开事实及受控提示实现。

例如补水演示为60分钟、298元，包含卸妆与温和清洁、外用保湿精华、保湿面膜、保湿收尾和体验沟通；清洁演示50分钟、258元，侧重卸妆和分区清洁。价格与既有演示运营包的共同项目保持一致。所有费用是场景设定，没有真实售卖或治疗授权；不编造剂量、发数、注射点位、国内注册号或医生执业证。

医美普通科普依据公开原文组织短摘要，机构服务和价目单则为虚构。来源包括[Lumenis IPL](https://lumenis.com/aesthetics/products/m22/)、[AAD射频与超声说明](https://www.aad.org/public/cosmetic/younger-looking/firm-sagging-skin)、[FDA填充与肉毒毒素说明](https://www.fda.gov/consumers/consumer-updates/dermal-filler-dos-and-donts-wrinkles-lips-and-more)、[FDA微针](https://www.fda.gov/medical-devices/aesthetic-cosmetic-devices/microneedling-devices)、[FDA射频微针安全信息](https://www.fda.gov/medical-devices/safety-communications/potential-risks-certain-uses-radiofrequency-rf-microneedling-fda-safety-communication)、[FDA医用激光](https://www.fda.gov/radiation-emitting-products/surgical-and-therapeutic-products/medical-lasers)、[AAD脱毛咨询准备](https://www.aad.org/public/cosmetic/hair-removal/laser-hair-removal-preparation)、[FDA非侵入体形技术](https://www.fda.gov/medical-devices/aesthetic-cosmetic-devices/non-invasive-body-contouring-technologies)、[北京卫健委水光/透明质酸科普](https://wjw.beijing.gov.cn/jyt2023/jytjksh/202604/t20260409_4577208.html)。访问日期2026-10-12。国外资料不能表示中国注册、说明书用途或门店实际设备；厂商信息不能代替独立临床结论。

回答先讲定义、步骤、区别或费用，最多两个简短段落和一个相关追问。资料有具体内容时不再泛称“只是了解目录”；模拟标识集中在咨询面板、项目卡片和依据。API另返回simulated/disclosure，不把虚构信息伪装真实。既有历史回复不改写，新版本使旧证据失效；演示请新建对话。

## 模拟科普复核与生产边界

新增显式 `MA_DEMO_MEDICAL_EDUCATION=true` 仅在非生产且 `MA_ALLOW_SIMULATED_DATA=true` 时允许。医学条目必须单独声明 `KnowledgeDetails.review_scope=demo_education`，public audience、真实公开来源URL与日期齐全，知识/审核/租户/门店均为模拟，作者和审核账号不同。复核理由持久加“模拟公开科普演练复核，不代表真实医学批准”；没有虚构证号或真实资质状态。原25条无此范围的医学待审任务/摘要不批准、不发布。

审核、发布、worker投影和对客证据都校验此范围；关闭开关立即不再允许相关证据，过期/撤回/版本不一致仍拒绝。生产启用该开关必须启动失败，真实医学批准路径没有实现。个人病史、症状、孕期、适合性及治疗选择仍本地转专业，不因演示开关向模型发送。一般风险科普与“我/朋友做完后疼痛”等个体问题分开识别。

所有新版本经过现有门店授权、独立开发账号复核、outbox、Milvus真实向量与Neo4j投影，PostgreSQL仍为权威。知识出口按本次用户授权增加当前70条精确摘要，未来修改不自动授权；模型名称、URL、密钥及客户业务配置不改。

## 本地复现

backend目录执行 `python -m scripts.authorize_knowledge_exports --record-user-authorization`，显式开启上面的本地模拟科普设置后，`python -m app.knowledge_import` 和 `python -m app.knowledge_worker --max-events 500`。不得用于真实客户医疗上线。重跑同一数据不新建版本、不刷新有效期或复活撤回内容。

启动API并在5173咨询页面新建对话。尝试“补水包含什么→那多少钱→和清洁区别→先不预约”；或“光子是什么→和热玛吉区别→只咨询收费吗”。`python -m scripts.chat_quality_check --demo` 用12个独立合成访客测试46轮，另存runtime/demo-chat-report.json；不覆盖上一批聊天捕获，不读取已有客户记录，不自动提交预约。测试与实际运行结果在完成后追加记录。

## 实际验收结果

70条导入及真实投影完成，团队资料随后与后台演示包统一并新增1版本；原25条医学draft保留。当前PostgreSQL310个published版本、Milvus310个主集合版本向量、Neo4j310个版本节点，包含历史被替代版本，不等于310条当前可见证据；outbox为空，投影均ready。

核心完整后端225项通过（961.20s）；随后原文候选/数字提示/脱毛完整别名及元数据兼容等最终20项专项通过（20.35s），不相加冒充全套226。Ruff74文件/类型34源文件通过，前端客户37+后台31项通过，客户TypeScript与构建通过。真实Qwen最终12组46轮HTTP200与同键重放/本人历史通过，39生成、1数字校验失败的有效证据降级、2固定、4转接；19个定向检查通过，中位6.39s/最大7.89s，不是临床或容量验收。原始最终捕获runtime/demo-chat-final-46.json，逐轮实际文本runtime/demo-chat-transcript.md。

最终浏览器额外4轮显示具体补水步骤/298元、补水与水光区别、免费咨询选择。第三轮遗漏项目起价而只说咨询费，现场补保留末句价格引用及“项目价与咨询费分开”提示，第四轮正确同时回答补水体验298元/常规398元、水光演示起价1280元/咨询0元40分钟。不修改历史回复；最后20项再次通过，上面的完整46轮在这次末句引用调整前捕获，不宣称是最后提示的全量重测。截图runtime/demo-consultation-browser.png及demo-consultation-prices-browser.png均目视检查，额外4轮不计入46轮。临时标签已关闭，恢复测试前对话4选择，原客户与后台标签保留，没有预约或回访业务提交。

最新API8001进程27064/session56018，migration012。机构与医学资料仍仅支持演示；真实资质/注册/医学批准、实际排班/收费、供应商、跨设备身份与生产运维仍须完成。下一批继续语义覆盖及M6备份恢复/监控，不云部署。
