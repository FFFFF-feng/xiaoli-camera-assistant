# 参考图驱动的 AI 构图预演（第一版接入框架）

当前状态：**接口与页面已实现，服务默认关闭，尚未选择或接通真实图片编辑提供商。** 本次测试只用本地替身，没有发起付费生成，也没有更新服务器。不能把接口测试通过当作保真效果已验收。

## 它做什么

用户完成构图分析后，在结果页看到“AI 构图预演”。管理员启用服务后，用户另行同意照片发送对象和费用，再手动点击生成。一次请求使用一张明确图号对应的原始参考图，以及当前构图目标、动作、辨识特征、画幅和目标位置框。不会把抽象多边形当作物体外形输入。

原图是样貌依据，位置框只表达构图意图。提示要求保留同一主体身份、数量、颜色、纹理、可见部件、姿态和持物；不能搬动固定建筑、拆散树木或凭空复制物体。新机位无法验证的内容只允许保守近似。

页面保留原图与结果对照，明确标为“AI 生成预演 · 未验证真实性”。没有自动视觉相似度评分，也不能承诺新视角可以实拍实现。普通原图裁切和拍摄建议完全独立，编辑失败不会覆盖原图。

## 接口协议

目前适配 **OpenAI Images Edits 形态**：后端 multipart `POST {base_url}/images/edits`，上传 `image` 文件、`model`、`prompt`、`n=1`、`size`、`quality`、`output_format=png`。仅接受返回的 `data[0].b64_json`，不访问提供商返回的网址。

这是协议适配，不是“任意视觉模型都能编辑图片”。Chat Completions 的视觉识别接口不能直接代替它。参考 [OpenAI 图片编辑接口](https://developers.openai.com/api/reference/resources/images/methods/edit) 与 [图片生成/编辑指南](https://developers.openai.com/api/docs/guides/image-generation)。`input_fidelity` 并非所有模型都支持，须按所选模型文档配置，不能一律发送 `high`。

受保护的应用接口：

- `GET /api/v1/composition-preview/config`：返回是否可用、提供商主机名、模型、配置指纹和费用说明，不返回密钥。
- `POST /api/v1/composition-preview`：表单包含 `file`、`plan`、`consent=true`、`configuration_id`、UUID `request_id`。
- 成功：返回 `image_data_url`、`ai_generated=true`、`semantic_verified=false`、参考图号和警告。
- 未启用返回503；不同意/坏图片或方案返回422；配置变化或编号复用冲突返回409；限流返回429；提供商失败返回脱敏502。

`plan` 使用严格字段：`goal`、`actions`、`preserve_features`、`aspect`、`reference_photo_id`、`layout`。`layout` 最多6个合法的目标框，不携带原来的抽象线条。后端不接受客户端指定提供商地址或模型，避免任意转发。

## 后续如何启用

先确定服务支持上述协议和图片编辑模型，再在根目录私有 `.env` 中填写；不要把密钥发到聊天、前端、知识库或 GitHub。

```dotenv
CAMERA_IMAGE_EDIT_ENABLED=false
CAMERA_IMAGE_EDIT_BASE_URL=
CAMERA_IMAGE_EDIT_API_KEY=
CAMERA_IMAGE_EDIT_MODEL=
CAMERA_IMAGE_EDIT_TIMEOUT_SECONDS=180
CAMERA_IMAGE_EDIT_INPUT_FIDELITY=omit
CAMERA_IMAGE_EDIT_QUALITY=medium
```

确认服务、模型、预算与隐私条款后才把 `ENABLED` 改为 `true`。Base URL 是 API 根地址，不包含 `/images/edits` 后缀。例如选择官方服务时 API 根地址为 `https://api.openai.com/v1`；模型名称按实际已开通的编辑模型填写，不自动指定“最新模型”。

图片编辑使用独立密钥，**不自动复用** `CAMERA_AI_API_KEY`、`OPENAI_API_KEY` 或智谱实验配置。默认 `omit` 不发送输入保真选项；所选模型支持并需要高保真参数时，再显式填写 `high`。画幅明确时使用常见横/竖/方尺寸，没有布局依据时使用 `auto`。

双击 `启动项目.cmd` 会先检查可选编辑配置、构建当前前端，再按既有策略启动本项目服务。`--check` 仅检查配置/运行依赖，不调用编辑服务。正常演示模式不启用付费图片编辑。没有增加 Python 或 Node 依赖；`scripts/launch_apps.py` 继续转交新版启动器，端口归属、启动锁和旧构建拒绝策略保持不变。

## 费用、隐私和资源保护

- 每次分析**不会自动生成图片**。另行勾选、手动生成；重新生成可能再次计费。
- 配置指纹变化后拒绝旧授权，需刷新确认新的照片发送对象。
- 输入沿用上传字节限制，另限1600万像素；纠正 EXIF 方向、删除元数据，再以相同像素尺寸的 JPEG 副本发送（质量95），不发送原文件名。应用不永久保存上传图片；上传框架处理大文件时可能使用系统临时文件，请求结束后关闭。
- 输出仅接收有大小和像素上限的有效 PNG/JPEG/WebP，重新编码 PNG 后给前端。不执行 SVG/HTML，不追随提供商重定向，也不下载模型给出的 URL。
- 编辑单独限制一个并发任务；同一身份10分钟最多3次，全进程每小时最多20次。网页登录也沿用网站限流。此为学生项目保护默认值，不是商业计费系统。
- `(身份, request_id)` 加照片/方案指纹做进程内幂等。同编号同内容复用结果，不同内容拒绝；客户端断线后工作仍占用并发槽，不偷偷启动第二份。
- 最多保留8个任务/结果，完成后在后续请求中清理超过10分钟的记录。该内存结果缓存用于重复请求保护，不是历史图库；原图/结果不会写入本机历史或服务端文件。
- 超时、服务失败、拒绝、无效结果都不自动重试。停止等待不等于提供商停止计费。
- 缓存和限流都是**单进程**的；重启会清空，不能跨重启承诺去重。多 worker/多实例上线前，需改为共享任务与限流存储，并设计付费请求的持久幂等与恢复策略。

## 代码入口与验证

配置：`src/camera_assistant/image_edit_config.py`；编辑适配器：`services/image_edit.py`；应用接口：`image_preview_api.py`；结果页面：`mobile/src/components/CompositionPreview.vue`；接入测试：`tests/test_image_preview.py`。

已通过协议替身测试，覆盖独立凭据、EXIF方向/隐私、认证、单独同意、配置变化、坏图/方案、返回URL/SVG拒绝、服务错误脱敏、无自动重试、请求幂等、限流及客户端断开仍占用工作槽。浏览器12项检查覆盖同意门槛、重复点击、对照、AI标识、失败不覆盖原图，以及320/390像素和桌面排版。测试替身返回项目已有小栗插画，不是本模型生成结果。

后续真实验收应至少选人物、动物、建筑/器材三类原图，逐项核对主体身份/数量、轮廓、关键部件、纹理、背景事实、动作与构图一致性，并记录耗时和实际费用。先做少量人工验收，再考虑视觉模型复核或自动质量阈值；当前不宣称保真准确率。

本地回归：Python全量1207通过、1跳过；最后调整另跑编辑接口、网页/手机网关及启动器71项通过。前端48项通过，类型检查和生产构建通过；`启动项目.cmd --check` 通过。已有 Starlette 依赖弃用警告不影响测试结果。浏览器验证后已关闭本次临时测试服务，不影响其他成员的独立预览。
