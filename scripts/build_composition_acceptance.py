"""Build offline synthetic presentation samples; no model or photo upload needed."""
from __future__ import annotations

import base64
import json
from pathlib import Path

from camera_assistant.composition_models import CompositionIntent, CompositionProposal, ObservedScene, PhotoBoundary
from camera_assistant.services.layout_solver import solve_layout
from camera_assistant.services.photo_boundary import boundary_evidence

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    cases = []
    for name, box, placement, scale, actions in [
        ("近似恒等变换", [.4, .1, .5, .9], "keep", "keep", ["检查塔顶与四边余量，再试拍一张"]),
        ("明显左移并放大", [.4, .1, .5, .9], "left", "larger", ["适当靠近，调整取景使主体位于画面左侧"]),
        ("主体接触左边缘", [0., .1, .1, .9], "right", "larger", ["适当后退，重新拍全主体并检查左侧余量"]),
        ("连续场景", [0., 0., 1., 1.], "left", "larger", ["降低机位试拍，核对两侧结构的关联"]),
    ]:
        continuous = name == "连续场景"
        scene = ObservedScene.model_validate({"scene_mode": "continuous" if continuous else "objects",
            "objects": [{"object_id": "object1", "label": "测试建筑", "kind": "building", "role": "main",
                "mobility": "fixed", "depth": 1, "bbox": box,
                "outline": [] if continuous else [[0, .15], [.5, 0], [1, .15], [1, 1], [0, 1]],
                "representation": "scene_structure" if continuous else "silhouette",
                "details": ([[[0, .1], [.5, .5], [1, .1]], [[0, .9], [.5, .5], [1, .9]],
                             [[.1, 0], [.4, 1]], [[.9, 0], [.6, 1]]] if continuous else
                            [[[.2, .3], [.8, .3]], [[.3, .3], [.3, .95]]]),
                "identity_features": ["合成测试轮廓"], "evidence_photo_ids": ["photo1"]}],
            "limitations": ["此图为合成验收样本，不验证真实照片的识别质量。"]})
        if name == "主体接触左边缘":
            scene.objects[0].photo_boundary = PhotoBoundary.model_validate(
                boundary_evidence(scene.objects[0].outline, box, 800, 600))
        proposal = CompositionProposal(action_type="reshoot", goal=name, actions=actions,
            reasons=["测试展示分支"], conditions=["离线合成样本"], tradeoffs=["不代表真实摄影"], limitations=["仅用于验收页面展示"])
        board, framing = solve_layout(CompositionIntent(focus_object_id="object1", diagnosis=name,
            placement=placement, subject_scale=scale), scene, 4/3, proposal)
        obj = scene.objects[0]
        def path(points):
            return " ".join(f"{(box[0]+x*(box[2]-box[0]))*800:.1f},{(box[1]+y*(box[3]-box[1]))*600:.1f}" for x, y in points)
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600" viewBox="0 0 800 600">'
               '<rect width="800" height="600" fill="#c9dee9"/><rect y="480" width="800" height="120" fill="#acbda0"/>')
        if obj.outline:
            svg += f'<polygon points="{path(obj.outline)}" fill="#d0ae83" stroke="#41392f" stroke-width="3"/>'
        svg += ''.join(f'<polyline points="{path(p)}" fill="none" stroke="#41392f" stroke-width="3"/>' for p in obj.details)
        svg += '<text x="20" y="570" font-family="sans-serif" font-size="18">SYNTHETIC TEST FIXTURE</text></svg>'
        cases.append({"name": name, "board": board.model_dump(), "framing": framing.model_dump(), "actions": actions,
            "reference": "data:image/svg+xml;base64,"+base64.b64encode(svg.encode()).decode()})
    target = ROOT / "mobile/tests/fixtures/composition-presentation.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(cases, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"Created {len(cases)} offline presentation cases.")


if __name__ == "__main__":
    main()
