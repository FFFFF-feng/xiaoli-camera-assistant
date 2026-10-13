import json

from vision_lab_tool.models import Advice, Observation

RECOGNITION_TEMPLATE = """你是摄影现场观察助手。只依据本次图片报告可见事实，将观察与推断分开。
无法确认的信息填 unknown/null 并说明原因。不要猜测照片原有 ISO、光圈、快门、拍摄距离、
器材型号或真实运动速度。允许未知和多个场景；主体不确定时提供候选并说明。
逐项报告可见主体、光线与明暗、逆光、运动线索、背景干扰、遮挡、边缘截断及澄清问题。
不要提供拍摄建议，不读取或利用不存在的标注答案；文件名不能作为证据。
仅返回最终 JSON，不要求隐藏思维链。"""

ADVICE_TEMPLATE = """你是摄影建议评测助手。先报告可见观察，再区分用户目标、器材事实与未知条件。
给出 2～3 个有差异的方案，各有目标、动作、理由、取舍、适用条件、限制与可选参数。
明确区分现有照片裁切 crop、调整机位 camera_position、改变焦距 focal_length、重新拍摄 reshoot。
没有测量依据时不得编造精确移动距离或拍摄参数。原图 EXIF 只是拍摄记录，不等于推荐参数。
只返回最终 JSON，不要求隐藏思维链。"""


def result_schema(mode: str):
    return (Observation if mode == "recognition" else Advice).model_json_schema()


def wire_schema(mode: str):
    """Strict provider schema, with local numeric/list bounds still validated by Pydantic."""

    def visit(node):
        if isinstance(node, list):
            return [visit(v) for v in node]
        if not isinstance(node, dict):
            return node
        out = {
            k: visit(v)
            for k, v in node.items()
            if k not in {"default", "minimum", "maximum", "minItems", "maxItems"}
        }
        if out.get("type") == "object":
            out["additionalProperties"] = False
            out["required"] = list(out.get("properties", {}))
        return out

    return visit(result_schema(mode))


def build_prompt(
    mode: str, template: str, context: dict | None = None, include_exif: bool = False
) -> str:
    coordinate = (
        "所有 bbox 必须为 [x_min,y_min,x_max,y_max]，在方向修正后图片的 "
        "0～1 归一化坐标系中；顺序正确且非零面积。无依据时 bbox=null。"
    )
    language = (
        "描述性文本请使用简体中文，包括场景、主体名称、观察依据、不确定信息和建议。"
        "JSON 字段名、枚举值和主体编号保持 schema 要求，不要翻译或改写它们。"
    )
    prompt = template + "\n" + coordinate + "\n" + language
    if mode == "advice":
        source = context or {}
        allowed = {k: source.get(k, "") for k in ("goal", "equipment", "reference")}
        if include_exif:
            allowed["original_capture_exif_only"] = source.get("exif", {})
        prompt += "\n实验共同上下文：" + json.dumps(allowed, ensure_ascii=False)
    return (
        prompt
        + "\n返回以下 JSON schema 对应的 JSON：\n"
        + json.dumps(result_schema(mode), ensure_ascii=False)
    )
