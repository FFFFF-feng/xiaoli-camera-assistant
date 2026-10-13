# 定位验收前置修复与人工确认交付

2026-10-13，北京时间。**程序修复、已有结果离线对照、五图确认包和保存/重开验收已完成；人工确认与定位质量评分尚未进行。** 本次新增付费API请求0、本地检测推理0、模型下载0，未续用上一轮剩余7次请求预算。

## 交付入口

- [五图中文人工确认页：B02先看](http://127.0.0.1:8766/preacceptance_20261013/confirmation_package/index.html)
- [本地HTML及所有图片/JSON](../data/vision_lab/detector_experiments/preacceptance_20261013/confirmation_package/index.html)
- [可编辑历史映射：版本、规则、run_id、方法、照片](../data/vision_lab/detector_experiments/preacceptance_20261013/history_registration_final/history_mapping.md)
- [最终离线比较JSON](../data/vision_lab/detector_experiments/preacceptance_20261013/replay_final/replay_comparison.json) / [CSV](../data/vision_lab/detector_experiments/preacceptance_20261013/replay_final/replay_comparison.csv)
- [最终交付断言与文件哈希](../data/vision_lab/detector_experiments/preacceptance_20261013/delivery_acceptance.json)
- [下一轮独立新图方案及待授权预算](detector-independent-validation-plan-2026-10-13.md)

在[8502工具](http://127.0.0.1:8502/)选择“检测与联合定位”，重开 **B02 / v1 / original** 的确认副本 `26eb2769a600470194ffc87b58fb0a13`。它已经带有完整AI参考，无需再次运行模型。下拉显示完整实验版本、原/修复关联规则、参考版本与run前缀。

最终有效文件夹是 `replay_final/` 和 `history_registration_final/`。关联规则 `conservative-association-v4`，范围规则 `explicit-task-units-v3`，词典 `task-english-v2`，标签规则 `complete-query-phrase-v1`，评测类别口径 `human-correspondence-class-level-entity-v2`。可执行规则包SHA256：`05f224d8f7485e3d03fa8a990910984a3276f882406d6f4da18968936cd3a351`。

审查修复前的 `replay/`、`replay_v2/` 及对应历史仍作为可恢复中间快照保留。三批累计120条派生历史是数据版本，不能当120次模型试验。最终映射只采用40条：26修复回放+14五图原规则确认副本，共115方法行；UI明确说明派生版本不是新请求或独立图片样本。

## 程序修复

旧 `_associate()` 把全部非COCO语义对象写入阻断列表。固定cup候选和主cup语义原可选中，添加非主体rock背景就变为unsupported；已先建立不联网失败复现，再修改。

范围解析现在只读实际共同任务和已保存语义，不接收人工参考、图片文件名、框面积或分数。区分 `main_target / required / auxiliary / background / unknown`；主目标ID只能标角色，不能定义全部任务必需单元。背景unsupported留在关联诊断，不阻断已支持主任务；必需岩石、手、泥坯、部件/区域仍记录unsupported和完整库存。多必需目标缺语义或缺可靠唯一候选，不判完整selected。

杯中区域、可见部件清单和双手分别保留要求。未知并列目标放在前后位置、未知主目标旁有已知上下文、显式数量、整体的部件修饰与未消费的目标描述均保守退出。词典及任务语法有限，无法确定的范围保持unknown，不因为只识别出cup就删除难目标。

通用别名仅做完整短语规范：`water cup / water cups / cups → cup`。DINO复合label必须由实际保存的完整查询或固定完整别名全部分解，不能子串匹配。原label不改，规范label/分量/规则/依据存于 `queries.label_normalization`；语义原query和规范query也分别记录。

`cup inside region`不充当cup整体，绘制人物不转成现场真人，多同类实例不强绑，整体/部件不替代。已知实体归属不能仅凭类别自动选中，策略未放开，也没有让VLM一律填unknown。

独立只读审查确认了未知前置目标漏掉、数量压缩、部件替代、明确背景尾项误阻断，以及关联/评测类别口径不一致五项边界缺陷；另补未知后置目标描述的保守退出。均有失败→修复→通过证据。评测现在只对分量均归一到同一类别的复合label采用一致类别口径；混合身份/类别/区域仍拒绝配对，不改原label，不找最大IoU。

提示词原文、schema、阈值、尺寸、权重和后处理未改。页面下一次显式定位请求默认选择上一轮 **v1格式候选 `localization-prompt-v2`**；v0/v2仍可切换恢复，控件不改写旧历史冻结提示。这只是已有格式证据，不宣称定位质量验证。

## 同源离线对照

26条旧run、75方法行：52检测关联重放，23份A原结果/原失败原样保留。VLM、实际查询数组、检测输入/原始候选、配置和阈值全部复用；只补共同任务文字与新规则诊断。新run/result ID引用原run/result/detection/VLM ID、来源文件与规则哈希。未重解析或修补旧回答，未覆盖旧失败。

| 项目 | 最终变化数 |
|---|---:|
| 方法执行status | 0 |
| 主体选择status | 1 |
| 自动selected ID | 0 |
| 候选坐标 | 0 |
| 候选原label | 0 |
| 候选语义层级装饰 | 5 |
| 规范候选label / 复合label分解 / 语义query规范 | 1 / 3 / 4 |

唯一状态变化是 **B02 v0纯检测YOLO：abstained→unsupported**：原完整任务还包含杯内区域，旧词典只留下cup。此变化揭示限制，没有增加成功数。5项候选语义装饰来自更完整/更严格的关联；362候选的坐标、原label、score和class逐字段一致。

| 五图v1原完整任务 | A/B1/B2合法候选数 | 诊断与仍待确认事项 |
|---|---|---|
| B02 杯整体+杯中可见区域 | 2/1/3 | 别名与复合label恢复整体关联，内部区域仍缺正确层级；B2仍unsupported。透明边界、内容/杯口解释待确认 |
| D03 器具整体+可见部件 | 1/4/0 | VLM v1只留整体，部件完整清单未知；整体不能替代细杆/盒体/四管。可见整体与父子归属待确认 |
| D07 两手+泥坯+轮面 | 4/3/1 | 手实例/层级与轮面区域不完整关联；YOLO必需类别不支持。手腕、泥坯/承托盘、轮面边界待确认 |
| C03 人物候选与实体归属 | 1/1/0 | 复合label恢复候选关联，depiction身份门槛仍退出。描绘人物边界与父对象待确认 |
| P06 全部人物实例、无唯一主角 | 5/10/3 | 不按前景、最大框或高分强选；可辨人物、两个疑似/ignore区域和完整人数待确认 |

候选数量不是TP，程序变化不是准确率改善。任务类别不同，当前不能宣布一种检测器全面更好。需要改变真实DINO发送query的别名合并仅作为 `executed=false` 计划；旧查询原数组保留，回放不能验证新查询影响。

## 五图确认包与可重开记录

共32项AI草稿，27项暂定required（含P06两项ignore/存在不确定），全部 `annotation_source=ai / confirmed=false / complete=false`。原10图119项草稿保持原样。这五图已有曝光，只用于已有结果诊断，不是全新盲测。

| 图 | 草稿/必需项 | 内容 |
|---|---|---|
| B02 | 3 / 2 | 整体、内容区域、杯口独立备选解释 |
| D03 | 9 / 7 | 整体、盒体、细杆、四管、开口、组合范围 |
| D07 | 4 / 4 | 两手分别、泥坯、轮面区域 |
| C03 | 2 / 1 | 描绘人物候选、广告牌上下文 |
| P06 | 14 / 13 | 人物实例、两项待判定/ignore范围、尺度上下文 |

每图有原图、方向修正图、实际发送JPEG、原图/发送图编号草稿、每对象放大、简明中文确认表CSV/JSON、标准DetectorReference根对象 `reference.json` 和图哈希/来源manifest。模型预测在独立 `predictions.html`，不回灌参考。

| 图 | v1原规则可编辑确认副本run_id | v1最终修复副本run_id |
|---|---|---|
| B02 | 26eb2769a600470194ffc87b58fb0a13 | 8bb2a5e096db4de8846b89ed7274d4e0 |
| D03 | 76984d833e9d4074b40dec35fe7258b6 | a65cdcbfb1b34f3c8294aa780fd20312 |
| D07 | defc4ee38c724d13bd55e2561220f0e2 | 3843dabedde64a84ab9c99ecbb8ef30e |
| C03 | 21f0911a400340ebbd7a899d6f5dda9a | d6a667f8e0b64d66adf3001fac4e86f9 |
| P06 | 3823177e41ee4db7b8d77015560f7a20 | 8d34bd7cdb154f7589cf9f79ee13d497 |

每个paired记录含A/B1/B2；完整v0/v1/v2/纯检测记录、result_id与照片绝对路径见最终映射。两种规则同图使用逐字段相同的冻结AI草稿；尚未收到人类确认。

参考JSON可直接粘贴当前“参考框 JSON”，没有把外层ai-reference-draft当UI契约。原/发送JPEG摘要是文件字节SHA256；`corrected_sha256`沿用RGB尺寸+像素摘要，另存PNG文件摘要，不混称。

## 人工确认、保存与评分门槛

JSON导入/表格编辑只改草稿；粘贴 `confirmed=true` 也不授予人工确认，confirmed/source列不直接编辑。明确选择gt_id、填写用户原文及修订理由，再点“确认所选对象与边界”，才记录对应对象。来源为 `ai_reviewed_by_human`，不可变ai_draft继续保留；日志记录字段、原文、时间、图像哈希、参考版本、对象摘要和理由。

只确认B02整体时，其余项及未提及字段保持待定，不能把“整体挺好”当整批确认。仅部分字段确认时保留备注、confirmed=false；实体可继续unknown。库存不能删除或直接降required来解锁原完整任务；更小诊断或有真实人类证据的范围修订应建立独立evaluation_scope/参考版本。工具当前不支持部分参考质量评分，因此部分确认继续未评测。

保存创建新run_id，引用父记录，原JSON/照片不覆盖。旧历史继续可读。空complete参考、缺库存、无真实来源的AI确认标志与无确认日志的AI配对都不能解锁评分。合法一对一配对另填写原文/理由并确认，不复制预测/GT对应，不自动找最大IoU。

人类确认后，同图A/B1/B2及原/修复规则需同步同一冻结参考与来源日志，配对分别确认。当前没有真实人工照片确认，冻结人类参考同步、IoU/TP/FP/FN/准确率/召回/完整任务成绩与质量路由结论均未执行。

## 验收、保存范围与下一阶段

全项目pytest **435通过、1跳过（65.88秒）**；随后针对实际大历史修正导出时机，**21项UI回归全部通过（29.40秒）**，Ruff通过。使用项目内TEMP/TMP、独立basetemp及UTF-8。首次全量检查中一个旧测试默认GBK读UTF-8配置失败，日志保留；统一UTF-8后通过，未为此修改旧测试。Streamlit AppTest在沙箱内的socketpair受限，诊断后仅对本地离线回归使用许可的执行环境，没有真实请求。

实际150条历史的JSON/CSV分别约189MB/109MB；原页每次渲染都提前生成，离线实测仅序列化就耗16.37秒/11.96秒。已在当前Streamlit 1.65的已核验callable下载接口上改为点击时生成，重开不先生成全部导出；更旧版本保留原bytes契约。新增失败→通过测试同时验证下载回调不会推理。此改变只调整导出时机，不改内容或任何旧结果。

实际浏览器已重开B02副本，原完整任务、草稿叠框、确认入口和complete=false均可见。参考页有32行确认表与20图像资源；模型预测独立视图可查看，40引用采用延迟加载。21个UI回归测试覆盖导入、表格、叠框、保存、重开、版本切换、导出不推理。仅重启已核验路径/端口的本项目8502；8766预览只绑定127.0.0.1。

交付检查验证原实验836文件、原历史56文件、84个包来源、82个包产物摘要不变；119原草稿保留。最终40条记录和照片可重开，115方法行全部scoring_ready=false、质量字段None；当前完整规则哈希与最终快照一致。原请求台账SHA256仍为 `5b6fd038199b6c6fb20a6af57317d26ac8004dc64f451f9b53412cc43c596851`。AI几何与工程统计不当人类准确率。

本轮未编辑app.py、camera_assistant主流程或四模型旧历史。交付期间主应用存在并行修改，已保留，不能归为本轮检测验收集成。已有README/.env.example/.gitignore和未提交工作保留，未提交/合并混合工作；独立检测环境保留。

下一轮方案建议另授权12张独立新图、12次共享VLM、24次本地检测、0云检测，先核实单价与金额上限。该预算仅为方案，本次授权额度仍为0。当前待办为用户真实确认、冻结参考及合法配对，随后统一评分。
