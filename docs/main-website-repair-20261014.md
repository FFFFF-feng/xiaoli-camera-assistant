# 主网站建议审核修复与验证记录

> GitHub 阅读说明：本报告记录本地验收。`data/history/` 下的原始回答、截图、日志和数据库不随仓库上传，相关相对链接仅在保留这些证据的本地工作区可用。公开版本边界与复现条件见 [开发版本说明](github-development-snapshot-20261015.md)。

2026-10-14，Asia/Shanghai。主入口 `app.py`，主生产流程 `CameraAssistantPipeline`。起始提交为 `13ca11b589ac650ef76be20916c82e381a4cb5fa`，修复留在工作区，未提交或重置 Git。

起始六个未提交文件（README、app、CSS、pipeline、两个页面/生产流程测试）的进度反馈等修改已阅读并保留衔接。未发现适用 AGENTS.md。`vision_lab.py` 与 `src/vision_lab_tool` 冻结逻辑无修改；未修改、发布或自动审核知识卡。真实轮主库逻辑内容前后相同，0 已发布、0 知识命中。

## 1. 修改与对应错误

- `models.py`、`services/exposure.py`：新增模式 M/Av/Tv/P/unknown、ISO manual/auto/unknown、参数角色 manual_setting/auto_target/observed/not_applicable/unknown。用户当前设置、建议、镜头最大光圈和参考照片 EXIF 分开记录，模型自报状态不能覆盖程序审核。
- `services/validator.py`：联合审核模式与 ISO，完整解析光圈、快门与 ISO 字段；光圈所有区间端点受镜头能力限制，纯 `4.0` 规范为 `f/4`。未知或矛盾字段不通过改数字变成确定事实。M＋固定 ISO 不提供有效 EV 操作，重建快门/光圈/ISO 调亮暗步骤；不能仅将 EV 改为 0 后留下原理由。
- 已核验 Canon EOS R50 的 M＋Auto ISO 支持非闪光曝光补偿，保留 ISO 响应与边界条件；未核验机型保持未知。Av/Tv/P 明确相机自动参数与用户控制；ISO 改变可能被自动参数抵消，不描述为独立调亮暗旋钮。[R50 M 手册](https://cam.start.canon/en/C011/manual/html/UG-03_CustomShooting_0050.html)、[Av 手册](https://cam.start.canon/en/C011/manual/html/UG-03_CustomShooting_0040.html)、[Tv 手册](https://cam.start.canon/en/C011/manual/html/UG-03_CustomShooting_0030.html)。
- 基础理由、相关风险与步骤按操作域由程序生成，覆盖景深、运动模糊、曝光、对焦、测光、驱动、白平衡。提高 ISO/加快快门不直接减小光学景深，电子快门/前帘不作为 IBIS。未分类旧文字不因此成为已验证事实。
- `candidate_models.py`、`services/advice_review.py`：候选操作明确控制项、对象、效果、前提、原文依据；程序核对控制角色、物理关系与独立输入。自报依据、合法 JSON、照片模型声明、类别框不证明真实实体配对或建议正确。可选候选元数据不合格时隔离并标未审核，避免拖垮独立有效方案；模型自报 reviewed_operations、safety_notes、validation_notes 均不作审核证明。
- `photography_targets.py`、`localization.py`：分开主体、数量/身份、保护、成像目标与输出请求，保留原文跨度。完整窗框保护与树林层次关系分开；保留主体的请求仍有主体约束。位置要求记录为未核验 location_identity，真实多候选、解析未知、数量/语义覆盖、反射身份各自记录，不按分数或面积强选。
- `composition.py`：裁切检查选中主体及明确要求完整的另外保护对象；环境关系无法凭框证明时明确待预览。仅对端点恰好等于原框四位小数舍入的情况向外修正，不使用宽泛容差。检测只覆盖当前可见内容，不能恢复或保证遮挡身体完整。
- `pipeline.py`、`advice_safety.py`：在最终数值确定后审核理由、风险、步骤和构图条件；成功阶段保留。机位方向转为现场比较，不透传确定效果或未经测距的幅度；光圈操作伪装成焦段方案时同步改类型/目标。用户未确认运动时最终速度为 unknown，不由单帧拉丝外观确定真实速度或原曝光因果。
- `app.py`：保留已有进度反馈，读数标明用户设置/自动控制目标/需确认；取消建议及场景置信度百分比。候选观察与规则检查不展示为实测正确率。8501 已核对项目进程并重启加载最终源码，health=200/ok。

## 2. 验证与证据链

先阅读并核对 [原报告](../data/history/main-round-20261014-105503/report.md)、原 raw、structured、pipeline，先离线回归后执行一轮真实模型与 DINO。

最终完整测试：**933 passed，1 skipped**，跳过 `test_knowledge_importer.py:224` 为本机未授权创建符号链接。修改范围 Ruff 通过，`git diff --check` 通过。测试包括未知模式、M 固定/自动 ISO、Av/Tv/P、数值修正后联动、候选元数据容错、未见过的表达和反例、窗框/身体保护、背景分离、数量、位置与反射关系，以及正确裁切与有效操作的保留。

独立代码复核发现的未校验快门角色问题已补红/绿回归并修复：无效快门同步为 unknown，相关候选不能获审核通过，步骤先确认有效曝光时间。见 [代码复核](../data/history/main-fix-final-20261014/code-review.json) 与 [最终逐图复核](../data/history/main-fix-final-20261014/final-review.json)。

[最终测试日志](../data/history/main-fix-final-20261014/pytest-final.log)。命令：

```powershell
.\.venv\Scripts\python.exe -m pytest --basetemp tmp/pytest-final-audit-36 -q -rs
```

原基线回答最终离线回归见 [main-fix-offline-final-audit-20261014](../data/history/main-fix-offline-final-audit-20261014/summary.json)：30 次回放，0 新 API，保留原有 2 超时与 4 连接失败，成功阶段未被重做或丢弃。

真实轮见 [main-fix-live-20261014-125300](../data/history/main-fix-live-20261014-125300/summary.json)：原 P01–P10 原图、原受控请求、GLM-4.6V、DINO CPU/同 revision/同阈值、120 秒超时、4096 输出 token、相同 thinking 配置。10 张原图 SHA256 及实际送入模型的 JPEG 哈希与基线一致。用现有安全密钥配置；日志未记录密钥或请求头。

本轮启动时载入的代码遇到 6 个阶段审核失败：构图 P01/P08，参数 P02/P06/P07/P09。原因均为可选候选依据 source 写成 localization/scene/scene_analysis，被起始严格枚举拒绝，**不是运输失败，也不是合法 JSON 就说明建议可用**。详见 [阶段审计](../data/history/main-fix-live-20261014-125300/stage-review.json) 与 [逐图视觉复核](../data/history/main-fix-live-20261014-125300/composition-review.json)。

发现问题后修复候选隔离与最终说明审核，保留真实原始回答和真实 DINO 结果，执行零 API 重审，结果见 [main-fix-final-20261014](../data/history/main-fix-final-20261014/summary.json)。最终版没有再发送第二轮完整模型请求；新增真实调用为 0。真实轮与最终重审各自保存源码哈希，不能把最终重审冒充新一轮真实生成。最终 10 张都保留构图方案及参数对象，但 P02 参数对象仍缺少可校验快门与明确 ISO，不能把对象返回数视为完整可用率。

重新执行：

```powershell
.\.venv\Scripts\python.exe scripts/replay_main_round.py
.\.venv\Scripts\python.exe scripts/reprocess_live_round.py --baseline data/history/main-fix-live-20261014-125300
```

真实运行脚本为 `scripts/run_main_round.py --live`；它只复用主生产流程和安全配置，克隆知识库当前逻辑状态，不模拟发布；仅原有格式重试，单阶段最多 2 次请求，不重做成功的整个流程。

## 3. 修复前后具体对比

| 案例 | 修复前证据 | 最终处理 |
| --- | --- | --- |
| P01 | 将最大 f/4 当当前值；低机位保证放大眼睛 | 当前光圈保持未知，最大光圈独立能力；保留降低相机的试取景方向，比例/背景须比较，最终 Av 快门标自动目标 |
| P02 | M＋手动 ISO400–800 仍微调 EV；构图快门条件分裂；问句当主体 | 原回答离线 M/固定 ISO 的 EV 不适用，步骤改真实控制项且条件同步；新真实回答改选 Av，但 ISO 自报“自动或手动”、快门不合规范，明确未确认；人物保留要求与真实多候选分开 |
| P03 | 提高 ISO/加快快门减小景深；后退保证层次；缩光圈却标焦段方案 | 基础物理说明重建，快门/ISO不直接变景深；机位变现场比较；实际光圈操作归重拍并改理由、目标与条件 |
| P05 | 鸟轮廓/背景分离问句当未知主体 | 主体鸟、完整身体保护、背景分离目标、重拍请求分别保留；同保存语义/框由 ambiguous→selected；新 `4.0`→`f/4`，裁切仅保全当前可见范围，不保证遮挡脚部完整 |
| P07 | 凝固骑行动作当未知主体，参数阶段失败 | 人物＋自行车完整主体集合；凝固为目标。新回答重审为 Tv、1/500s、Auto ISO，光圈为自动目标，机位/裁切不能替代快门控制 |
| P08 | M＋ISO100 用负 EV 防灯光过曝；低机位保证减少天空高光 | 固定 ISO 的 EV 不适用，缩短曝光/调整光圈或ISO，试拍看高光；只保留相对试取景，去未测距离和保证高光效果 |
| P09 | 未证真人与倒影配对，电子快门当手持防抖 | 原配对方案移除；反射身份继续 ambiguous。取舍/条件与最终参数同步，去防抖与串入的猫细节；保留靠近玻璃试取景但不保证效果 |
| P10 | 固定 ISO 负补偿调亮暗；ISO 降进光量；四位舍入误拒绝 | M/固定 ISO 重建操作；ISO只影响记录亮度/相关画质，不改变入射光量；裁切端点精确向外修复并保留，树林层次需预览；未确认速度为 unknown，去慢门原参数因果 |

逐项查看最终 `Pxx-pipeline.json`；`*-parameters-structured.json` 是模型候选，不能当最终审核说明。原基线与真实 raw 不曾被改写。

## 4. 真实调用、失败和耗时

本次真实调用 **30 次**（视觉 10、构图 10、参数 10），DINO 重新执行 10 次。运输失败 **0**，超时 **0**，连接失败 **0**；格式重试 **0**。30 份返回合法 JSON 是格式统计，未计算建议正确率。

真实总耗时 **1465.018 秒（24 分 25 秒）**，每图中位 **127.0035 秒**，最长 **238.504 秒（P03）**。初始阶段错误 6 个已在零 API 重审中隔离修复，未篡改初始错误记录。最终零 API 重审约 1.485 秒，不计入真实模型性能。

| 图片 | 真实耗时（秒） | 启动时载入代码的阶段失败 |
| --- | ---: | --- |
| P01 | 122.954 | 构图候选元数据 |
| P02 | 184.147 | 参数候选元数据 |
| P03 | 238.504 | 无阶段失败 |
| P04 | 204.347 | 无阶段失败 |
| P05 | 92.523 | 无阶段失败 |
| P06 | 131.053 | 参数候选元数据 |
| P07 | 69.398 | 参数候选元数据 |
| P08 | 105.360 | 构图候选元数据 |
| P09 | 206.805 | 参数候选元数据 |
| P10 | 109.865 | 无阶段失败 |

## 5. 仍未解决或必须现场核对

- P02 新模型回答的快门未通过完整数值解析，ISO 自动/手动不明确；程序明确缺失，未猜成固定或自动。重审恢复参数对象不等于恢复了有效完整曝光方案。
- P03 `scene.environment=outdoor` 是未独立核验的宽泛视觉分类，未硬改为确定室内。室内窗视点与窗外风景的关系仍需补充现场信息，不能声称全部视觉事实已修复。
- 多实例、全部人物、悬崖位置身份、反射配对和遮挡身体仍保持保守状态；DINO 类别框不证明身份或完整可见实例集。窗框完整保护缺唯一几何时裁切弃权，环境层次关系保留现场比较。
- 意图解释器和操作域审核都是有界实现；未支持的表达保留原文/未知状态，不宣称能理解所有自然语言或验证所有旧自由文字。M＋Auto ISO 仅当前已核验机型能力分支可用，未知机型须核对。
- 本次是 10 张受控输入、一轮模型生成及其最终规则重审；没有独立人工摄影效果真值或实际重拍。合法 JSON、规则通过、知识引用和模型置信度均不代表建议正确率。

主网站 [http://127.0.0.1:8501/](http://127.0.0.1:8501/)，重载证据见 [server-reload.json](../data/history/main-fix-final-20261014/server-reload.json)。
