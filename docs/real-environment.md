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

需要排查链路时可分别设置 `CAMERA_AI_COMPOSITION_ENABLED=false` 或 `CAMERA_AI_DETECTOR_ENABLED=false`。云端模型请求默认超时为 120 秒，检测超时为 180 秒；它们是不同阶段的限制。

密钥只保存在本机环境或凭据存储中。`.env`、凭据、权重、上传临时文件和 SQLite 数据库均由 Git 忽略。配置更新后重启应用，避免继续使用已缓存的旧流程。

真实模式缺少密钥会明确报配置错误，不会把模拟结果当作真实模型结果。需要离线体验时，显式设置 `APP_DEMO_MODE=true`。

## 3. 启动主应用并在手机试拍

在项目根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File start_app.ps1
```

电脑浏览器打开 `http://localhost:8501/`。手机与电脑连接同一局域网后，在手机浏览器打开 `http://<电脑局域网IP>:8501/`；IP 可在电脑上通过 `ipconfig` 查看。手机上的 `localhost` 指向手机自身。系统防火墙需要允许本应用的局域网连接。

上传原始 JPG/JPEG/PNG，填写拍摄意图和主体运动状态后点击原有的“让小栗帮我配参数”。页面先展示定位候选和构图方案，再展示光圈、快门、ISO 等拍摄设置。候选编号与下方 ID 列表对应；检测分数不是正确率。图像预览使用与模型输入一致的 EXIF 修正方向，避免竖屏原图与检测框错位。

真实模式会把缩放后的现场图、拍摄需求以及必要的知识与器材信息发给所配置的模型服务。Grounding DINO 的推理在本机完成。请求失败、格式不合规或检测不可用时页面显示状态，不自动变成演示结论。

模型实验工具保持独立入口：`start_vision_lab.ps1`，端口 8502。日常实拍使用主应用的 8501。

## 4. GitHub 上传知识后接入构图

GitHub 保存供队友协作的知识文件，运行时检索本机 `data/knowledge.db` 中已发布的资料。上传到 GitHub 不会直接成为模型依据。拉取资料后，使用受管知识格式和审核流程：

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
