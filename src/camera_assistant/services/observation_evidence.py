"""Bounded, local semantic consistency and readable observation summaries."""
import re


def category_adaptation(raw):
    """Specific object names may contradict a generic category, never a case ID.

    Architectural names and background roles are deliberately not rewritten.
    This checks category consistency; it does not prove the visual label true.
    """
    if not isinstance(raw, dict) or raw.get("role") == "background":
        return None
    label, kind = raw.get("label"), raw.get("kind")
    if not isinstance(label, str) or not isinstance(kind, str):
        return None
    if re.search(r"建筑|大楼|楼房|塔|雕塑|造型|形状|building|tower|sculpture", label, re.IGNORECASE):
        return None
    candidates = (("cup", r"(?:咖啡|纸|茶|水)?杯|\b(?:cup|mug)\b"),
                  ("bottle", r"水瓶|酒瓶|饮料瓶|\bbottle\b"),
                  ("camera", r"相机|摄影机|\bcamera\b"),
                  ("book", r"书本|书籍|\bbook\b"),
                  ("ball", r"皮球|网球|小球|^球$|\bball\b"))
    matches = [target for target, pattern in candidates if re.search(pattern, label, re.IGNORECASE)]
    if len(matches) != 1 or kind.strip().casefold() == matches[0]:
        return None
    # Only resolve a broad/inconsistent type, not two conflicting specific names.
    if kind.strip().casefold() not in {"building", "architecture", "object", "pet", "tree", "mountain"}:
        return None
    return {"original_kind": kind[:30], "normalized_kind": matches[0],
            "reason": "specific_label_category_consistency"}


def observation_summary(advice, scene):
    """Text reflects locally validated inputs and extraction, not a quality pass."""
    if scene is None:
        return advice
    rows = []
    for obj in scene.objects:
        if obj.role not in {"main", "prop"}:
            continue
        if obj.representation == "scene_structure":
            rows.append(f"已保留“{obj.label}”的同一组开放结构线，关联景物共同变换；不是完整物体分割。")
        else:
            rows.append(f"“{obj.label}”已提取可见轮廓与局部像素线索；名称和细节仍需对照原图核对。")
        if obj.photo_boundary and obj.photo_boundary.clipped_edges:
            rows.append(f"“{obj.label}”接触照片边界，画外形体未知，未描绘闭合的截断边。")
    missing = [f"已识别到“{obj.label}”，但未可靠绘出；请对照原图核对。" for obj in scene.unrendered_objects]
    return advice.model_copy(update={"observations": [*rows, *missing][:10],
        "uncertainties": list(dict.fromkeys([*missing, *advice.uncertainties]))})
