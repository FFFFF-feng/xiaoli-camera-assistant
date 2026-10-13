"""Frozen task vocabulary. This module has no references, manifests or image names."""
from __future__ import annotations

import re

DICTIONARY_VERSION = "task-english-v2"
TASK_DICTIONARY = {
    "人物": "person", "人群": "person", "行人": "person", "骑行者": "person",
    "人像": "person", "双手": "hand", "手部": "hand", "左手": "hand",
    "右手": "hand", "手掌": "hand", "泥坯": "clay", "陶坯": "clay",
    "黏土": "clay", "陶轮": "pottery wheel", "轮面": "pottery wheel",
    "器具": "instrument", "装置": "device", "盒体": "metal box",
    "长杆": "rod", "金属杆": "rod", "管口": "tube", "金属管": "tube",
    "水滴": "water droplet", "飞溅": "water splash", "海浪": "wave",
    "礁石": "rock", "日食": "eclipse", "日全食": "eclipse",
    "亮点": "bright spot", "亮斑": "bright spot", "自行车": "bicycle",
    "鸟": "bird", "狗": "dog", "猫": "cat", "树": "tree", "汽车": "car",
    "反射": "reflection", "画中人物": "depicted person", "列车": "train",
    "水杯": "cup", "杯子": "cup", "彩铅": "colored pencil", "喷溅": "water splash",
    "两只手": "hand",
}
COCO_CLASSES = ("person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush")
ALIASES = {"people": "person", "human": "person", "persons": "person",
           "hands": "hand", "water droplets": "water droplet", "dogs": "dog",
           "cats": "cat", "birds": "bird", "bikes": "bicycle", "bike": "bicycle",
           "water cup": "cup", "water cups": "cup", "cups": "cup"}
LABEL_RULE_VERSION = "complete-query-phrase-v1"


def canonical(value: str) -> str:
    value = re.sub(r"\s+", " ", value.lower().strip().strip("."))
    return ALIASES.get(value, value)


def label_components(label: str, sent_queries=()) -> dict:
    """Decode complete concatenated query phrases; never accept a substring.

    Grounding DINO may report multiple query phrases in one label. Each word
    must be consumed by an actual saved query or its frozen whole-phrase alias.
    Different categories remain distinct; identity/level are never flattened.
    """
    original = label
    value = re.sub(r"\s+", " ", label.lower().strip().strip("."))
    phrases = set(COCO_CLASSES) | set(ALIASES)
    phrases.update(re.sub(r"\s+", " ", q.lower().strip().strip(".")) for q in sent_queries)
    phrases = sorted(phrases, key=lambda q: (-len(q.split()), -len(q), q))
    remaining, pieces = value, []
    while remaining:
        phrase = next((q for q in phrases if remaining == q or remaining.startswith(q + " ")),
                      None)
        if phrase is None:
            return {"original": original, "normalized": canonical(value), "components": [],
                    "rule_version": LABEL_RULE_VERSION, "basis": "unparsed; no substring match"}
        pieces.append(canonical(phrase))
        remaining = remaining[len(phrase):].strip()
    components = list(dict.fromkeys(pieces))
    return {"original": original,
            "normalized": components[0] if len(components) == 1 else value,
            "components": components, "rule_version": LABEL_RULE_VERSION,
            "basis": "complete saved-query phrases and frozen whole-phrase aliases"}


def english_queries(values):
    result = []
    for value in values:
        value = canonical(value)
        if not re.fullmatch(r"[a-z][a-z0-9 '\-]{0,79}", value):
            raise ValueError("查询必须为英文类别短语，最多80字符；不执行表达式")
        if value not in result:
            result.append(value)
    return result


def task_queries(task: str) -> list[str]:
    result = []
    for token, phrase in TASK_DICTIONARY.items():
        if token in task and phrase not in result:
            result.append(phrase)
    known = set(COCO_CLASSES) | set(TASK_DICTIONARY.values()) | set(ALIASES)
    occupied = set()
    for phrase in sorted(known, key=lambda x: (-len(x), x)):
        for match in re.finditer(r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])", task.lower()):
            span = set(range(match.start(), match.end()))
            if not span & occupied:
                occupied.update(span)
                value = canonical(phrase)
                if value not in result:
                    result.append(value)
    return result


def compose_queries(task, semantics=(), manual=()):
    from_task = task_queries(task)
    from_vlm = english_queries([v.query for v in semantics])
    from_manual = english_queries(manual)
    return {
        "dictionary_version": DICTIONARY_VERSION,
        "from_task": from_task,
        "from_vlm": from_vlm,
        "manual": from_manual,
        "merged": list(dict.fromkeys(from_task + from_vlm + from_manual)),
        "fallback": from_task if not semantics else [],
        "source_policy": "task_dictionary+validated_vlm; manual is diagnostic/pure only",
        "task_text": task,
    }
