# 第一批构图知识卡整理与导入验证

整理及本地验证日期：2026-10-13。

已将 5 条基础构图原则整理为可直接上传的 Markdown 知识卡，并通过现有上传桥接层导入本地 `data/knowledge.db`。本批是已有知识编号的 **v2 草稿修订**，不是 5 个新增主题；v1 和其他记录均保留不变。

## 收录内容与证据边界

| 文件 | 沿用知识编号 | 本次补充重点 | 核心原则证据 |
| --- | --- | --- | --- |
| `01_background-separation.md` | `expanded-v1-composition-background-separation` | 背景重叠检查、机位比较、环境叙事例外 | Nikon 与 Adobe 交叉支持 |
| `02_framing.md` | `expanded-v1-composition-framing` | 真实前景、主体遮挡、用户表达选择 | Adobe 与 Canon 交叉支持 |
| `03_thirds.md` | `expanded-v1-composition-thirds` | 三分法非强制、居中例外、不作唯一评分 | Adobe 与 Nikon 交叉支持 |
| `04_fill-frame.md` | `expanded-v1-composition-fill-frame` | 主体占比与故事背景的取舍、不同取景方式 | Adobe 与 Canon 交叉支持 |
| `05_look-room.md` | `expanded-v1-composition-look-room` | 朝向不确定时不猜左右、情绪不作确定因果 | 一份已读取的 Nikon 一手资料 |

知识卡目录：[composition-verified-v2](E:/develop/cmera/data/knowledge_drafts/composition-verified-v2)。不需要 ZIP；上传时选择该目录下的 5 个 `.md` 文件即可。**本说明和原来的抖音来源清单不是上传知识卡，不能一并上传。**

每条包含核心主张、适用前提、操作建议、限制与例外、提示文案、来源 URL 与具体章节、核验范围和未完成事项。

操作流程、安全提醒、视觉不确定时的处理方式是整理者的操作化归纳，不声称厂商逐字给出这些流程；未测定实拍改善率。四条“交叉支持”也只覆盖标注的核心原则，不等于整条知识卡已完成人工审核。

## 与抖音素材的关系

抖音清单只用于发现与关联选题。知识卡的依据是独立核对的官方教学资料，未导入博主视频、原片、完整文稿或作品图片，也不称这些文字为博主原话。

卡片中的 `discovery_source_ids` 可追溯到原清单，不能用来证明完整视频已核验或作者授权已取得。原来源登记与核验报告未修改。

本批未采纳固定钟点、固定变焦倍数、固定角度、跨场景人物比例、必然显高显瘦或必然产生某种情绪等通用结论；第 10 条的运镜片段未纳入静态构图库。

## 当前存储与检索状态

- `library_id=composition`，`kind=guideline`，`version=2`。
- `dataset_split=reference`：这是候选参考知识，不是上传烟雾测试的评测样本。
- 数据库状态为 `draft`；`source.retrieval_allowed=false`。
- 独立人工复核、实拍验证、检索与公开使用范围核对尚未完成。
- 没有提交审核、批准或发布，也没有修改应用检索模式。

`conditions={}` 表示这些卡目前没有声明由存储检索器执行的等值筛选条件。`payload.requires` 是阅读及将来编排建议时使用的前提，**当前代码不会自动把它变成视觉置信过滤或实时动作指令约束**。不要因卡片列有这些前提就宣称实时指导已实现。

本机本次读取的应用配置仍为 `legacy`。正式托管检索另有发布和许可过滤；主业务链是否路由到构图库仍需单独开发和验证。此次完成的是整理、上传格式兼容和本地草稿写入，不是移动端构图指导接入。

## 本地验证结果

数据库：[knowledge.db](E:/develop/cmera/data/knowledge.db)。

导入前通过 SQLite backup 接口创建了一致性备份：[导入前备份](E:/develop/cmera/data/backups/knowledge-before-composition-v2-20261013-203534-386144.db)。备份和真实数据库均被 Git 忽略，不应上传 GitHub；如需恢复，应先停止数据库写入并单独安排恢复，不覆盖仍在使用的数据库。

| 检查项 | 实际结果 |
| --- | --- |
| CLI 只校验，不写库 | 5 个文件全部通过 |
| 上传层解析与确认流程 | 隔离的 Streamlit AppTest 通过；未启动用户项目服务 |
| 本地首次导入 | 新增 5 个 v2 草稿，无错误 |
| 使用相同文件再次导入 | 新增 0，未变化 5，未增加审计记录 |
| 总修订数量 | 86 → 91 |
| 构图库草稿修订数量 | 21 → 26；这是版本数，不是主题数 |
| 旧修订与旧审计日志 | 逐项比较保持不变 |
| 写入后读取 | 5 条记录与上传解析结果完全一致 |
| 新审计事件 | 5 条 `save_draft`，无审核或发布事件 |
| 托管检索隔离 | 5 个查询结果与导入前一致，均未召回草稿；结构化查询也未变化 |
| SQLite 完整性 | 备份与导入后的主库均返回 `ok` |

针对本批及现有上传、解析、存储的测试结果：**136 通过，1 跳过**。初次运行另有 `.pytest_cache` 无写权限警告，不影响测试通过或知识写入；没有为此修改目录权限。

这些检查证明本批格式、写入、版本保留和隔离机制正常，**不证明摄影效果、视觉识别准确率或第三方内容使用权限**。

## 如何在工作台查看

打开知识库导入工作台后，选择“构图知识库” → “知识条目”，将状态设为“草稿”或“全部状态”。找到表格里的知识编号，查看 `v2` 即可；v1 仍能查看。

如果还想手动检查上传交互，选中这 5 个 Markdown → “校验并预览” → 确认保存草稿。本库已导入，因此再次保存应显示没有新增、5 条未变化；只点“校验并预览”不会写入数据库。

## 离线复现

在项目根目录的 PowerShell 中执行，环境需要已安装项目依赖：

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
python -m camera_assistant.knowledge.cli import data/knowledge_drafts/composition-verified-v2 --dry-run
python -m pytest tests/test_composition_verified_batch.py tests/test_knowledge_uploads.py tests/test_knowledge_importer.py tests/test_knowledge_store.py -q -p no:cacheprovider
```

重新导入同一数据库可用以下命令。它仍只保存草稿；同编号同版本且内容相同会保持不变，内容不同则拒绝，需要人工整理新的递增版本。

```powershell
python -m camera_assistant.knowledge.cli --db data/knowledge.db import data/knowledge_drafts/composition-verified-v2
```

## 后续审核清单

1. 队友独立阅读卡片及来源章节，检查适用条件与例外，不能把自动化测试当人工审核。
2. 补充不同机型、拍摄距离与目标下的实拍对照；人物案例需另行确认使用同意。
3. 核对计划使用范围，明确保存、检索、展示与再分发的区别。不因来源公开就认为可任意使用原文和配图。
4. 若允许检索，保存明确许可信息并建立递增版本，再按已有审核流程提交、批准和发布；不改写历史修订。
5. 单独接入构图知识路由、视觉置信条件和动作生成验证，不把知识卡直接变为实时移动命令。

## 已核对的一手依据

- 背景组织与机位示例：[Nikon — Take Better Portraits](https://www.nikonusa.com/learn-and-explore/c/tips-and-techniques/take-better-portraits)。
- 框架及视觉强调：[Adobe — Emphasis in photography](https://www.adobe.com/creativecloud/photography/discover/emphasis-in-photography.html)。
- 自然框架与紧取景：[Canon — Mastering Photo Composition](https://www.canon.com.au/get-inspired/mastering-photo-composition-ideas)。
- 三分法及例外：[Adobe — How to use and break the rule of thirds](https://www.adobe.com/creativecloud/photography/technique/rule-of-thirds.html)。
- 三分位置、朝向留白及例外：[Nikon — 5 Easy Composition Guidelines](https://www.nikonusa.com/learn-and-explore/c/tips-and-techniques/5-easy-composition-guidelines)。
- 收紧取景与叙事背景：[Adobe — Fill the frame photography](https://www.adobe.com/creativecloud/photography/technique/fill-the-frame.html)。

这些网页仅作为可追溯依据链接；本批没有下载或再分发原站媒体与全文。
