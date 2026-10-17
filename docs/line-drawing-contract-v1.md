# 线绘并行修复接口 v1

本文件随 A 检查点冻结。具体提交见协调包 `BASELINE.json`，原工作树只由 A 写入。这里的 B 接口是待 B 实现的协议，当前产品仍使用 GrabCut；不能据此宣称学习型分割已经接入。C 的函数和 D 的几何字段已经存在。

## B：可选像素掩码接口 segmentation-v1

模块位置：`camera_assistant.services.segmentation`。B 在自己的工作树实现并导出以下不可变数据对象和运行时；不改公共 schema、像素追踪或依赖入口。

```python
@dataclass(frozen=True)
class SegmentationRegion:
    object_id: str
    bbox: tuple[float, float, float, float]

@dataclass(frozen=True)
class SegmentationResult:
    object_id: str
    status: Literal["success", "failed"]
    code: str
    mask: np.ndarray | None
    backend: str
    model_version: str
    weights_sha256: str | None
    device: str
    timings: dict[str, float]
    candidate_count: int
    selection_basis: str

class SegmentationRuntime:
    def segment_many(self, rgb: np.ndarray,
                     regions: Sequence[SegmentationRegion], *,
                     timeout_seconds: float = 10.0) -> list[SegmentationResult]: ...
    def close(self) -> None: ...
```

- 输入是方向校正后的 RGB `uint8` H×W×3；最长边由 A 现有调用选择（普通720，宠物/花细节最多1280），模型不能改用户原图或外层构图。输入尺寸至少8×8、至多400万像素；每批1–4个不重复 `object1..object6`。
- bbox 是相对于传入 RGB 的 XYXY `[0,1]` 可见范围，非 xywh/像素值。允许0/1边界与原照片截断，不自行补造杯底或肢体。区域应至少4×4个输入像素；非法输入明确失败，不夹紧到一个新框冒充原输入。
- 每个输入区域对应且按原顺序返回一个结果。成功 `code="mask_extracted"`，mask 必须是同 H×W 的二维 `np.bool_`；保留真实孔隙和分离连通分量，不填 bbox 矩形或预先强制取最大分量。模型内部缩放后以最近邻还原，披露其预处理版本。不能将返回框/得分当 mask。
- 失败 `status="failed"`、`mask=None`，固定码取 `invalid_image`、`invalid_bbox`、`region_too_small`、`duplicate_object_id`、`object_limit_exceeded`、`backend_unavailable`、`weights_missing`、`weights_invalid`、`device_unavailable`、`compute_slot_busy`、`inference_timeout`、`inference_failed`、`mask_empty`、`mask_full_frame`、`mask_invalid`。未知异常映射 `inference_failed`，不返回异常正文。
- 全前景没有可辨背景时作为失败，不能以全图真值掩码凑成功。多候选选择依据须固定、可解释且记录 `candidate_count/selection_basis`；自评分只是候选依据，不是准确率。
- `backend/model_version/device` 必须反映实际执行者。权重为真实 SHA-256；未加载/不存在用 None，绝不伪造散列。B 不隐性降级、不静默下载。A 将模型失败与实际 GrabCut 降级分别记录，且重新跑覆盖率、自交、来源与比例校验。
- `timings` 单位秒，用单调时钟，固定键 `queue/load/encode/decode/postprocess/total`，缓存命中阶段实际为0，不能填官方速度。`total` 为本次调用墙钟时间，勿累加并行区间充作总时间。初次加载另列冷启动，不混为热请求速度。
- 每运行时最多一个模型实例、一个推理槽；排队最多0.5秒，超时明确失败。每批只编码一次图像，多个 bbox 复用编码；跨批最多保留一个图像 embedding，进程内有界、不写照片或 embedding 到磁盘，`close()`释放。不同 RGB/模型/预处理绝不共用旧 embedding。不可中断的 native 推理须用可回收 worker 或诚实说明超时边界，不能只在推理完后声称硬超时。
- 缓存键由实际 RGB 内容散列、尺寸、模型/权重散列、预处理/算法版本、完整bbox与参数构成。B 只管理编码生命周期；轮廓成功缓存仍归 A。失败不入成功缓存。B 可最多评测两个候选，独立环境，不修改共享依赖。
- A 的接入点是 `pixel_contours._trace_single` 当前 GrabCut 产生 foreground 的位置；下游仍保留多连通/孔隙、简化、细节线与质量检查。连续场景 `scene_structure` 不强制走物体分割。

## C：已实现的共享摄影事实 photography-facts-v1

拥有文件：`services/photography_facts.py`、`advisor.py`、`validator.py`、`tests/test_photography_facts.py`，以及摄影建议/校验专属测试和文档。C 接管现有实现审查完善，A 检查点后不再同时修改这些文件。

现有可调用签名：

```python
build_photography_facts(request, scene: SceneAnalysis | None,
                        camera: CameraProfile | PhoneProfile | None) -> PhotographyFacts
photography_facts(request, scene, camera=None) -> PhotographyFacts
use_photography_facts(facts)  # context manager
semantic_issues(text: str, facts: PhotographyFacts) -> set[str]
reconcile_parameter_facts(recommendation, facts) -> CameraRecommendation
reconcile_composition_proposal(proposal, facts) -> tuple[CompositionProposal, list[str]]
reconcile_composition_facts(advice, facts) -> CompositionAdvice
preserve_continuous_framing(advice, facts) -> CompositionAdvice
```

`PhotographyFacts` 为 frozen dataclass：`device_type`、`ibis`(present/absent/unknown)、`motion`、`support`(tripod/handheld/unspecified)、`white_balance_goal`(preserve_warmth/neutralize/unspecified)、`declared_light`(str或None)、`compare_center_thirds`、`preserve_reflection`。`prompt()`提供受控生成约束；`white_balance_instruction`为同源建议。

器材能力来自已解析目录；generic_*强制未知，R50目录为无IBIS。运动、支撑和白平衡目标来自用户明确条件，不能从暖色照片推断钨丝光源。局部规则不是完整自然语言事实证明。现存正例包括降低抖动/增加稳定性、否定句、支持时的条件句与未知机型。

A 已在 `pipeline.py` 两分支启动前构建同一实例，通过 `copy_context`传播，参数/构图继续并行；在构图 snapshot/ready/返回与汇合做本地校验。`composition.py`负责生成约束和连续场景保留取景接入。C 若改上述签名/语义，交具体最小接入diff，由 A 修改这两个文件；禁止额外串行云调用。

## D：已实现的几何 contract-v1

消费 `composition_models.py` 与 `mobile/src/types.ts`，样例位于 `tests/fixtures/composition_contract_v1.json`；均是合成线协议数据，不是实际照片效果证据。

- bbox/source_bbox 为0–1 XYXY，路径点为相对 bbox 的0–1局部坐标；每路径最多64点，实体至少3点，开放线至少2点；details最多96条，contours/holes各最多12条。
- silhouette：单外环 outline，或 contours 表示多个实心分部；只有 silhouette 填色。当前后端禁止 holes 和 contours 同时使用；holes 必须是单外环内部不触边、无自交的真实分割孔。SVG与Canvas使用evenodd透明孔。旧记录缺 holes 默认为空。
- context_lines：非main环境线，outline/contours/holes必须为空、details非空，不闭合或填色。
- scene_structure：保留main身份的固定建筑/山水开放结构，outline/contours/holes为空，details至少4条且有双轴覆盖。原始 ObservedScene.scene_mode=continuous；人物动物不得改模式绕过分割。开放路径自身不填色、不延伸未知背景。参考图底层配色单独说明，不声称完整对象分割。
- 所有推荐图保留 `reference_photo_id`、对象来源 `source_object_id`、`evidence_photo_ids`、`source_bbox`；开放结构还保留 `source_details`。source_geometry图记录 `source_photo_aspect`，布局物理比例以它校正。
- 新意图 `CompositionIntent.version=1`，本地 `layout_engine=local_v1`。`layout_mode`为schematic/crop_projection/source_preserving。连续场景采用source_preserving及四项keep，统一变换整体保留原取景与已有截断，不称推荐图已实现侧移后的透视。
- 新路径以同一sx/sy/tx/ty保护所有主要主体，环境线按同一变换裁剪。已知兼容边界：旧 provider storyboard 回退 `apply_observed_layout` 仍逐层_fit_box，只有固定左右顺序检查；不能把新路径统一变换保证外推给旧回退，A 后续负责。
- 最小有效例：legacy、silhouette_hole、continuous；明确失败例：context_main、outside_hole、closed_scene、missing_source；另有无占位图的failure_advice。D应同时跑前端可信校验，不把接收等同质量成功。
- `CompositionDiagnostic`含stage/status/code和可选object_id/field_path；code固定格式，字段路径脱敏，不能将Pydantic原始输入或远端错误正文显示给用户。

## 事件和历史

保留scene、parameters、composition文字partial；`composition_ready`仅发布已完成主体与布局校验的完整CompositionAdvice。相同请求ready与最终构图应相同，不能把未检验图当提前完整图。partial/ready不写历史，只有最终result持久化；新任务revision隔离旧任务结果。失败保持文字/原因说明，不补占位主体。

NDJSON事件发生时刻是相对于客户端单调时钟的固定时间，阶段duration由后端单调时钟给出；父子阶段/并行分支有重叠不可相加。中途ready后最终整体失败需要明确分析失败，不假定已保存历史。

## 交接限制

本检查点是并行基线，不是 INTEGRATION_READY。学习型分割未接入、最终咖啡v4只有离线冻结输入验证、狗耳眼球仍弱；最终模型效果和端到端耗时交 E 验收。真实云后续只由 E 发起，本轮总额8，A已用5，剩3。照片/原始回复/截图/权重/配置/密钥均不入Git。
