# 咨询模型配置

`LLM_MODEL` 支持 `qwen3.7-plus` 和 `qwen3.8-27b`，通过配置显式选择。未配置时保留原来的 `qwen3.7-plus` 默认值；`LLM_*` 优先于旧版 `MA_*` 别名。

```dotenv
LLM_MODEL=qwen3.8-27b
LLM_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_API_KEY=你的对应地域密钥
```

本次演示选择 `qwen3.8-27b`，依据是用户确认其账号仍有该模型的免费额度；项目不保证每个账号都有免费额度，不自动关闭供应商“免费额度用完即停”。只读模型列表可见不代表实际推理额度可用，需以一次合成请求验证。

两个模型沿用公开问题投影、联系方式移除、当前证据授权、JSON 段落输出、证据引用及数字校验。请求为非流式、`enable_thinking=false`、`response_format={"type":"json_object"}`，保留原有超时与重试上限。模型不接收预约表单、联系人或客户长期记忆原文。适配不会改为未校验文本输出。

仅切换咨询生成模型；向量化仍使用 `text-embedding-v4`、256 维，Milvus 集合及既有知识数据不需重建。沙箱内部不持有模型凭据或联网能力，由宿主可信 Broker 处理调用。

既有云部署需要先发布支持该名称的新 API 镜像，再备份并更新 `runtime/api.env`、`runtime/worker.env` 的 `LLM_MODEL`，保留其他密钥与设置。使用 `compose.yml` 和 `compose.release.yml` 一起重建相关服务；不得重新运行初始化脚本覆盖数据库和业务密钥。API 重建后平滑重载 nginx 并核验公开 API，防止上游地址缓存旧容器 IP。

当供应商返回 `AllocationQuota.FreeTierOnly`，应用保留资料摘录降级，而不静默切换付费模型。诊断只输出 HTTP 状态和错误分类，不输出密钥、用户原始问题或供应商完整错误响应。

合同测试覆盖两个模型的环境变量别名、请求中的模型名称、非思考 JSON 模式、公开历史与证据、联系方式移除，以及拒绝未验证的模型名称；模型切换不会绕过既有授权和回答校验。

供应商参数：[OpenAI 兼容接口](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)、[思考模式](https://help.aliyun.com/zh/model-studio/deep-thinking)、[免费额度相关错误](https://help.aliyun.com/zh/model-studio/error-code)。真实模型可用性以本次发布及调用验收记录为准。
