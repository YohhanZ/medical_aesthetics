# 云演示部署与恢复

## 本批范围

用户确认腾讯云43.142.39.108、ubuntu、4核4 GB/3 Mbps，演示/面试用途，无域名；2026-10-13进一步要求先暂停原项目Docker容器再部署本项目。只暂停mapmost-rag的6个已核实容器，不停止Docker服务、删除镜像/卷、修改原项目配置或清理缓存。原项目暂停期间8080将不可用。镜像与部署配置验证完成后才切换；新存储启动失败会请求恢复原容器，恢复健康须另验。

独立目录 `/home/ubuntu/medical-aesthetics-demo`，Compose项目 `medical-aesthetics-demo`；独立网络/5个命名卷/随机数据库与存储账号。PostgreSQL/Neo4j/Milvus/MinIO/etcd不发布宿主端口；NGINX只发布80/443，客户 `/`、机构后台 `/admin/#/login`，双端均通过同源 `/api`。原项目数据与现有本地客户业务记录不迁移；重新通过独立模拟审核/outbox导入项目知识。

## 实现文件与构建

- backend/deployment/Dockerfile、requirements.lock：API固定Linux运行依赖，不装pytest/Ruff/mypy。先构建既有sandbox/Dockerfile再构建API；API复用相同Python3.12/已实测运行依赖，单独加入Docker CLI/API/Milvus客户端依赖，LABEL不是worker角色。pymilvus在Linux必需milvus-lite/tqdm包，仅满足SDK依赖，应用仍用鉴权Standalone Milvus；没有切换Lite数据库。
- backend/deployment/bootstrap.py：显式development+simulation才执行012迁移、模拟种子、独立审核与版本导入；只初始化云演示集合，不创建测试集合。原25条医学待审保留，demo_education不能成为生产医学批准。
- backend/deployment/worker.py：持久outbox投影循环，有限等待与安全类型日志；模型仍经Gateway/精确摘要出口授权；不外发业务记录。
- backend/deployment/smoke.py：HTTPS端到端合成验收，本地操作员使用忽略的bootstrap凭据文件，输出仅模式/检查结果及合成run_id。
- deploy/cloud-demo/compose.yml、web.Dockerfile、nginx.conf、acme.conf：完整存储/API/Worker/双前端/TLS配置。frontend/admin/vite.config.ts仅cloud-demo模式采用/admin/，本地开发和默认构建原路径保留。
- deploy/cloud-demo/configure.py：拒绝覆盖目标目录，独立生成密钥/密码，仅从项目.env继承模型配置与既有出口摘要；配置只在被Git忽略的runtime，不进入镜像或Git。API没有Milvus写/管理员token；Worker无管理员token；bootstrap专用管理员token不挂给API/沙箱。
- deploy/cloud-demo/switch-project.sh、restore-previous.sh：保存原容器ID和restart policy，只停止特定6个容器；恢复前重新验证ID，保留全部卷与镜像。
- deploy/cloud-demo/renew-tls.sh：项目专用、flock互斥、仅续期本IP证书、NGINX校验后热加载。

示例构建（工程根目录，运行部署前按私有配置实际准备）：

```powershell
$env:VITE_CUSTOMER_URL = "/"
npm --prefix frontend run build --workspace @ma/customer
npm --prefix frontend run build --workspace @ma/admin -- --mode cloud-demo
Remove-Item Env:VITE_CUSTOMER_URL
docker build -f backend/sandbox/Dockerfile -t medical-consultation-sandbox:local -t medical-consultation-sandbox:demo-20261013-r2 backend
docker build -f backend/deployment/Dockerfile -t medical-aesthetics-api:demo-20261013-r2 backend
docker build -f deploy/cloud-demo/web.Dockerfile -t medical-aesthetics-web:demo-20261013-r2 .
```



## 内存与可信边界

PG160 MiB、Neo4j576、etcd96、MinIO128、Milvus896、API320、Worker320、Web48，服务上限合计2544 MiB；单次沙箱512 MiB，咨询准入1、单轮45秒、CPU1，峰值配置总上限约3056 MiB（不含宿主/临时bootstrap或Certbot）。临时bootstrap512 MiB在API/Worker启动前运行；TLS128 MiB短暂运行。禁用容器额外swap，不更改宿主4 GiB swap。若OOM/健康失败，不视为可用部署。

[Milvus官方v2.5要求](https://milvus.io/docs/v2.5.x/prerequisite-docker.md)Standalone至少8 GB；本4 GB受限单人合成演示必须实测，不能据此声称符合最低配置、生产稳定或高并发。实际内存/RSS、OOM及响应时间待云验收记录。

API是受信任控制器，非rootUID65532通过Docker socket组控制宿主daemon，具有很高信任权限；这不是daemon最小权限或宿主整体沙箱。模型执行容器不拿socket、网络、凭据或挂载，执行固定LangGraph，白名单Broker重新校验范围与证据。生产需独立受控启动器节点/最小daemon权限，见runtime-sandbox.md。

## IP HTTPS与密钥审核记录

[Let's Encrypt官方说明](https://letsencrypt.org/2026/03/11/shorter-certs-certbot)支持IP证书，需Certbot5.4+ webroot、shortlived约6天证书和自动续期。固定官方Certbot5.4.0镜像；先测试签发，正式证书另用43.142.39.108 cert-name，不让NGINX加载测试证书。证书续期计划须安装并实测，不能仅因获得证书声称续期完成。证书公钥/站点元数据会进入正常CA流程，不发送模型或业务信息给CA。

上传包含本地.env派生模型API密钥的包曾被自动审批拒绝，理由是未明确授权凭据出站、包内容未核验。随后先逐文件验证并上传不含LLM_API_KEY及其值的配置，其他准备继续；用户明确选择“允许传输，用于本次云端部署”后，严格SSH经stdin将该模型密钥写入本项目三个mode600配置，不输出、不在命令行或Git。新生成DB/存储/加密凭据独立于原项目，私有配置不得公开。

## 截至准备阶段实际结果

- 双前端TypeScript/Vite构建通过，cloud-demo管理员资源前缀/admin/。68项Vitest通过（客户37、机构31）。首次普通Windows沙箱realpath EPERM，授权构建重试成功。
- API首次镜像失败：镜像源没有返回pydantic-core；复用同Python/固定沙箱基础依赖后发现Windows依赖闭包遗漏Linux-only milvus-lite，补齐固定包后pip check成功。一次命令工作目录错误未修改依赖锁，该轮构建未成功；按正确路径补齐后最终构建成功。
- API离线无网络、只读镜像实际import fastapi/pymilvus/app.api通过；12迁移存在、无/app/.env；Docker CLI27.5.1可运行。Ruff通过，mypy四个相关源文件通过。
- 云端模型密钥模式600安装成功；Compose config --quiet通过。HTTP80公网/deployment-check200；测试/正式IP证书签发均成功，提示到期2026-10-19。
- 镜像压缩包：TLS/Web110,928,089字节、存储1,408,362,216、API/沙箱205,939,260；本地SHA256已记录，云导入前校验。原始包只含镜像、不含业务卷/配置。现有原项目6容器仍healthy，尚未切换、初始化、验证完整聊天或公布已部署成功。

## 交付后的操作（完成后补实测）

云目录中`docker compose --env-file runtime/compose.env -f compose.yml ps`检查本项目；`bash restore-previous.sh`仅恢复ID一致的原项目，随后核实各容器healthy与8080。不能同时跑两套再声称4 GB足够。任何`down -v`、全局Docker prune或删除原项目models均不在本批范围。Git提交/推送、CI/CD、跨实例限流/追踪、真实SMS及真实医学批准不因演示部署自动完成。


镜像包云端SHA256全部OK，存储/API/沙箱加载成功、DockerCLI27.5.1和NGINX正式证书校验成功。导入后磁盘约6.7 GiB可用，随后仅删除本次上传并校验的临时压缩包；不清理原项目缓存/镜像/卷。首轮切换在停止前被Ubuntu无法遍历Certbot root700证书目录拦住，原项目仍healthy；改为NGINX容器按自身权限校验证书，无权限放宽。重新校验成功后保存原6容器ID/restart policy，开始暂停并启动新存储；最终健康及恢复结论待后续实测。


## 云运行与质量修正进展

原6容器已暂停且restart policy均仍unless-stopped；无需修改原配置。新5个存储healthy、无OOM，暂停后宿主内存available约2936 MiB。012及全部364条模拟版本初始化通过；按当前版本过滤实际发布308，Milvus/Neo4j/ready回执均308，当前待投影0、未完成outbox0；31被后续版本替代的历史记录保持不激活，25原医学资料draft。不能把339个导入发布请求或历史版本计为339个可检索向量。

HTTPS443服务器本地客户/后台200、SSL验证0，但公网TCP443超时，UFW inactive；公网80连通、旧8080收到ConnectionRefused，因原服务已停。没有更改云安全组；新web增加8080:443映射，正式HTTPS8080客户/后台/公开门店API均200。只允许精确HTTPSIP与HTTPSIP:8080来源；后台品牌链接改同源/，HTTP80重定向HTTPS8080。前端r2镜像SHA256 4a7c51364567269a0c209dde29dea4ad4449c8f8519c1134894723206d6e3fe2。

正式IP证书renew --dry-run模拟续期通过，期间Certbot随机等待约165秒，不是调用挂起；已安装ubuntu本项目每6小时cron，保留其他cron任务，实际NGINX配置测试/热加载成功。修正无须交互的Docker run/exec stdin，避免SSH bash -s后续只读命令被CLI消耗。首次当前版本统计SQL错误使用不存在knowledge表，已按真实扁平knowledge_version/tenant/store/key改正，后续统计通过。

两次端到端合成预算题发生evidence_fallback，均由answer_fact_unsupported引起，生成耗时约5.4/5.9秒而非OOM或模型断连。模型复述了问题中的300预算数字，而报价证据为298；不将预算数字当机构证据。调整系统提示避免复述客户预算/年龄/次数数字，仅报证据数字；unsupported fact额外允许一次预算内重试，第二次失败继续拒绝不安全草稿。新增真实隔离PG两场景验证纠正成功/两次均失败，证明只重试一次、999假报价不进回复/持久助手记录。35项相关Agent/Gateway回归通过55.45秒，Ruff与mypy42源文件通过；新API与固定沙箱均重建为demo-20261013-r2，部署前等待当前咨询run完成，保留云端已存在的真实用户演示申请与会话。

浏览器的通用getTab/create入口曾两次超时，改用已选browser.tabs.get+playwright.domSnapshot取得实际完整页面：可见公开项目卡、图片说明、回答依据、真实多轮回答/比较及用户自行提交的待门店确认申请。未修改该用户会话或申请，不将其算合成验收数据，不保存该业务正文到本文；仅DOM确认，不宣称完成截图/手机视觉验收。此云端tab已标记保留。


## 最终验收结果（2026-10-13）

演示部署成功，客户入口https://43.142.39.108:8080/#consultation，机构后台https://43.142.39.108:8080/admin/#/login。HTTP80重定向HTTPS8080；公网443仍未放行，未修改云安全组。模型、认证、门店范围、客户确认、幂等、医学边界、独立审核和Docker沙箱全部保留。原6容器exited，ID/镜像/卷/原配置和unless-stopped重启策略保留；新存储/API健康，Worker完成投影、Web可访问，8个新运行容器无OOM/重启。没有调用恢复脚本实际切回原项目，也没有重启服务器。

最终公网HTTPS合成验收全通过：HTML/JS/CSS/项目图片与详情、Secure Cookie、30个有效项目目录；问候fixed→300元预算问题generated（引用演示价298）→‘它一般需要多久’generated并保留补水主题→共情暂停fixed→预约意愿handoff且未提交。5轮均记录sandbox/completed，消息重放与10条历史一致。个人医疗问题另转人工且connected=false。模拟验证码/本人明确确认/持久申请、同键重放、后台demo-operator确认及客户读取同步、知识作者无预约权限、跨门店/访客拒绝、退出后拒绝全通过。仅确认脚本自己创建的‘合成云端验收’申请，不处理用户在页面中另行提交的申请。第二轮诊断与最终测试没有将安全降级伪装成模型成功；只有修正后generated才通过对应断言。验收脚本原将预约意愿错误预期fixed，已按现有visit_request/handoff协议修正并断言未写入/未接通。

最终报告为忽略的runtime/cloud-deployment-acceptance.json，仅保存检查结果和合成run_id，不保存用户真实申请、密码、模型key或正文。5轮run_id：bbd0326c-bbac-4438-8c97-08e0916632a5、1d4e8ee6-1d17-4906-b167-16bd9f54b95a、efabf040-448a-407f-9f01-e54f80fa5018、7297f277-479b-4b3d-b0ac-f9541b1c30b1、cdcf4042-5c25-449d-9429-a149d6f06423。最终快照：宿主可用1937 MiB、已用1472 MiB，swap约53 MiB已用；磁盘约7.3 GiB可用/81%。API160 MiB、Worker96、Neo4j515、Milvus181，其余较小；不存在遗留运行沙箱。只是单用户合成实测，不能代替符合Milvus最低规格或生产/高并发稳定性证明。

Certbot测试和正式签发、renew --dry-run均成功；cron为active/enabled，每6小时以绝对/bin/bash运行本项目续期脚本，其他cron保留。原项目恢复后新web停止时续期脚本直接退出，不继续对已暂停站点验证；新web运行后正常renew+nginx-t+reload。私有脚本模式700、云配置600；本机新云配置两个目录也限制到用户/SYSTEM/Administrators。所有凭据/报告Git check-ignore通过。API/Sandbox r2镜像分别e9d0fff8652ef059c3d9f6e7ddf5455d5df8b756cea2745cb2a38a8fcbb05454、35192224f93953405b7e6586f5b60073f092e7c93bf4beb4b19b49dabcb3a453；代码修正采用deployment/update.Dockerfile复用本批已验证Linux依赖，依赖改变需完整Dockerfile重建。

### 本地复验与恢复

```powershell
# 工程根目录：仅合成写入自己的新会话/预约，不发送真实短信
.venv/Scripts/python.exe -X utf8 backend/deployment/smoke.py --credential-file runtime/cloud-demo-config/bootstrap.env
# backend目录：仅ma_m1_test隔离库
..\.venv/Scripts/python.exe -X utf8 -m scripts.verify tests/test_consultation_agent.py tests/test_consultation_gateway.py
```

后台接待用demo-operator，客户/回访用demo-consultant，知识分别demo-author与demo-reviewer；独立随机密码在本机runtime/cloud-demo-config/demo-access.txt和服务器runtime/demo-access.txt，仅用户查看，不能提交Git或分享公开资料。无需把密码/密钥发到聊天中。

服务器ubuntu控制台恢复原项目：`cd /home/ubuntu/medical-aesthetics-demo && bash restore-previous.sh`，随后`docker ps`及原8080验证healthy；恢复脚本先核对原6个ID，停止本医美服务后才启动原容器，不能同时运行两套并声称4 GB有余量。未执行实际恢复演练，不能声称恢复实测成功。服务部署运行不依赖本机开发服务；专用SSH授权到期不影响已运行服务与本机cron。

### 后续里程碑和限制

下一批为GitHub提交/更新与CI/CD、独立备份恢复演练和运行监测；当前没有Git提交/推送、CI流水线、长期云运行/重启演练、真实SMS、真实机构/医学审批或高并发验收。外部LangSmith适配器、跨会话长期记忆仍按既有未实现状态；本次是显式development/simulation的HTTPS云演示，不能改名为真实客户医疗生产上线。
