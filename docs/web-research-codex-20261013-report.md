# MCP 摄影知识采集：2026-10-13 第一批

已完成 10 条可上传知识草稿：6 条构图卡、4 条 iPhone 15 器材操作卡。其中 5 条沿用既有知识 ID，提供新的 v2 修订；另 5 条是新增主题。此次不修改业务代码、原知识卡或项目主数据库，不审核、不发布、不推送 GitHub。

## 交付位置

- [可上传知识卡目录](E:/develop/cmera/data/knowledge_drafts/web-research-codex-20261013)：只选这里的 10 个 JSON 文件，不需要 ZIP。
- [来源登记](E:/develop/cmera/knowledge_sources/web-research-codex-20261013/sources.json)：记录实际读取范围和未读取候选，不是上传知识卡。
- [知识清单与去重记录](E:/develop/cmera/knowledge_sources/web-research-codex-20261013/manifest.json)：记录版本、证据及修订/新增动作，不是上传知识卡。
- [核验边界与待审事项](E:/develop/cmera/knowledge_sources/web-research-codex-20261013/review-notes.json)：解释为何没有采用部分通用说法，不是上传知识卡。
- [本批隔离测试](E:/develop/cmera/tests/test_mcp_research_batch.py)：使用临时 SQLite 数据库和模拟上传文件。

10 个知识文件总计 40,325 字节，符合上传页的单文件、文件数和批次大小限制。

## 实际使用了什么连接

本次调用了现有网页搜索 MCP 工具 `mcp__codex_apps__search_service_web_run`，使用其 `system2_search_query`、`open`、`find` 完成公开搜索和正文读取。

- 搜索：4 次调用，11 个查询。
- 打开正文及定位：7 次调用，29 个目标，包括同一网页不同段落及未成功的读取。
- 正文查找：1 次调用，4 个目标；查找匹配不足的地方改用完整 URL 定位正文。
- 未安装新的 MCP 或插件，未修改连接配置，未登录任何网站账号，未用 Cookie、密钥或私人资料。
- 没有使用普通 `web` 工具作替代，也没有连接这些厂商的专用账号 API。网页搜索 MCP 可读公开网页，不等于获得网站全站采集权限。

没有下载视频、图片、PDF 或原站全文，也没有把网页全文保存成来源缓存。来源记录和知识卡仅含链接、核验元数据与原创短归纳。

## 候选统计

本批登记并处置 **16 个核心候选 URL**：14 个读取了相关正文段落并用作证据，2 个未成功读取、未作为证据。这里不把全部搜索结果、导航页面或不同语言镜像重复计算为候选，也不把 14 个 URL 当成 14 个独立发布者。

未成功的路径：

- Canon SNAPSHOT 基础构图文章：打开返回错误，不能只依据搜索摘要使用。
- 最初推测的 Adobe `discover/foreground-middleground-background.html` 路径：打开失败。之后用搜索找到实际 `hub/guides` 页面，读取其正文并登记正确链接；失败地址不作为证据。

搜索结果中的第三方代理页面、社区评论及无关 Photoshop 色彩设置资料未作为本批知识依据。即使搜索标题显示“官方 Apple 支持”，也检查了最终域名，不把代理镜像当官方网站。

## 知识卡清单

| 文件 | 库 | 版本与去重 | 主题 | 核验范围 |
| --- | --- | --- | --- | --- |
| `01_leading-lines.json` | 构图 | 原 ID / v2 | 引导线的指向与线条主体 | Nikon 与 Adobe 支持核心作用；保留画外引导例外 |
| `02_horizon.json` | 构图 | 原 ID / v2 | 平直与位置分开判断 | Nikon 与 Canon 支持辅助与位置选择；倒影例外由 Nikon 支持 |
| `03_depth-layers.json` | 构图 | 原 ID / v2 | 前中后景与不必三层的例外 | Adobe 与 Canon 支持层次方法；非强制属性由 Adobe 支持 |
| `04_edge-scan.json` | 构图 | 原 ID / v2 | 边缘干扰与保护必要内容 | 综合建议；四边扫描流程不是来源验证过的视觉算法 |
| `05_negative-space.json` | 构图 | 原 ID / v2 | 非纯色留白，不硬设面积阈值 | Adobe 与 Canon 支持留白方法；纹理与颜色说明由 Adobe 支持 |
| `06_group-faces.json` | 构图 | 新 ID / v1 | 合照面部遮挡与边缘裁切 | Nikon Japan 一份一手资料；需独立复核日文归纳 |
| `07_iphone15-burst.json` | 器材 | 新 ID / v1 | 连拍与照片选择 | Apple 操作说明与 iPhone 15 规格；不填未核实帧率 |
| `08_iphone15-live-audio.json` | 器材 | 新 ID / v1 | 实况照片的动态与音频 | Apple 功能说明与型号规格；素材隐私检查是整理建议 |
| `09_iphone15-portrait-depth.json` | 器材 | 新 ID / v1 | 人像景深编辑与实体光圈区分 | Apple 操作与型号能力；不保证任意 JPEG 可编辑景深 |
| `10_iphone15-timer.json` | 器材 | 新 ID / v1 | 延迟拍摄与当前系统选项 | Apple 通用计时功能说明；具体用户系统未确认，待真机复核 |

四条构图卡标记 `cross_source_agreement`，一条构图卡为 `synthesized_guideline`，合照卡为 `primary_source_only`。四条器材事实也标记 `primary_source_only`：Apple 的多篇资料仍来自同一发布者，不称独立跨来源认证。

核验状态只表示证据层次，不是数据库审核状态，也不证明整条卡每个操作步骤都由两家来源支持。每条 `evidence.supports` 单独标明来源支持的部分，安全提醒、判断前提及结果检查包含整理者归纳。

## 处理了哪些容易降低准确性的表述

1. **引导线不强制指向人物。** Adobe 强调指向主要关注点，Nikon 也允许线条本身成为主体；按用户想表达的对象理解，不自动把另一种目标判错。[Adobe 引导线教学](https://www.adobe.com/creativecloud/photography/technique/leading-lines.html)、[Nikon School 引导线说明](https://nikonschool.co.uk/hints-and-tips/using-leading-lines-in-your-compositions)。
2. **平直与上下位置不是一回事。** 网格/水平可以帮助平直，倒影仍可保留居中；不把三分位置设为所有风景的唯一正确方案。[Nikon 构图教学](https://www.nikonusa.com/learn-and-explore/c/tips-and-techniques/5-easy-composition-guidelines)、[Canon 构图与辅助工具](https://www.canon.com.au/get-inspired/mastering-photo-composition-ideas)。
3. **不强制三层。** Adobe 明确照片不一定具备或需要所有三层；空间层次建议不能变成“缺前景就失败”的评分。[Adobe 层次说明](https://www.adobe.com/creativecloud/photography/hub/guides/foreground-middleground-background.html)。
4. **留白不等于白色像素。** Adobe 举出了带纹理或变化的留白。其文中面积经验值属于风格建议，本批未把它升级为跨场景阈值，也未独立验证情绪效果。[Adobe 留白说明](https://www.adobe.com/creativecloud/photography/type/negative-space-photography.html)。
5. **合照不推广原文示例光圈。** 源文要求逐人检查面部可见、裁切与清晰范围；实例的光圈不适用于未确认的人数、排布、距离和镜头。[Nikon Japan 合照教学](https://nij.nikon.com/learn/phototech/lenslesson/lesson22.html)。
6. **手机功能、操作、实拍表现分开。** 型号规格证明功能存在；通用手册提供操作依据，但当前用户系统、菜单和模式组合仍需确认。计时器卡没有固定时长，未套用别的机型专属硬件步骤。[iPhone 15 规格](https://support.apple.com/en-us/111831)、[Apple 相机工具中的计时器说明](https://support.apple.com/zh-cn/guide/iphone/iph3dc593597/ios)。

这些是适用范围与证据边界处理，没有发现必须在两组冲突数值之间取舍的硬件事实；不是一次全库事实审计。

## 上传与导入验证

已实际执行：

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
python -m camera_assistant.knowledge.cli import data/knowledge_drafts/web-research-codex-20261013 --dry-run
python -m ruff check tests/test_mcp_research_batch.py
python -m pytest tests/test_mcp_research_batch.py tests/test_composition_verified_batch.py tests/test_knowledge_uploads.py tests/test_knowledge_importer.py tests/test_knowledge_store.py -q -p no:cacheprovider
```

结果：10 个文件全部通过 dry-run；代码检查通过；相关测试 **153 通过、1 跳过**。

隔离测试验证了：

- 上传预览成功，但没有确认前不写数据库。
- 经确认后写入 10 个草稿修订；这是临时测试数据库，不是项目主库。
- 重复导入新增 0、未变化 10，审计条数不增加。
- 为版本测试预置 5 个 v1，写入新批次后保留旧版本及内容。
- 写入后读取的数据与解析的卡片一致。
- 同一 ID/版本改内容会整批拒绝，不覆盖已存记录。
- 新草稿不被托管正式搜索或结构化检索召回。
- 在临时库模拟审核后，`retrieval_allowed=false` 仍阻止发布；这不是给真实知识卡进行人工审核。
- 手机等值条件使用已有 `apple_iphone_15` 档案及 `auto`/`portrait` 模式；未知机型或缺少条件时不适配。此项是条件匹配单测，不证明真实 RAG 召回准确率。

项目主数据库 `data/knowledge.db` 在开始和测试结束时的 SHA256 均为：

```text
12698199AAAA460F2C9A5CBE575B29CB762B839B9ADAB31E43245737ADE47761
```

因此本次没有把这批资料实际导入项目主库，界面“知识条目”不会自动增加这些记录。原先已导入的知识保持不变。

## 如何交给队友查看或手动上传

直接阅读知识卡与来源记录即可。要查看上传预览，打开工作台，选择知识卡目录里的 10 个 JSON，再点“校验并预览”；不要选来源登记、清单或本报告。

如果你决定保存，在页面确认后才写入所配置数据库的草稿区。当前主库没有本批修订且没有其他队员同时写入的情况下，应新增 10 个草稿版本；若出现同版本不同内容冲突，应停下核对或递增版本，不覆盖旧记录。

所有卡 `source.retrieval_allowed=false`，未人工审核、未实拍验证、未核对计划检索/展示用途；不能把校验成功当成正式 RAG 可用。

构图卡的 `conditions={}`，视觉前提写在 `payload.requires`，当前检索器不会自动执行这些视觉判断。手机卡的等值条件也没有覆盖用户 iOS 版本或第三方相机差异，操作前仍需确认。现有主业务链并未因此新增构图实时路由或连拍、实况功能执行能力。

## 下一步需独立完成

- 队友逐条审核来源、归纳与例外，尤其复核日文合照段落及手机菜单。
- 手机至少确认用户系统版本与原生相机当前界面；不把真机未测试写成已验证。
- 构图建议补不同目标、场景和机位的实拍对照，记录不改善或变差的情况。
- 核对计划保存、检索、公开展示和再分发范围。未取得素材权限时不补录原站媒体。
- 确定需要导入本地库后另行备份并导入草稿；发布仍走独立审核与许可流程。

这批交付提供的是可复核的候选知识和上传验证，不是已经量化提升识别、推荐或构图准确率的结果。
