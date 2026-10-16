# AI 营销创作中心

后台入口：`http://127.0.0.1:5175/#/marketing`。支持图文海报、5 秒无声宣传短片和作品库。

## 当前功能

- 无密钥也能使用：品牌介绍／日常护理／到店邀请模板、编辑文案、画面描述、三种版式、Canvas 海报预览、PNG 海报及 TXT 文案下载。示例图片复用项目已有 AI 场景素材，页面和导出图片都标注“示例排版／非实时生成”。不伪造生成任务。
- 配置后：Kolors 真实生图、万相真实文生视频、持久任务、状态轮询、作品分页、排队取消、失败原任务核实、认证素材预览及下载。
- 文案为本地模板草稿及已发布项目资料，不额外调用文字模型。海报中文、品牌名和说明独立排版，编辑无需重新生图。任务保存品牌、文案与标题；本地排版导出暂不回写为新的版本。
- 万相固定 `wan2.2-t2v-plus`、480P、5 秒、开启 AI 水印；当前不含配音、烧录字幕或直发社交平台。文案单独导出供后期使用。
- 图文海报支持 3:4、1:1、16:9。Kolors 使用支持的竖版／方形规格，横版海报裁剪方形配图。视频比例为 9:16、1:1、16:9。

## 配置

在 **backend/.env** 配置，密钥不放前端或 Git。不使用 `LLM_API_KEY` 作为隐式回退。

```dotenv
MA_MARKETING_IMAGE_API_KEY=你的硅基流动APIKey
MA_MARKETING_VIDEO_API_KEY=你的阿里云百炼北京地域APIKey
MA_MARKETING_VIDEO_ENABLED=false
MA_MARKETING_DAILY_LIMIT=10
MA_MARKETING_MEDIA_ROOT=runtime/marketing
MA_MARKETING_MAX_ASSET_MB=24
```

生图模型为 `Kwai-Kolors/Kolors`。视频需确认模型权限、免费额度及供应商“免费额度用完即停”设置后，再显式设置 `MA_MARKETING_VIDEO_ENABLED=true`。每日次数是当前门店的应用限额，不是供应商免费额度查询，不能代替供应商止付设置。已有百炼 Key 如具备对应权限，可以显式填入视频配置，无需另建阿里云账号。

配置后重启 API 与营销 worker。独立终端启动 worker：

```powershell
cd D:\medical_aesthetics\backend
..\.venv\Scripts\python.exe -m app.migrate
..\.venv\Scripts\python.exe -m app.marketing_worker
```

API 沿用 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8001`；后台前端在 `frontend/` 下运行 `npm run dev --workspace @ma/admin`。本次开发已启动本机进程。

真实调用需员工登录，持有当前门店 `knowledge_author` 权限。演示种子中的 `demo-author`、`demo-reviewer` 具备此权限；平台管理员不自动获得门店内容权限。纯“界面演练”模式不调用生成 API，示例版式不写入作品库。

## 实现与任务机制

- `backend/migrations/014_marketing.sql`：任务、幂等键、来源项目、品牌文案、供应商任务 ID、租约和素材元数据。
- `backend/app/marketing.py`：权限、项目来源、每日配额、幂等创建、分页、取消、原任务核实、认证文件读取。
- `backend/app/marketing_worker.py`：独立单并发 worker，只将画面描述发送给供应商，不读取客户资料、聊天或长期记忆。任务保存 PostgreSQL，文件转存媒体目录。
- `frontend/admin/src/views/MarketingPage.vue`：创作区、预览、进度和作品库。
- `frontend/admin/src/services/poster.ts`：Canvas 排版与导出。

状态：`queued → submitting → running → succeeded`；其他状态为 `failed / unknown / cancelled`。提交 API 快速返回，页面定时刷新；worker 执行前重查员工、门店和创作权限。

同门店同请求键与正文只创建一个任务。响应丢失时前端保留原请求核实；生成 POST 超时或 worker 在提交阶段异常退出，不自动重新生成，防止重复扣费。有供应商任务 ID 后只重试查询／素材转存。“核实原任务”恢复已知任务，不重新生成。

素材下载仅允许 HTTPS、配置的供应商公共 CDN 域名及公共地址，不跟随跳转；匿名下载不携带模型凭据。检查大小及图片／MP4 头；域名配置参见 `.env.example`，若使用新 CDN，需核实后扩展。原始签名 URL 和文件路径不返回前端。读取素材必须重新经过员工及门店授权，前端以 Bearer 请求 Blob，离开页面时释放 URL。作品不依赖浏览器存储，重新登录后从服务器读取。

## 部署

只更新本机，未部署云端。本机已先备份 `ma_m1` 再应用迁移 014。部署前备份业务库并执行迁移，API 启动检查此迁移。

Compose 模板新增 `marketing-worker`，与 API 使用同一新镜像。共享 `marketing` named volume：worker 可写，API 只读；Dockerfile 初始化目录所属 UID/GID 为 65532。发布覆盖文件必须同时给 `api`、`worker`、**`marketing-worker`** 指定同一新版本，不能让新 worker 使用旧标签。

API 与营销 worker 都需上述配置。`configure.py` 支持为新环境生成配置，但不要为了更新既有部署重新运行它，以免轮换数据库及业务密钥；既有环境在受限配置文件中增补项目即可。媒体目录随卷持久化。

这是演示规模的存储实现，默认单文件上限 24 MB；长期运营需添加生命周期清理、容量监控或迁移对象存储。网页刷新不自动重新提交生成。

## 供应商文档与验证

- [硅基流动图片生成 API](https://api-docs.siliconflow.cn/docs/api/images-generations-post)
- [万相 2.1–2.6 文生视频 API](https://help.aliyun.com/zh/model-studio/legacy-wan-text-to-video-api-reference)
- [百炼免费额度与用完即停](https://help.aliyun.com/zh/model-studio/new-free-quota)

未提供供应商密钥，真实生成尚未验收。自动测试使用独立测试库、模拟 HTTP 和素材，不消耗真实额度。

本机验证：后台前端 34 项、营销后端 11 项测试通过；额外登录门槛回归 5 项通过。构建、Ruff、mypy 通过。浏览器实测模板编辑、竖版／横版 PNG 预览、示例海报下载和图片导出检查、手机单列布局，以及未配置视频时禁用真实生成。
