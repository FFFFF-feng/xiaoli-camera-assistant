# 手机型号知识草稿（2026-10-14）

整理人：符梁。22 条 `equipment` 型号事实草稿，覆盖 27 个完整型号，来源登记 24 项。每条保留原始卡片字节；`manifest.json` 记录 SHA-256。全部 `retrieval_allowed=false`，尚未独立人工审核、真机实测、授权确认或发布。

## 文件入口

- [可上传知识卡](upload_cards/)：`batch-01` 为 20 条，`batch-02` 为 2 条，符合每次上传最多 20 文件的现有工作台限制；仅选择其中的单条 JSON。
- [来源登记](sources/source_registry.json)与[冲突记录](sources/conflicts.json)：记录原始链接、发布者、地区、章节、访问日期、实际读取范围和权限边界。
- [覆盖与未收录原因](reports/historical/coverage.json)、[采集阶段核验报告](reports/historical/核验报告.md)。
- [当前主分支上传前核验](reports/current-repository-validation.json)：使用本次 GitHub 基线代码实际执行，区别于采集阶段历史报告。
- [卡片清单与哈希](manifest.json)。

涵盖 Apple、Samsung、Xiaomi / REDMI、Huawei、vivo、OPPO、HONOR、OnePlus、Google 的所列型号。覆盖地区各不相同；品牌研究仅用于选题，不能把本批称为全市场型号榜或全部主流设备的完整能力库。规格缺项保持未知，不把最高像素、最大数码倍数或宣传效果写成画质保证。

## 上传与核验边界

GitHub 存放可审核的知识文件，不自动写入项目主数据库或注册运行时机型。导入后仍为草稿。采集阶段报告位于 `reports/historical`，保留当时“尚未执行 Git 提交推送”等历史状态；公开报告副本已将本机绝对路径替换为 `<original-workspace>`。源知识卡没有改动。

可在项目根目录、已有依赖环境中复核：

```bash
python -B data/knowledge_drafts/mobile-models-20261014/verify_upload.py
```

验证脚本只读扫描已有卡片与现有主数据库；导入、重复导入及检索隔离使用独立临时数据库，并在结束后清理。它不执行审核、发布、Git 推送或安装。主数据库缺失时会如实标记未执行主库检查；本次随附报告是在主库存在的环境实际生成。

待人工审核：完整型号与销售地区、来源事实和版本、相机 App / 模式 / 镜头控制入口、与旧卡语义合并、运行时字段对齐及展示/检索/再分发许可。未验证的项目保持未知与禁止检索。
