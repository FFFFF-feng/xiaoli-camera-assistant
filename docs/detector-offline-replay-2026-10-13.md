# 检测定位前置修复：已有记录离线回放

> 本文记录审查前的关联v2中间快照，保留作恢复对照。最终关联v4及有效记录见 [最终前置修复报告](detector-preacceptance-repair-2026-10-13.md)，采用 `replay_final/` 和 `history_registration_final/`，不能以本文旧ID替代最终映射。

2026-10-13。完整回放26条旧历史，保留23条A原结果，仅对52个检测方法执行新的任务范围、类别标签规范和主体关联。**未增加API请求、检测推理、下载或模型加载；没有人工真值，全部人工质量指标为null。**

结果没有新增自动主体选择。75个方法的原状态均保留；唯一主体关联状态变化是B02 v0纯检测YOLO的`abstained→unsupported`，因为原任务还必需杯内区域。全部候选坐标、原始标签、分数及实例ID不变。修复证明程序能够更忠实地表达范围和关联，不能据此宣布准确率提高。

## 交付与复用契约

- [全部75方法新旧对照JSON](C:/Users/丁铭哲/Documents/ChatGPT/摄影/xiaoli-camera-assistant/data/vision_lab/detector_experiments/preacceptance_20261013/replay/replay_comparison.json) / [CSV](C:/Users/丁铭哲/Documents/ChatGPT/摄影/xiaoli-camera-assistant/data/vision_lab/detector_experiments/preacceptance_20261013/replay/replay_comparison.csv)
- [五图逐方法对照JSON](C:/Users/丁铭哲/Documents/ChatGPT/摄影/xiaoli-camera-assistant/data/vision_lab/detector_experiments/preacceptance_20261013/replay/five_sample_comparison.json) / [CSV](C:/Users/丁铭哲/Documents/ChatGPT/摄影/xiaoli-camera-assistant/data/vision_lab/detector_experiments/preacceptance_20261013/replay/five_sample_comparison.csv)
- [26条来源与派生run映射](C:/Users/丁铭哲/Documents/ChatGPT/摄影/xiaoli-camera-assistant/data/vision_lab/detector_experiments/preacceptance_20261013/replay/run_mapping.json)
- [规则全文和哈希](C:/Users/丁铭哲/Documents/ChatGPT/摄影/xiaoli-camera-assistant/data/vision_lab/detector_experiments/preacceptance_20261013/replay/rule_snapshot.json)、[原文件前后核验](C:/Users/丁铭哲/Documents/ChatGPT/摄影/xiaoli-camera-assistant/data/vision_lab/detector_experiments/preacceptance_20261013/replay/integrity.json)、[逐字段交付验收](C:/Users/丁铭哲/Documents/ChatGPT/摄影/xiaoli-camera-assistant/data/vision_lab/detector_experiments/preacceptance_20261013/replay/replay_acceptance.json)

派生JSON位于`replay/runs/<原版本>/<样例>/<paired或pure>/run.json`。run、attempt和MethodResult使用新ID；原VLM与DetectionResult的ID、原答、语义、候选、配置和失败完整保留，作为真实历史的复用来源。每个新结果记录来源run/result/detection/vlm ID和来源文件、VLM、候选、查询、任务、图片、配置的哈希。

`from_task/from_vlm/manual/merged/fallback`实际查询数组逐项不变，传给新`_associate()`的额外输入只有原`task_prompt`作为`task_text`。输出新增`task_scope`和`label_normalization`证据。没有重跑`compose_queries()`、VLM解析或`localization_provenance()`，实际发送prompt与schema逐字保留。推理历史耗时/费用保留在来源命名空间；本次执行另记离线耗时和零新请求，避免将旧token、耗时和未知账单当作新增消耗。

新规则为`conservative-association-v2`、`task-english-v2`、`explicit-task-units-v1`和`complete-query-phrase-v1`。规则快照保存完整runner/query/scope模块字节及哈希，包含新增helpers与常量；bundle SHA256：`cafd5eac5c1596f09db35bb31999b674749581fb830d968b525eefb8c860bed0`。原prompt版本与格式候选决定没有改变：v0/v1/v2分别保留原`localization-prompt-v1/v2/v3`来源。

## 工程变化

| 项目 | 结果 |
|---|---:|
| 历史run / 方法 | 26 / 75 |
| 原A结果保留 / 检测关联回放 | 23 / 52 |
| 方法状态变化 / 主体关联状态变化 | 0 / 1 |
| 自动selected ID变化 | 0 |
| 候选数量或坐标变化 / 原标签字段变化 | 0 / 0 |
| 候选语义装饰变化的方法 | 5 |
| 候选label规范 / 复合label分解 | 1 / 3 |
| 语义query别名规范记录 | 4 |
| 新VLM / 检测推理 / 付费请求 | 0 / 0 / 0 |

语义装饰仅指派生候选的`target_level/semantic_source`，不改变来源候选。B02 v1 B1/B2及v2 B2的cup由instance关联为whole；C03 v1 B1记录语义关联来源；D03 v0 B1因复合标签解析后不再有唯一metal tool候选，撤销旧whole装饰，回到原检测instance。5项均保留空selected ID，不能称为主体选择正确。

原23条A中的JSON错误、截断、综合schema/框错误及合法输出全部原样。源记录的13次success、6次json_error、3次box_format_error、1次truncated保持不变；不把旧失败的原文重新解析成成功。

## 五图重点对照

表中候选数为v1 A/B1/B2顺序，表示合法候选数量而非TP。A的status与selection均沿用历史；完整任务质量未评分。

| 样例 / 原完整任务 | 候选数 | B1旧→新 | B2旧→新 | 修复后仍保留的范围与退出条件 |
|---|---|---|---|---|
| B02 杯整体+杯中可见区域、透明边缘 | 2/1/3 | ambiguous→ambiguous | unsupported→unsupported | `water cup→cup`与`cup water cup cup→cup`恢复整体关联；内部区域不能冒充cup整体，原VLM part未满足独立region；实体physical不能凭类别强选 |
| D03 金属器具整体+可见部件、画面边缘 | 1/4/0 | ambiguous→ambiguous | abstained→abstained | 整体不能代替部件；部件完整清单unknown保留在分母，YOLO空结果及不支持诊断保留 |
| D07 两手+泥坯+陶轮可见区域 | 4/3/1 | ambiguous→ambiguous | unsupported→unsupported | hand最少2实例；同一候选不能绑定两手；陶轮whole未满足任务region；YOLO手/泥坯/区域不支持 |
| C03 人物候选+现场/描绘实体归属 | 1/1/0 | ambiguous→ambiguous | abstained→abstained | `person cartoon woman`完整拆分后关联恢复；描绘人物不规范为现场person；候选全集范围unknown及depiction身份门槛继续保留 |
| P06 人物实例+与周围景物尺度关系、无唯一主角 | 5/10/3 | ambiguous→ambiguous | ambiguous→ambiguous | 实例总数和尺度关系范围unknown；不以最大框、分数或主目标ID缩小全任务，空selected ID保留 |

五图v0/v1/v2和纯检测全部行在五图JSON/CSV中。B02 v0 pure / YOLO的单独状态变化保留3个原候选，新增`cup inside region`不支持诊断。没有将它改成成功，也没有删除原完整任务的区域要求。

v1派生run ID与直接JSON入口：

| 样例 | 新run ID | 派生记录 |
|---|---|---|
| B02（第一张） | `7e7f51a1bfd742e1af7bf1d57feaa91b` | [B02](C:/Users/丁铭哲/Documents/ChatGPT/摄影/xiaoli-camera-assistant/data/vision_lab/detector_experiments/preacceptance_20261013/replay/runs/v1/B02/paired/run.json) |
| D03 | `2b1c2520384c4910b85fe973113a06d1` | [D03](C:/Users/丁铭哲/Documents/ChatGPT/摄影/xiaoli-camera-assistant/data/vision_lab/detector_experiments/preacceptance_20261013/replay/runs/v1/D03/paired/run.json) |
| D07 | `2d344964e5ce46bdbcd19ec96dc4ad83` | [D07](C:/Users/丁铭哲/Documents/ChatGPT/摄影/xiaoli-camera-assistant/data/vision_lab/detector_experiments/preacceptance_20261013/replay/runs/v1/D07/paired/run.json) |
| C03 | `4603506f0f40479399eff662c2755672` | [C03](C:/Users/丁铭哲/Documents/ChatGPT/摄影/xiaoli-camera-assistant/data/vision_lab/detector_experiments/preacceptance_20261013/replay/runs/v1/C03/paired/run.json) |
| P06 | `39c17d287ff24761aab9cc16dd49b25d` | [P06](C:/Users/丁铭哲/Documents/ChatGPT/摄影/xiaoli-camera-assistant/data/vision_lab/detector_experiments/preacceptance_20261013/replay/runs/v1/P06/paired/run.json) |

## 新查询计划和人工评分边界

只有B02 v1/v2的别名合并生成了新查询计划：v1拟`[cup, cup inside region]`，v2拟`[cup, liquid in cup]`。计划字段固定`executed=false/new_inference_count=0`，本次实际仍使用原保存查询。新词组合影响DINO分数与候选，不能把已有候选的回放冒充新查询验证；内部区域的语义、层级和边界还需要人工确认。该计划未获得新请求预算，也未执行。

所有IoU、TP/FP/FN、召回、准确率、自动/人工主体正确率、查询/固定类覆盖、候选可用及完整任务成功均为null，派生`evaluations={}`。旧AI参考维持`annotation_source=ai/confirmed=false/complete=false`。范围解析只读取共同任务和保存语义，测试确认改变人工参考不会影响范围或关联。

## 验证与不可变性

运行`pytest tests/test_detector_preacceptance_replay.py`，17通过（最新0.33s）；Ruff通过。使用项目内TEMP/TMP和basetemp。完整导出测试以monkeypatch sentinel禁止HTTP、模型/worker、prompt重生成、VLM重解析与查询重组；脚本本身另有fail-closed离线guard。测试为合成离线测试，26条为旧真实记录复用，两者不混为新API验证。

逐字段验收26份任务/图片/配置/参考/VLM、52份检测及原查询、23份A原结果和362份候选的坐标/原标签/分数/class一致；26新run和75新MethodResult ID唯一。原实验836份文件在回放前后哈希全部一致，清单保存于`source_hashes_before/after.json`；请求ledger前后SHA256均为`5b6fd038199b6c6fb20a6af57317d26ac8004dc64f451f9b53412cc43c596851`。完整hash和断言结果见交付验收JSON。
