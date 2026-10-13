# 摄影知识草稿合集

2026-10-13 汇总已完成的四批 **121 条**知识记录。前两批 112 条保留原 AI 整理署名；10 月 13 日新增两批共 9 条，整理人符梁。仅汇总已经生成的记录，后续请求的 20 条新增采集尚未完成，不在本合集内。

| 批次 | 条数 | 来源与历史核验 |
| --- | ---: | --- |
| 20261011 | 80 | [来源](sources/20261011/source_registry.json) · [历史校验](reports/historical/20261011/validation_report.json) |
| 20261012 | 32 | [来源](sources/20261012/source_registry.json) · [历史校验](reports/historical/20261012/validation_report.json) |
| 20261013 第一批 | 4 | [来源与冲突](sources/20261013-batch1/) · [历史核验报告](reports/historical/20261013-batch1/核验报告.md) |
| 20261013 第二批 | 5 | [来源与冲突](sources/20261013-batch2/) · [历史核验报告](reports/historical/20261013-batch2/核验报告.md) |

六库分布：场景 20、构图 18、风格 15、技术 43、器材 16、案例 9。全部 `schema_version: 1`、`dataset_split: reference`、`source.retrieval_allowed: false`，导入时由存储层生成草稿，不包含顶层审核状态。

## 目录与使用

- [upload_cards/](upload_cards/)：121 个单条 JSON，只有此目录用于导入。记录字节与本地交付版一致，未改写作者、正文、许可或版本。
- [sources/](sources/)：各批来源登记，以及 10 月 13 日两批的冲突与范围差异记录。旧来源 ID 按批次关联，10 月 12 日记录可引用 10 月 11 日来源。
- [reports/](reports/)：本次合集的软件验证与各批历史核验。历史报告中的测试日期和未执行项属于当时采集过程，不代表本次重新访问或重做内容审核。
- [manifest.json](manifest.json)：每条 ID、作者、库、版本及 SHA-256，用于检查传输完整性。

只保留知识记录、来源登记与报告文本。不包含项目数据库、网页全文缓存、ZIP、图片、视频、私有原图或备份。旧案例中可能有原交付目录的本地图片路径，本合集没有对应媒体；可依据已记录的原始链接核对，不把本地图片路径当作可用附件。报告中的本机绝对路径已替换为 `<original-workspace>`。

从项目根目录使用现有 CLI 进行只读格式校验：

```powershell
python -m camera_assistant.knowledge import data/knowledge_drafts/photography-20261013/upload_cards --dry-run
```

若使用 8502 工作台，只选择 `upload_cards/` 中的 JSON，每批最多 20 个文件，121 条分为 7 批。不要上传说明文档、来源登记、清单或核验报告。需要导入自己的数据库时，先校验预览，再按现有工作台流程确认保存草稿；本次 GitHub 上传未向项目主数据库导入这 9 条新增记录。

## 本次核验

[合集核验结果](reports/repository-upload-validation.json)由以下命令实际生成：

```powershell
python -B scripts/verify_photography_collection.py
```

验证当前模型、121 条唯一 ID/版本、禁检索状态、文件哈希及现有 CLI dry-run；在独立临时数据库按每批最多 20 条执行真实上传预览、草稿写入、重复上传、重复目录导入，以及关键词和结构化检索隔离。临时数据库结束后清理；有本地主数据库时，仅以 SQLite `mode=ro` 读取并核对前后哈希。

程序校验不证明摄影效果、语义去重、真机能力、资料许可或案例权利。本次没有重新读取所有历史来源，没有执行浏览器 UI 上传、独立人工内容审核、真机试拍、审核发布流程。所有操作建议及范围限制仍须逐卡人工复查，未审核的草稿不会自动参与受管检索。

新增 9 条中的摄影建议用 Canon 与 Sony 两个独立发布者核对核心主张；Apple 与 Sony 的厂家事实限对应型号、模式及已读取的版本文档，不把同一厂商多个页面计为独立发布者。原始链接、章节、访问日期、实际读取范围与权限情况保存在卡片及各批来源登记中。
