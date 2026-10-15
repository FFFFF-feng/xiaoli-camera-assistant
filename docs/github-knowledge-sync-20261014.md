# GitHub 知识同步合并结果

已将项目仓库中的摄影、手机及基础知识条目同步并导入本地知识库。本次新增 160 条待审核草稿，数据库由 7,647 条变为 7,807 条，原有记录和审核状态保持不变。没有提交或推送 GitHub，也没有覆盖本地应用代码。

## 同步范围

来源为 [FFFFF-feng/xiaoli-camera-assistant](https://github.com/FFFFF-feng/xiaoli-camera-assistant) 的固定提交 [6e362996ae75](https://github.com/FFFFF-feng/xiaoli-camera-assistant/commit/6e362996ae75977c2c41c183f0f474b0f2536dc6)，不是合并整个 Git 分支。

| 集合 | 条数 | 本地知识文件 |
| --- | ---: | --- |
| 队友新增手机型号知识 | 22 | `data/knowledge_drafts/mobile-models-20261014/upload_cards/` |
| 摄影知识合集 | 121 | `data/knowledge_drafts/photography-20261013/upload_cards/` |
| 基础知识草稿 | 17 | `data/knowledge_drafts/starter-v1/` |
| 合计 | 160 | 全部已保存为草稿 |

摄影合集和基础草稿此前已有本地文件，但没有进入当前数据库，因此一并补齐。新增卡片按六库分布为：场景 20、构图 22、风格 15、技术 53、器材 41、案例 9。

共校验 200 个知识及附属文本文件，新增同步 35 个，其余 165 个与本地相同。原作者、来源、许可、正文、版本和原始来源登记均保留。只读取知识文本，不下载或执行远端 Python 验证程序，不同步根目录 README 或应用代码。

## 去重和冲突规则

1. 先使用项目现有 `KnowledgeRecord` 契约校验每条文件。
2. 校验远端固定提交的 Git blob 哈希；有合集清单时，再核对每条的 SHA256、ID、版本、所属库和作者。
3. 同一 ID 和版本内容相同则跳过，保留已有审核状态；内容不同则列为冲突，不覆盖本地记录。
4. 对不同 ID，只在除 ID 和版本外的全部字段完全相同时自动去重。适用条件、证据来源、许可、作者或 payload 不同，均不能视为严格重复。
5. 旧版本跳过；所属知识库发生变化则隔离。标题相同但内容不同只登记为待人工判断，不自动拼接摄影建议。
6. 本地文件存在实质修改时保留原文件，不导入该冲突卡。仅换行符不同可视为传输差异，但也不覆写本地文件。

本次首次比对的结果是：160 条待新增、0 条严格重复、0 项冲突。没有进行向量语义去重，也没有删掉原有相近主题的条目。不同来源对同一器材的补充内容可能同时存在，后续可在保留证据与适用条件的前提下人工归并。

## 导入与验收

- 导入前已创建一致性备份：`data/backups/before-github-sync-20261014T154922631522Z.db`。
- 原有 7,647 条记录逐行比对保持不变，新增 160 条全部为 `draft`。
- SQLite 完整性检查为 `ok`。
- 真实目标数据库重复写入没有新增记录，也没有新增审计条目。
- 再次离线预览时，160 条全部判为已存在且相同，待新增为 0。
- 同步工具及既有导入、存储、上传、CLI 回归测试合计 164 项通过、1 项跳过。

手机合集及摄影合集共 143 条原始 `retrieval_allowed=false`。基础草稿中 12 条为 false、5 条为 true，均按原文件保留；这 5 条也仍是草稿，没有审核或发布。导入后当前库已发布条目数为 0，不能因为许可标记为 true 就绕过审核进入正式检索。

这些检查证明文件完整性、软件契约、导入幂等性和记录保留性，不代表已重新核验所有手机规格、案例权利或摄影效果。本次没有进行真机测试或新增人工内容审核。

## 报告位置

- [首次同步预览](../knowledge_sources/github-sync-6e362996ae75/20261014T154628664565Z/sync-report.json)
- [实际同步与合并报告](../knowledge_sources/github-sync-6e362996ae75/20261014T154922311408Z/sync-report.json)
- [数据库备份与导入结果](../knowledge_sources/github-sync-6e362996ae75/20261014T154922311408Z/database-import.json)
- [导入后再次预览](../knowledge_sources/github-sync-6e362996ae75/20261014T154954885830Z/sync-report.json)

原始快照在 `data/source_cache/github-knowledge-6e362996ae75977c2c41c183f0f474b0f2536dc6/`，不纳入 Git；本地可导入的卡片位于上表目录。不要把来源登记、报告或集合 README 当作知识卡上传。

## 后续同步命令

默认只预览，不改数据库或本地已有知识文件。以下命令从项目根目录执行：

```powershell
# 读取远端 main 的最新提交，下载知识快照并预览去重
python scripts/sync_github_knowledge.py

# 检查报告后，固定所确认的完整提交再导入
python scripts/sync_github_knowledge.py --commit 6e362996ae75977c2c41c183f0f474b0f2536dc6 --apply

# 已有缓存时可完全离线重跑，同样先预览
python scripts/sync_github_knowledge.py --commit 6e362996ae75977c2c41c183f0f474b0f2536dc6 --offline
```

`--apply` 会同步缺失的知识文本、验证独立测试库、备份本地库，然后通过公共事务接口导入草稿。它不会执行 `git pull`、提交、推送、审核发布或改变设备下拉选项。默认目标是项目 `data/knowledge.db`，可用 `--db` 指定独立测试库。

本版同步范围仅限脚本 `COLLECTIONS` 列出的上述三个集合；队友新增其他集合目录后，应先补充同步白名单和清单校验，不能假定已自动覆盖。Git 拉取的 TLS 连接错误未通过关闭证书验证来处理，本次使用 GitHub API 与固定提交的文本下载完成同步。
