# C 摄影事实与建议一致性交付报告

角色与状态：**C / DONE（本角色本地实现、回归和交付）**。整体集成、scene 卡片估计标识及真实画面验收仍依赖 A/E；未宣称全项目测试或真实画面全部通过。

工作树：`C:\Users\丁铭哲\Documents\ChatGPT\摄影\xiaoli-photography-consistency`

基线：`986fd0594150dce96b3255c8cc77ff54e8174620`。分支：`codex/photography-consistency`。

代码有序提交：

1. `32babd2206a8819d0fafff60b14a60ef68acd659` — 事实来源、条件/否定范围、白平衡目标、连续取景、fixture 与 Ruff。
2. `081ffcca676a60f4adb5e19b3063d3f8f874c608` — 顶层构图 observations 的未确认事实降级及回归。
3. 本报告及 C 接入说明的文档提交随上述提交链交付；完整范围为 `986fd0594150dce96b3255c8cc77ff54e8174620..codex/photography-consistency`。文档自身 SHA 在最终聊天及协调包同名报告补全，避免在已提交文件中写入自引用 SHA。

必须按顺序整合完整链，不能只摘最后一个文档提交。本分支未 push、合并、部署或修改 A/D/E 所属代码。

## 继承与修改范围

继承检查点的 frozen PhotographyFacts、共享 ContextVar、生成约束、参数/构图汇合检查、continuous 保留取景，以及原有 46 项摄影事实回归；没有重写流水线或从旧 main 开始。

只修改：

- `src/camera_assistant/services/photography_facts.py`
- `src/camera_assistant/services/advisor.py`
- `src/camera_assistant/services/validator.py`
- `tests/test_photography_facts.py`
- `reports/C-实施记录.md`、`reports/C-跨模块接入说明.md`、本报告

检查了 `启动项目.cmd`、`scripts/launch_apps.py`、`scripts/launch_web.py`；本轮没有入口、依赖、配置或端口变更，不修改这些 A 所属文件。真实云完整请求 **0**，内部模型请求 **0**。

## 已证实根因与修复

1. 原条件逐逗号切开，令“若机身支持 IBIS，可开启……”失去条件；宽泛否定又把“开启机身防抖不能替代高速快门”中的肯定开启动作一并豁免。现在分别判断条件对象、支持的正负方向、使用动作与后续效果；条件只跨逗号，不跨分号/句号/转折。机身 IBIS 条件不能授权镜头 IS。
2. 原文本修正统一用分号拼接，第一次修正另一个错误后会破坏有效条件，第二次复核又误删。现在保留原标点作用域，覆盖混合有效条件与错误因果的幂等回归。
3. 原钨丝灯暖色检查把“在钨丝灯下用自动白平衡氛围优先保暖”也当作错误。现在区分光源描述与钨丝灯预设，保留正确否定/条件句；保暖、中和与尚未选择的比较目标分开。参数值、理由、构图和 Demo 使用同一目标；修正某个白平衡子句时保留奶泡对焦/杯沿检查。
4. 原目标判断未正确限定带主语的否定（例如“我不想保留暖色”），会把被否定的目标与选定目标并列。现在只移除被否定目标；尚未选择的保暖/中和比较为 unspecified。
5. 原 scene 运动标签直接进入事实；原 broad lighting_type 非空时又可放过具体灯种断言。现在结构化用户状态优先，有限的用户肯定陈述可作依据；scene 标签仍为估计。natural/continuous_artificial/mixed/flickering_artificial 不证明钨丝灯或 LED；问句、假设、否定不构成声明。用户明确声明钨丝灯/白炽灯时保留相符断言，不接受另一灯种。
6. 原建筑检查跨整个 proposal 混合比较与执行指令，既可能误杀两个替代方案，也可能被一个比较句豁免真正矛盾的动作。现在比较文字和当前动作分别判断；主体自身对称不等于画面中轴对称。需要纠正时在布局求解之前将 intent 改回 keep，清除不可校正的旧 provider 板并说明取舍；不伪造对称几何。
7. continuous 保留取景时原过滤会删除“不要靠近”“不必强行三分”等正确边界，而且嵌套说明仍可能承诺新机位。现在保留否定边界，对嵌套文字按原取景说明；不改 layers、来源、坐标或轮廓。短字段容纳不了完整修正时明确降级，不截断成一个未经验证的句子。
8. 顶层 observations 原本绕过 proposal 校验，现在同样将未确认的摄影断言改为条件式核对建议并加 notes。无问题文字不因此获得“摄影正确”认证。
9. Ruff 13 项已修正。没有直接删除 F401 fixture：原真实 pytest fixture 对象通过 `pipeline_fixtures.settings/image_content` 显式绑定到模块属性，pytest 仍能发现别名；F811 的导入遮蔽消除。实际夹具和并行/ready 测试已执行。

器材事实复核采用佳能官方[EOS R50 规格](https://downloads.canon.com/ow/camera/EOS-R50-Spec-Sheet.pdf)和[镜头 IS 手册](https://cam.start.canon/en/C011/manual/html/UG-05_Shooting-1_0320.html)：R50 无 IBIS；镜头 IS 要求实际镜头支持。没有新增未经核实的机型条目。佳能[白平衡说明](https://cam.start.canon/en/C004/manual/html/UG-03_Shooting-1_0110.html)区分自动氛围优先与白色优先，不能把灯种和预设效果混为一谈。

## 正反例与验证

| 检查 | 保留的正确例 | 拒绝或降级的错误例 |
| --- | --- | --- |
| 快门因果 | 高速快门降低抖动；不能说高速快门降低稳定性 | 高速快门降低取景稳定性/增加抖动 |
| 未知器材 | 若机身支持 IBIS，可开启；镜头支持时使用镜头 IS | 未知机型已具备/已开启 IBIS；否定支持条件授权开启；机身条件授权镜头 |
| 主体运动 | 若现场确认运动，再使用较快快门；用户明确快速奔跑 | 从未知运动或 scene 估计直接断言主体正在高速运动；用防抖凝固运动 |
| 白平衡 | 自动氛围优先保暖；钨丝灯预设不保证保暖；用户明示灯种 | 钨丝灯预设保证保暖；保暖参数同时要求中和暖色；由照片偏暖判定灯种 |
| 建筑 | 两个替代方案；偏置牺牲中轴；主体自身对称 | 当前动作同时右三分与画面中轴对称，即使理由另有方案比较 |
| 二维边界 | 现场试移观察；不恢复画外内容；否定的移动边界 | 推荐图已消除遮挡/恢复未拍到杯底；旧精确距离仍走原拒绝规则 |

环境固定为原项目依赖目录加本工作树 src，实际 `camera_assistant.__file__` 已确认指向本工作树。没有向旧项目 src 导入或安装额外包。

```powershell
$env:PYTHONPATH = 'C:\Users\丁铭哲\Documents\ChatGPT\摄影\xiaoli-camera-assistant-latest\.launcher\python-packages;C:\Users\丁铭哲\Documents\ChatGPT\摄影\xiaoli-camera-assistant-main\.launcher\python-packages;C:\Users\丁铭哲\Documents\ChatGPT\摄影\xiaoli-photography-consistency\src'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$cPython = 'C:\Users\丁铭哲\Documents\ChatGPT\摄影\xiaoli-camera-assistant\.venv\Scripts\python.exe'
& $cPython -X utf8 -m pytest -q tests/test_photography_facts.py tests/test_validator.py tests/test_advice_physics.py tests/test_composition_advisor.py tests/test_real_pipeline.py tests/test_pipeline_parallel.py tests/test_completed_composition_progress.py tests/test_composition_intents.py --basetemp=.tmp/c-delivery --tb=short
& $cPython -X utf8 -m ruff check src/camera_assistant/services/photography_facts.py src/camera_assistant/services/advisor.py src/camera_assistant/services/validator.py tests/test_photography_facts.py
& $cPython -X utf8 -u .tmp/C-evidence/run-offline-tests.py -q --basetemp=.tmp/c-all-delivery --tb=short
```

- 基线：事实+validator **117 passed**；Ruff 确认原 6+7 项。
- 测试先失败：首组25个失败；只读审查6类 Important 对应8个失败用例；用户声明3个失败；顶层观察1个失败。修复后保留所有原事实测试，当前事实文件 **103项（原46+新增57）**。
- 最终关联回归：**316 passed in 32.96s**，包含真实模式的离线替身、参数/构图并行、完整图 ready/final 一致性；这不是云上传或画面质量验证。
- fixture 独立运行：两个共享事实/ready 测试 **2 passed in 1.00s**；它们也包含在316项内，不重复计入分母。
- C归属4文件 Ruff：**All checks passed**；没有运行全仓库批量修正。`git diff --check` 通过。
- 最终两个代码提交的全量回归：**1500 passed、1 failed、2 skipped、1 warning，137.34s**。唯一剩余失败为 `tests/test_launch_apps.py::test_forwarding_cmd_works_from_a_unicode_desktop_folder`，隔离工作树没有 `mobile/node_modules/vite`；warning为共享依赖Starlette使用AnyIO弃用别名。没有擅自安装或修改 D/A 依赖。
- `启动项目.cmd --check` 实际执行：退出1，同样报告“前端依赖尚未安装”。没有正常启动或重启服务；A应在集成环境完成前端依赖/构建及入口检查。
- 全量第一次在沙箱内阻塞于 Windows asyncio 的本地 socketpair，栈定位在首个 API TestClient 测试；已停止。全量重跑通过工具审批获得本地回环权限，并使用 `.tmp/C-evidence/run-offline-tests.py` 在进程中禁止非回环 socket 连接。没有通过放开外部网络调用云。
- 曾因新增文字修正抢先隐藏精确距离而使两个原构图拒绝测试失败，已撤去该处自动距离修正并恢复原校验链，两个测试已在最终316项内通过。首轮全量失败保留，不冒充首轮全绿。

## 四图旧真实结果的本地回放

读取了原报告、manifest、live_results、02/06/07/08 的 result/summary/events、02 ready、几何核对与 HTML 图集。仅从已保存的真实输出做本地语义重放，没有重新分析图像、重新分割、浏览器出图或上传。

| 样本 | 本地回放结果 | 原有效板数量→回放后 |
| --- | --- | --- |
| 02 狗 | 快门稳定性及 R50 IBIS 两项问题被修正，重复修正幂等 | 1→1 |
| 06 咖啡 | 参数与构图使用同一保暖指令，错误预设理由被修正 | 0→0 |
| 07 山湖 | 原来无方案仍无方案，没有编造山峰/倒影 | 0→0 |
| 08 拱廊 | 移除当前右三分/中轴对称冲突，保留比较说明 | 0→0 |

没有把零问题码等同摄影正确；例如建筑冲突属于 proposal 关系检查，不是 semantic_issues 的单句码。没有改变原四图失败分母，未将无图算作成功，也未宣称新模型、真实画质或端到端提速。

## 接口与 A 接入

公开签名及 frozen 字段保持 `photography-facts-v1`，现有 A 调用无需新增云请求或改串行。具体输入输出语义、既有调用位置和 scene 卡片最小建议 diff 见 `reports/C-跨模块接入说明.md`。

`composition.py`、`pipeline.py` 未修改。A需保留先共享事实/连续取景检查、再布局、再 ready 与汇合检查的顺序；scene 卡片仍属A，建议在原 `publish_partial("scene", scene)` 前用同一 shared_facts 标注运动和灯种估计的不确定性，再删去后面的重复构建点。该建议未接入，不能声称 scene 发布已经完成保护。

## 本地证据、资源和限制

证据根绝对路径：`C:\Users\丁铭哲\Documents\ChatGPT\摄影\xiaoli-photography-consistency\.tmp\C-evidence`。

关键证据：`red.txt`、`green1.txt`、`review-red.txt`、`review-green.txt`、`final-associated2.txt`、`delivery-tests.txt`、`full-sandbox-blocked.txt`、`full-offline.txt`、`full-final.txt`、`all-delivery.txt`、`launcher-check.txt`、`real-result-replay-final.json`、`replay_saved_results.py`、`run-offline-tests.py`。这些忽略目录文件留本机，原照片/云原始回复没有提交。

依赖、模型、GPU、共享服务、凭据与配置均无变化。真实云完整请求/内部请求均为 **0/0**，未触碰E云账本。

剩余风险：有限文本关系规则不保证任意摄影建议正确；跨段共指、复杂双重否定、其他灯种/表达仍可能漏检或误杀。未知镜头 IS 仍保守使用条件句；确认的镜头能力如要进入共享事实需版本化接口。scene 原始分类与更广泛的自然语言观察仍需要A明确估计来源；本轮未替代真实光照/运动测量。无图问题、狗耳腿球细节、几何和UI由A/B/D/E验收。A集成完整提交链后完成依赖、启动检查与E真实验收，不自行发布。
