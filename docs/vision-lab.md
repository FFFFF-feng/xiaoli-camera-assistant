# 视觉模型测试窗口

独立开发工具，不接入 `app.py` 推荐流程，不修改知识库。支持单图一次 2～4 个配置比较；没有密钥也可使用两个固定模拟夹具完成评测。模拟输出与上传照片内容无关，不能用于真实质量或准确率结论。

左栏“检测与联合定位”提供独立的纯检测和 A/B1/B2 对照，不受原比较页至少2模型的限制。
检测环境、记录和指标独立，四轮v1历史不改写。操作见 [检测工具说明](detector-lab.md)，
本次真实检测、模拟和未验证项见 [交付验证](detector-verification.md)。

## 简单使用：四模型快捷区

默认显示 **Qwen3-VL Plus、Doubao-Seed 2.1 Lite、Doubao-Seed 2.1 Pro、GLM-4.6V**。协议、连接地址、模型 ID、120 秒超时和 4096 输出上限已预填；高级参数收起。选择“模拟 / 其他模型”可以继续使用免密钥演示及以前的自定义配置。

在“API Key（本机长期保存）”填写三份 Key：百炼用于 Qwen、火山方舟用于两个 Doubao、智谱用于 GLM。点击“保存 API Key 到本机”，之后重开自动读取。空白保留已保存项；保存后密码框清空，已保存值不回显。

密钥通过 Windows DPAPI 按当前用户加密，保存在 `data/vision_lab/credentials.dpapi.json`。目录已被 Git 忽略，密钥不进入普通配置、历史和导出。换 Windows 账号或电脑需要重新填写。来源优先级：会话临时输入 > 本机加密保存 > 环境变量（含 `.env`）> Streamlit secrets。盲评或隐藏输入框不改变临时 Key；删除本机保存项不删除环境变量中的 Key。调用时仍会使用 Key 向服务商认证，并发送所选图片；本地运行不等于离线调用。

| 模型 | 已预填 ID | Key 输入区 |
|---|---|---|
| Qwen3-VL Plus | `qwen3-vl-plus` | 百炼 |
| Doubao-Seed 2.1 Lite | `doubao-seed-2-1-lite-260915` | 火山方舟，两款共用 |
| Doubao-Seed 2.1 Pro | `doubao-seed-2-1-pro-260915` | 火山方舟，两款共用 |
| GLM-4.6V | `glm-4.6v` | 智谱 |

四模型默认省略可选 detail/推理参数，按各服务商默认行为执行；不代表所有模型关闭了思考。先用 prompt 要求 JSON 并本地校验。未核价时费用保持未知。需要账户专属域名、不同版本或思考选项时，再展开“高级模型设置”。

来源：[百炼视觉接口](https://help.aliyun.com/zh/model-studio/qwen-vl-compatible-with-openai)、[方舟模型列表](https://docs.volcengine.com/docs/ark/model-list?lang=en)、[方舟推理参数](https://docs.volcengine.com/docs/ark/deep-thinking?lang=en)、[智谱 GLM-4.6V](https://docs.bigmodel.cn/cn/guide/models/vlm/glm-4.6v.md)。预填 ID 不保证账号已开通模型或满足地域/套餐权限。本次快捷区改动没有发出新的真实模型请求，其他三款仍待实际联调。

### 界面选项的含义

- **选择要比较的模型**：被选模型各自分析同一张照片；选四个会得到四份回答。
- **纯识图**：只问“照片里有什么”，检查主体、位置、场景、光线和不确定性，不加入目标和器材。
- **建议测试**：还问“为了我的目标，应该怎么拍”。例如同一骑行图，输入“凝固骑行者、器材未知”，比较方案；同次比较的目标和器材保持一致。
- **最长边**：等比例缩小照片，不放大小原图。4000×3000 设1600会发送1600×1200；更大可能保留更多小主体细节，也增加数据量。
- **JPEG质量**：控制压缩，不控制尺寸；88不表示88%准确率。较低可能丢失纹理、出现块状痕迹，较高文件通常更大。图像token/费用由服务商决定，质量数值不单独决定费用。

初次保持1600和88即可：填并保存Key → 选模型 → 上传单张图 → 选纯识图 → 运行 → 人工评测与保存。填Key、保存和切换设置不会调用模型。

## Windows 启动

已在本机桌面创建 **小栗视觉模型测试** 快捷方式。双击后会后台启动 8502 并自动打开浏览器；工具已运行时直接打开。请保留项目目录。启动脚本为根目录 `start_vision_lab.ps1`，首次启动诊断日志位于 `data/vision_lab/launcher/`。

在项目根目录执行（已有 `.venv` 可直接复用）：

```powershell
.\.venv\Scripts\python.exe -m streamlit run vision_lab.py --server.port 8502 --server.address 127.0.0.1
```

打开 <http://127.0.0.1:8502>。原应用仍用 `streamlit run app.py` 和 8501 端口。

首次安装：

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

无需复制或覆盖已有 `.env`。`.env.example` 末尾是本工具的密钥来源示例；也可将同名变量放到 `.streamlit/secrets.toml`，或在页面 password 框临时输入。优先级为临时输入 > 本机加密保存 > 环境变量（含 `.env`）> secrets。临时密钥只在当前 Streamlit 会话中，配置保存只保存变量名。

## 免密钥完整流程

1. 在“模型选择方式”中选“模拟 / 其他模型”，默认选择“模拟正常”“模拟遗漏”；上传 JPG/JPEG/PNG（真实格式校验、上限 15 MB）；也可点“使用内置模拟示例图”。
2. 查看方向修正原图、压缩 JPEG、尺寸/哈希；填写人工参考标签、0～1 数字框与备注。它们不会进入请求。
3. 选“纯识图”或“建议测试”，设置实验/提示词版本和“开发/验证”用途；点击“运行测试”。
4. 并排查看中文场景、主体、光线、构图卡片、主体框、耗时、用量与估算；建议测试额外显示方案卡片。新增“模拟格式错误”或将模拟夹具改为 `invalid_box` / `failure` 可验证失败隔离。
5. 开盲评、填写四维评分、错误标签（含自定义）、确认情况/严重程度/证据/疑似原因和正确情况说明。框 IoU 必须手动选择一对一配对。
6. 点“保存记录与评测”，在下方重新打开历史；按模型、图片哈希、错误、模式、实验版本和用途筛选并下载 JSON/CSV。下载保留真实身份。

只点击“运行测试”会请求模型；配置、评分、下载和历史重开均不调用。每次点击是新 run_id，每配置仅尝试一次，不自动重试。一次失败不阻断其他配置。记录保存前只在会话中，关闭页面后未保存数据会丢失。

### 中文结果怎么读

默认卡片显示模型报告的场景、主体、光线与明暗和构图线索。主体编号自动对应到名称，位置是已校验位置框的中心所在区域，不代表另一次定位。运动线索与推测分开展示，未知明确显示“无法确定”；空列表显示“未报告”，不能据此推断没有该现象。自报可信度是模型自己的判断，不是实测准确率。

“建议测试”显示每个方案的动作类型、目标和“怎么做”；展开后可看理由、取舍、适用条件、限制与可选参数。没有参数时不会补猜。原始回答和结构化 JSON 默认收在“原始回答与 JSON（排查用）”，导出和人工评测仍使用原始字段与主体编号。

转换在本地完成，不调用翻译接口。英文固定选项和部分常见主体名称可显示中文，任意英文描述保留原文；后续请求明确要求描述性内容使用简体中文，JSON 字段名、枚举值和主体编号保持协议要求。历史记录重新打开即可使用中文视图，不需要重跑模型。

## 接入国内服务

页面展开“编辑 / 新增模型配置”，选择示例并改为自己的模型 ID，然后“应用配置”。选择该配置与模拟夹具一起比较即可排查接入。可从模板新增同服务不同参数的独立配置。

| 服务 | 协议 | Base URL 示例 | 密钥变量 | 模型填写 |
|---|---|---|---|---|
| 百炼国内 | chat | `https://dashscope.aliyuncs.com/compatible-mode/v1` | DASHSCOPE_API_KEY | 可编辑 `qwen3-vl-plus` 示例；以账户地域为准 |
| 火山方舟 | chat | `https://ark.cn-beijing.volces.com/api/v3` | ARK_API_KEY | 控制台已开通的视觉模型 ID 或 endpoint ID |
| 智谱 | chat | `https://open.bigmodel.cn/api/paas/v4` | ZHIPU_API_KEY | 控制台支持 base64 图文输入的模型 ID |
| 本地兼容服务 | chat | `http://localhost:8000/v1` | 默认空 | 本地部署视觉模型的实际名称 |

百炼官方当前推荐工作空间专属域名：`https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`，页面可编辑；旧域名仍是官方支持的示例。各地域密钥、模型开通和能力不同。火山/智谱模型不预填，避免把某个账号或地域的能力当作普遍可用。部分智谱旧型号不支持 base64；本工具不自动上传照片换取公共 URL。

默认 `structured=prompt`、`detail=omit`、`reasoning=omit`，仅以提示词要求 JSON 后做本地 Pydantic 校验。确认所选模型支持后才开启：

- Chat: `response_format=json_object` 或 `json_schema`；`image_url.detail`；百炼 `enable_thinking=true/false`、方舟/智谱 `thinking_type=enabled/disabled/auto`，或兼容服务 `effort`。各模型不一定支持所有选项。
- Responses: `text.format`、`input_image.detail`、`reasoning.effort`；`store=false`，不使用历史 response ID。
- Anthropic: `output_config.format=json_schema`；`thinking.budget_tokens` 必须 >=1024 且小于最大输出；不支持本工具的 OpenAI detail/json_object 选项。
- Gemini: `generationConfig.responseMimeType/responseJsonSchema`、`thinkingConfig.thinkingBudget`；省略 OpenAI detail。模型可能采用不同 thinking 控制，不支持时请使用 omit。

目前只做非流式调用；仅支持流式的型号不能使用此版。最大输出在 Chat 使用 `max_tokens`，Responses 使用 `max_output_tokens`，Messages 使用 `max_tokens`，Gemini 使用 `maxOutputTokens`。不支持可选参数时返回配置/HTTP 错误，不自动降级后重发付费请求。

## 其他协议

| 服务 | 协议 | Base URL | 密钥变量 |
|---|---|---|---|
| OpenAI | responses | `https://api.openai.com/v1` | OPENAI_API_KEY |
| Anthropic 直连 | anthropic | `https://api.anthropic.com/v1` | ANTHROPIC_API_KEY |
| Google Gemini Developer API | gemini | `https://generativelanguage.googleapis.com/v1beta` | GEMINI_API_KEY |

模型 ID 手填。账户需有该模型权限，并满足厂商支持的地区、网络与支付要求；预设不证明当前账户可调用。Anthropic Bedrock/Vertex、Gemini Vertex IAM 与代理的非兼容协议不在首版范围。

## 实验、评测与成本定义

- 全部模型收到同一 JPEG 字节、任务、schema 和共同上下文；记录 original/corrected/sent 尺寸和哈希、压缩与每配置的 detail。厂商内部缩放不可控，不能声称输入差异完全消除。
- 统一 bbox 为 EXIF 修正后的 `[x_min,y_min,x_max,y_max]` 0～1 坐标。缩放不裁切，归一化框可直接绘制到修正原图。像素/0～1000、越界、倒序和零面积均报结构错误，不猜单位/截断/自动修复。
- 纯识图不加入人工答案、目标、器材、EXIF、资料和历史。建议上下文从独立输入构建，EXIF 默认关闭，开启时标注为原图拍摄记录。可编辑模板是实验输入，手工加入答案会破坏实验，请记录版本并避免。
- 自动场景指标为人工勾选可判定且有结构化观察结果的标签集合完全匹配率；无标注与调用/解析缺失不算对错。格式/调用率分别反映 schema 校验和获得可解析厂商响应，HTTP 成功但格式错会计调用成功。IoU 只计人工指定且双方有合法框的一对一匹配，未配对不进入均值。
- 汇总显示唯一图片数、运行结果数、已人工评测数/缺失数、场景有效数/缺失数、框对数、各评分有效数/缺失数。按完整请求配置、返回模型与图片预处理设置哈希进一步分组，修改 detail/推理/服务地址后不会混合历史。未配对框不冒充检测准确率；不确定性、自报置信度和四维人工评分不等于准确率。开发和验证样例分组；不能用反复调试的开发集证明最终质量。
- 没有 token/单价/核价来源/日期时费用显示未知；不会把缺失用量填 0。Chat/Responses 的 reasoning token 已包含在输出总量，不再加一次；Gemini 的 thoughts 单独计输出；Anthropic 缓存读写与 input_tokens 分开，分别计费。缺少必要缓存/推理细节时不估算；若缓存明细和缓存价格都未提供，按输入原价显示上界并明确标注限制。
- CNY / USD 分别累计，并显示已知/未知费用结果数。不换汇，token 估算不覆盖阶梯、独立图片计费等，账单以厂商为准。

## 本地记录与隐私

默认在 `data/vision_lab/` 保存 `configs.json`、`templates.json`、`runs/<run_id>.json`。只有明确勾选保存样例并点击保存，才生成 `samples/<run_id>.png`（方向修正、去 EXIF 副本）。目录已 gitignore，不自动上传历史或图片。没有本地照片时，重传相同哈希原图可恢复历史框预览。

每个结果保留 config/result ID、请求/返回模型、协议、提示词版本/hash、完整任务、实验设置、时间、耗时、最终文本、解析状态、一次尝试记录、用量与脱敏错误。隐藏思维块不保存、不索取。JSON 保留嵌套结构；CSV 每个错误一行，没有错误保留一行，适合筛选。CSV 对公式前缀做文本转义。

请求头、密钥和完整 base64 不进入记录与下载。Base URL 拒绝内嵌凭据/查询参数。模型可能回显秘密，因此已知密钥及图片 base64 也会在记录边界脱敏。请勿把其它秘密写进用户目标、模板或评测说明。

## 官方来源与验证边界（2026-10-11 核对）

- [百炼 OpenAI Vision 兼容接口](https://help.aliyun.com/zh/model-studio/qwen-vl-compatible-with-openai)、[Chat 参数参考](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)。
- [方舟 Chat API](https://docs.volcengine.com/docs/ark/chat-api?lang=zh&redirect=1)、[官方 API Explorer](https://api.volcengine.com/api-explorer/?action=ChatCompletions&groupName=Chat+API&serviceCode=ark&version=2024-01-01)。页面为动态内容，抓取有限，已以官方索引确认路径和 image_url 形状；真实账号兼容性待联调。
- [智谱官方视觉请求示例源代码](https://github.com/zai-org/GLM-V/blob/main/skills/glmv-prompt-gen/scripts/prompt_gen.py)。官方文档站本次抓取失败，以官方仓库确认图文请求与 base64 差异，不据此宣称特定模型已可用。
- [OpenAI 图片输入](https://developers.openai.com/api/docs/guides/images-vision)、[Responses 结构化输出](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)。
- [Anthropic 图片](https://platform.claude.com/docs/en/build-with-claude/vision)、[结构化输出](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)。
- [Gemini generateContent/用量参考](https://ai.google.dev/api/generate-content)、[结构化输出](https://ai.google.dev/gemini-api/docs/structured-output)。

用户于本会话明确授权了一次百炼测试。已在实际页面点击“运行测试”，向百炼国内兼容地址的 `qwen3-vl-plus` 发送内置几何示例图，`max_tokens=2048`、prompt JSON、detail/推理参数省略。HTTP 200、最终 JSON 通过 schema，耗时 12.5631 秒、输入 1379 / 输出 539 token、缓存 0，唯一一次尝试，无自动重试。服务返回模型字段为 `qwen3-vl-plus`（不是不可变快照版本），识别出背景、矩形与圆形。原始最终回答与记录保存在本地历史 run `2ede25dde682490894b53b6c508c2c02`，照片未落盘，价格未知未估算。

**仍未验证**：百炼其他型号/地域、原生 json_object/json_schema、detail/推理选项、建议模式真实效果和账单；方舟、智谱、本地模型、OpenAI、Anthropic 与 Gemini 均未真实调用。一次几何图测试不代表摄影照片识别准确率或建议质量。离线 MockTransport 只证明工具的请求构造、解析、错误隔离和记录逻辑，不等于对应服务商真实联调。

## 检查命令

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

本次测试环境 Python 3.13，满足项目 3.11+ 要求；没有额外修改项目依赖声明。页面自动化需要本地回环 socket；受限沙箱可将 TEMP/TMP 指向项目 tmp 并在允许回环的环境运行。详细交付验证见 `vision-lab-verification.md`。
