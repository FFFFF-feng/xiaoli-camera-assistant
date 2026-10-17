# C 摄影事实接入说明

## 版本和调用

保留 `photography-facts-v1` 的 frozen 字段和全部公开签名：

```python
build_photography_facts(request, scene, camera) -> PhotographyFacts
photography_facts(request, scene, camera=None) -> PhotographyFacts
use_photography_facts(facts)  # context manager
semantic_issues(text, facts) -> set[str]
reconcile_parameter_facts(recommendation, facts) -> CameraRecommendation
reconcile_composition_proposal(proposal, facts) -> tuple[CompositionProposal, list[str]]
reconcile_composition_facts(advice, facts) -> CompositionAdvice
preserve_continuous_framing(advice, facts) -> CompositionAdvice
```

现有 A 调用可直接沿用，必需的新调用 diff 为空。不能把参数和构图改成串行。事实的 ContextVar/copy_context 传播、snapshot/ready/汇合检查仍使用同一不可变实例；重复校验必须幂等。全部修正都是本地检查，无新增模型请求。

输入仍为 UserRequest、SceneAnalysis、已解析器材目录；输出不改变公共 schema 或几何。`motion` 在用户没有明示时为 `unknown`，不把 scene 的估计升级为事实。结构化运动状态优先；仅识别有限的用户肯定陈述（例如“狗正在快速奔跑”），假设、问句、否定不作证据。

`declared_light` 仍为 str/None：可以保留原 broad lighting_type；明确的用户灯种陈述归一为 `tungsten`（含白炽灯）、`fluorescent`、`led`。只有同一具体灯种才支持相应断言，natural/continuous_artificial/mixed/flickering_artificial 不确认钨丝灯。图像 lighting 标签不充当光源实测证据。

`white_balance_goal` 同时出现未选择的保暖/中和比较时为 unspecified；`white_balance_instruction` 不替用户自动选择中和。生成目标确定时，参数值和构图文字统一使用该字符串，保留无关对焦/边缘检查。

## A 必须保留的既有调用顺序

1. `pipeline.py`：两个分支启动前构建一次 shared_facts，以独立 copy_context 传播；参数验证后、构图 snapshot/ready/返回与汇合仍复核同一事实。
2. `composition.py::_resolve_intent_layout`：continuous 场景先 `preserve_continuous_framing`，再 `_validate_advice`，之后才 `solve_layout`；生成板后再校验。C 只处理文字与已有 intent，绝不生成轮廓或伪造新视角。
3. `composition.py::_validate_advice`：继续把 framing/sketch/storyboard 文字交给原 `composition_issue`。不能先抹掉未经测量的精确距离再让方案通过。两项原有距离拒绝回归已保留。
4. `reconcile_composition_facts` 已覆盖 proposal 可见文字和顶层 observations；layers/elements/来源编号/几何不修改。错误观察被改为条件式建议，并加 notes，不能视为视觉识别或整体摄影正确性认证。

## 如需覆盖 scene 卡片，交 A 的最小建议差异

C 不拥有 SceneAnalysis 的生成与发布；最终 `result.scene` 和 scene partial 仍可能显示视觉分类的运动/光线估计。建议 A 在 `pipeline.py` 目前 `publish_partial("scene", scene)` 前标明其估计性质，并把原约326行 shared_facts 的构建前移到该处（保留唯一实例，不重复创建）：

```diff
 # scene normalize 和用户明确运动覆盖完成之后
+shared_facts = build_photography_facts(effective_request, scene, camera)
+estimate_notes = []
+if shared_facts.motion == "unknown" and scene.subject_motion != "unknown":
+    estimate_notes.append("画面中的运动状态为模型估计，未获用户确认；快门建议需现场试拍核对。")
+if shared_facts.declared_light not in {"tungsten", "fluorescent", "led"}:
+    estimate_notes.append("画面色调与光线描述不确认具体灯种，光源类型需现场核对。")
+if estimate_notes:
+    scene = scene.model_copy(update={"uncertainties": list(dict.fromkeys([*scene.uncertainties, *estimate_notes]))})
 publish_partial("scene", scene)
 ...
-shared_facts = build_photography_facts(effective_request, scene, camera)
 # 保留下面两个并行分支对 shared_facts 的闭包引用
```

这是给 A 审查接入的建议，本分支未修改 pipeline.py。若 A 接入，需要补 scene partial/final 一致性的测试；本报告不声称它已经执行。更广泛的 scene 自然语言事实推断仍需生成端与 UI 明确标识不确定性。

## 边界

- 镜头 IS 没有进入 v1 frozen 字段，当前只接受“确认镜头支持时”的条件式指导；不能从机身 IBIS、焦距或镜头昵称推断镜头 IS。未来如传入已核实镜头能力，应先由 A/C 版本化接口，而非猜测。
- 当前规则是有限关系检查，不能保证任意摄影语言均正确。新增灯种、复杂双重否定、多重替代、跨段落共指仍可能漏检或过于保守。
- 四图真实上传、画面可辨性、性能与上线均由 A/E 后续验证；本分支不合并、不 push、不部署、不启停共享服务。
