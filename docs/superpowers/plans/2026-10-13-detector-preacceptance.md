# 定位验收前置修复实施计划

> **For agentic workers:** 按已授权执行提示词直接实施；主线程修任务范围，独立子任务负责回放、人工包和保存流程。使用失败复现、回归测试与完成验证。

**Goal:** 在零新推理下修复任务范围误判，保留原结果，交付五图可确认草稿与可重开派生记录。

**Architecture:** 不改变 detector-1 schema、检测配置与定位提示词。任务范围只读取共同任务/已保存语义；别名和复合标签使用完整短语规则。参考版本、用户原文日志、库存与配对确认记录放来源 sidecar/provenance，新记录引用旧结果。

**Tech Stack:** Python/Pydantic/Pillow/Streamlit，pytest/Ruff，独立检测环境继续保留。

**Spec:** `../../../../定位验收前置修复与人工确认-执行提示词.md`（项目上级用户明确授权的执行规范）。

## Global Constraints

- 不新增付费API请求，不自动续用上一轮7次预算；不运行检测/模型下载/重测。
- 保存原四模型、四轮历史与26条定位/纯检测记录，原失败不覆盖为成功。
- 不读人工参考决定任务范围，不按最大框/分数/main IDs猜全部必需目标。
- 人工未确认时所有质量指标未评测，继续完成独立工作。
- 阈值、输入尺寸、权重、提示词保持冻结；v1候选代码 localization-prompt-v2 不宣称质量验证。

## Review Focus

- 非主体非COCO背景不能阻断有证据的cup单目标。
- 缺失必需对象、未知部件/区域、多目标部分支持不能计完整成功。
- 短语部分重合/整体部件/描绘身份不得互相替代。
- 部分确认、库存删除、伪造confirmed与未经人确认配对不能缩分母或生成指标。
- 新派生历史不改写旧记录；保存/导入/重开/切版本/导出不能推理。

## Task 1: 范围及标签修复（主线程）

Files: `detector_runner.py`, `detector_queries.py`, 新 `detector_scope.py`, `tests/test_detector_scope.py`。

Interfaces: `_associate(detection,snapshot,queries,method)` 保持签名；queries增加 `task_text/task_scope/label_normalization`。`resolve_task_scope(task,semantics,main_ids)` 输出请求单元、作用、证据和未知范围；`label_components(label,sent_queries)` 只完整分词。

- [x] 运行cup/背景rock、缺必需目标、region/part、别名、复合标签、描绘身份与多人歧义的失败测试。
- [x] 实现有任务证据的必需/主目标/辅助/背景区分，未知范围保守退出，任务必需非COCO与层级不可替代仍unsupported。
- [x] 给新规则版本及完整helpers哈希，保存原标签/规范标签/规则来源。
- [x] 测试通过且既有golden prompt仍通过。

## Task 2: 离线回放（子任务）

Files: 新 `scripts/replay_detector_preacceptance.py`、对应测试、`preacceptance_20261013/replay`。

- [x] 保存旧实验文件哈希清单。
- [x] 26条记录同语义/查询/候选/参数回放，生成新ID、引用原ID，旧状态直接来自旧记录。
- [x] 候选坐标/标签/程序状态/主体选择分别报告，新增查询仅列计划。
- [x] 零HTTP/推理测试与源文件哈希不变核验。

## Task 3: 五图确认包（子任务）

Files: 新 `scripts/prepare_detector_confirmation.py`、对应测试、`preacceptance_20261013/confirmation_package`。

- [x] 读取实际完整任务及冻结AI草稿，五图所有必需单元保留。
- [x] 交付原图/发送图/编号草稿叠框/中文确认表/标准DetectorReference JSON；AI=false确认、complete=false。
- [x] 具体记录映射以及图像哈希、原AI来源与原任务保存sidecar；B02优先入口。
- [x] 验证全部本地资源与契约、原稿不变。

## Task 4: 保存与重开门槛（子任务）

Files: `ui_detectors.py`, `detector_storage.py`, `detector_evaluation.py`，新reference helper及对应测试。

- [x] 复现伪造confirmed/空完整参考/覆盖旧run/未经确认配对漏洞。
- [x] 新参考版本保留AI草稿、库存与用户原文/时间/字段/修订原因，仅明确确认后升级。
- [x] 部分确认不完整；保存派生历史，旧schema继续可读。
- [x] AppTest确认导入/叠框/保存/重开/切版本/导出均零推理。

## Task 5: 交付验收（主线程）

- [x] 全项目pytest与Ruff、真实浏览器只读重开与页面检查。
- [x] 将五图草稿/旧与新规则结果引用到派生可编辑历史及映射。
- [x] 独立代码复核，修实质问题并回归；报告全部证据和限制。
- [x] 交付独立新图验收计划与明确未授权请求预算，人工待确认入口保持可用。

## 执行记录

用户已提供明确目的、设计边界、顺序与执行授权，不追加技能流程审批。现有main含大量未提交他人工作；在指定目录原地做小范围修改，先保留来源/哈希，不创建不含未提交工作的worktree，不提交混合工作。

最终执行记录：关联v4/范围v3，replay_final与history_registration_final有效；435全量通过、1跳过，Ruff通过；后续UI延迟导出修复单独回归。原836实验文件、56历史文件和119草稿不变。原/修复五图参考相同且未确认，阶段二等待真实用户确认，不做人工评分。主应用并行修改已保留，未在本轮集成。
