# GLM-4.6V + Grounding DINO 真实环境接入

主应用使用 GLM-4.6V 观察画面、理解拍摄需求并生成方案，使用本机 Grounding DINO 提供候选对象位置。构图链路检索 `composition`、`style`、`case` 三类知识，方案携带本次检索资料的 ID，页面展示对应标题和来源。检测框是候选证据，主体关联仍需要结合用户意图和现场确认。

当前接入面向本机和同一局域网的实拍体验。代码接入与自动化检查不能代替真实照片、模型服务和正式知识资料的效果评测。

## 1. 准备本机环境

在项目根目录执行。如果已有 `.venv`，保留并使用该环境：

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Grounding DINO 在独立 `.venv-detectors` 中运行，主应用环境不用安装 PyTorch。实验检测环境和权重已经准备好的本机可复用；换一台电脑则显式准备：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\prepare_detectors.ps1 -Detector grounding_dino -Revision a2bb814dd30d776dcf7e30523b00659f4f141c71
```

准备过程需要联网下载依赖与权重，推理过程读取本地权重，不自动下载。预设固定本次实验的权重 revision；换用其他权重时需显式修改 `CAMERA_AI_DETECTOR_REVISION` 并重新验证。默认使用 CPU、float32、框阈值 0.35、文本阈值 0.25、180 秒超时。首次加载较慢，具体耗时以本机实测为准。详细运行环境、缓存路径与故障说明见 [检测环境文档](detector-runtime.md)。

## 2. 配置真实模式

在项目根目录的本地 `.env` 中设置：

```dotenv
APP_DEMO_MODE=false
CAMERA_AI_PRESET=glm-dino
KNOWLEDGE_RETRIEVAL_MODE=managed
KNOWLEDGE_DB_PATH=data/knowledge.db
CAMERA_AI_API_KEY=替换为自己的智谱API密钥
```

`glm-dino` 预设启用检测与构图，视觉和参数模型默认均为 `glm-4.6v`。`CAMERA_AI_API_KEY` 优先；没有该项时可以使用 `ZHIPU_API_KEY`，本机也可复用实验工具保存的智谱凭据。实验凭据受 Windows DPAPI 保护，不能通过 GitHub 复制给另一台电脑，其他机器应配置自己的环境密钥。

下表为主应用的必要配置与常用可调项。留空的预设项使用 `Settings.from_env()` 的对应默认值，不需要照抄所有参数。

| 参数 | `glm-dino` 默认 / 本次设置 | 用途 |
| --- | --- | --- |
| `APP_DEMO_MODE` | 默认 `true`，真实使用设 `false` | 显式选择真实模式 |
| `CAMERA_AI_PRESET` | 默认 `custom`，本组合设 `glm-dino` | 使用GLM与本地DINO预设 |
| `CAMERA_AI_API_KEY` | 无默认密钥 | 填本机密钥；预设支持上述智谱凭据来源 |
| `KNOWLEDGE_RETRIEVAL_MODE` | 默认 `legacy`，正式受管资料设 `managed` | 只检索符合条件的已发布资料 |
| `KNOWLEDGE_DB_PATH` | `data/knowledge.db` | 本机知识库路径 |
| `CAMERA_AI_RESPONSE_FORMAT` | `json_object`；`custom`默认`prompt` | JSON模式或仅由提示词约束JSON |
| `CAMERA_AI_FORMAT_RETRY_COUNT` | `1`，只允许 `0` 或 `1` | 最终模型文本非法JSON时额外重试次数 |
| `CAMERA_AI_MAX_OUTPUT_TOKENS` | `4096` | 每次请求的输出上限 |
| `CAMERA_AI_DISABLE_THINKING` | `false` | 保留服务默认思考设置；按需显式关闭 |
| `CAMERA_AI_TIMEOUT_SECONDS` | `120` | 云端请求超时秒数 |
| `CAMERA_AI_DETECTOR_TIMEOUT_SECONDS` | `180` | 本地检测超时秒数 |
| `CAMERA_AI_COMPOSITION_ENABLED` / `CAMERA_AI_DETECTOR_ENABLED` | `true` / `true` | 排查时可单独设`false` |

请求仍使用 Chat Completions。默认JSON模式与格式重试是主应用配置，不继承实验窗口的请求设置。格式重试只在服务已返回最终模型文本、且该文本不是合法JSON时发生；401、网络错误、超时、输出截断、思考内容没有最终答案等失败不重试。JSON结构不符合业务数据模型也不触发该格式重试。失败显示脱敏状态，不自动改用演示结论。

密钥只保存在本机环境或凭据存储中。`.env`、凭据、权重、上传临时文件和 SQLite 数据库均由 Git 忽略。配置更新后重启应用，避免继续使用已缓存的旧流程。

真实模式缺少密钥会明确报配置错误，不会把模拟结果当作真实模型结果。需要离线体验时，显式设置 `APP_DEMO_MODE=true`。

## 3. 启动主应用并在手机试拍

在项目根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File start_app.ps1
```

电脑浏览器打开 `http://localhost:8501/`。手机与电脑连接同一局域网后，在手机浏览器打开 `http://<电脑局域网IP>:8501/`；IP 可在电脑上通过 `ipconfig` 查看。手机上的 `localhost` 指向手机自身。系统防火墙需要允许本应用的局域网连接。

上传原始 JPG/JPEG/PNG，填写拍摄意图、主体运动和手持 / 三脚架状态。选择具体设备后，可在“相机与镜头”和“拍摄条件补充”中填写已确认的信息：

| 选填信息 | 填写方式与边界 |
| --- | --- |
| 设备完整型号 | 通用档案可补充实际型号；已选择的具体型号优先于冲突自填值，不套用相近型号能力 |
| 镜头完整型号、当前焦段、最大光圈 | 填实际使用的镜头与当前状态，不从参考照片猜测 |
| 手机相机应用、系统大版本 | 例如实际App名称与iOS/Android大版本；第三方App不套用原生控制能力 |
| 相机快门类型 | 机械`mechanical`、电子`electronic`、电子前帘`efcs` |
| 相机驱动模式 | 单张`single`、连拍`continuous` |
| 相机对焦模式 | 单次自动`AF-S`、连续自动`AF-C`、手动`MF` |
| 光线类型 | 自然光、连续人造光、已确认频闪的人造光、混合光；单张照片的模型猜测不能确认频闪 |

不清楚的项目留空或选“不清楚”，系统不把未知条件推断为某种快门、对焦、光源或系统版本，要求这些条件的专用资料会保守排除。已选具体机型档案优先于冲突的自填画幅。参考照片EXIF是该照片的记录，不作为当前目标设备、App、系统版本或拍摄模式。

点击“让小栗帮我配参数”后，页面先展示定位候选和构图方案，再展示光圈、快门、ISO等设置。候选编号与下方ID列表对应；检测分数不是正确率。图像预览使用与模型输入一致的EXIF修正方向，避免竖屏原图与检测框错位。

主应用使用独立的摄影目标关联实现，与8502实验工具的对照实现分开。要求“突出猫眼、完整保留耳朵和胡须”时，猫整体是主目标，耳、眼和胡须是取景保护要求，不等于每个部件必须有检测框。多个同类候选不能唯一对应用户目标时仍保守弃权，不按分数强选；静止宠物归入`pet_portrait`，快速运动才使用`fast_pet`。保护要求仍需检查取景四边余量与实拍结果。

建议校验会屏蔽已识别的明确物理矛盾，并按已收录机型的实际硬件上限处理快门、光圈等限制，支持中文快门表达。这些检查不证明全部建议正确，也不能由单张照片保证曝光、景深或运动清晰度；仍需相机测光、直方图与试拍。

真实模式会把缩放后的现场图、拍摄需求以及必要的知识与器材信息发给所配置的模型服务。Grounding DINO 的推理在本机完成。请求失败、格式不合规或检测不可用时页面显示状态，不自动变成演示结论。

模型实验工具保持独立入口：`start_vision_lab.ps1`，端口 8502。日常实拍使用主应用的 8501。

## 4. GitHub 上传知识后接入构图

GitHub保存供队友协作的知识文件，运行时检索本机`data/knowledge.db`中已发布的资料。上传到GitHub不会直接成为模型依据。当前121条JSON草稿加17条starter草稿，共138条；其中12条v2修订收紧设备与条件，仍是草稿，不扩大条数，不自动导入或发布主数据库。

接入分两阶段：先核验内容、来源授权、设备与拍摄条件，导入草稿后由非作者独立审核并按流程发布；再让主应用在`managed`模式检查实际召回与引用。来源授权审核通过不等于系统已接通，系统能检索也不代替内容审核。不要为了得到检索结果批量改动许可。

拉取资料后，使用受管知识格式和审核流程：

```powershell
.\.venv\Scripts\python.exe -m camera_assistant.knowledge init
.\.venv\Scripts\python.exe -m camera_assistant.knowledge import docs/knowledge-drafts --dry-run
.\.venv\Scripts\python.exe -m camera_assistant.knowledge import docs/knowledge-drafts
.\.venv\Scripts\python.exe -m camera_assistant.knowledge submit 实际知识ID
.\.venv\Scripts\python.exe -m camera_assistant.knowledge approve 实际知识ID --reviewer 实际审核人 --note "已核验来源和适用条件"
.\.venv\Scripts\python.exe -m camera_assistant.knowledge publish 实际知识ID
.\.venv\Scripts\python.exe -m camera_assistant.knowledge search "构图 主体位置 留白" --library composition
```

文件目录、知识 ID 与审核人都应换成实际值。审核人与作者必须不同，资料必须属于可检索的参考集且具备检索许可。支持受管 JSON、YAML、带 YAML 元数据的 Markdown；普通文章不能直接导入。完整字段模板、版本和条件约定见 [知识库开发说明](knowledge-development.md)。

构图资料放入 `composition`，风格资料放入 `style`，参考案例放入 `case`。参数链路继续检索 `scene`、`technique`、`equipment`。资料可带适用条件；条件不匹配时不进入本次建议。

还没有发布资料、匹配不到相关资料或引用不完整时，页面明确显示缺少知识依据或待验证，不会给未检索到的知识补造引用。后续发布资料无需重建关键词索引；下一次分析会读取当前发布版本。

## 5. 第一轮实拍记录

建议在同一照片与同一意图下记录：候选框是否覆盖目标、主体关联是否符合需求、构图操作是否能执行、引用是否解释了该方案、请求耗时及失败原因。再按建议重新取景并拍摄对照照片。对于没有正式知识依据的方案单独标记，等知识发布后重跑相同样例，便于判断新资料实际带来的变化。

模型名、阈值和检测环境应在这轮比较中保持一致。真实调用会产生所用模型服务的费用，费用与耗时以服务返回和本机记录为准。
