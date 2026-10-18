"""Full-denominator acceptance matrix and budget plan.

Absence of a test is never a pass. Every case starts as ``not_tested`` and
requires a stored evidence directory from the frozen integrated version.
"""

from __future__ import annotations

from typing import Any

CASES: dict[str, dict[str, Any]] = {
    "02": {
        "title": "狗：奔跑动作与主体身份",
        "risk": "主体身份/分割变化；细腿、孔隙与尾巴细节",
        "checks": [
            "实际朝向、跑姿、可见耳/腿/尾与球有辨识依据",
            "细腿没有因处理被明显合并",
            "若启用 MobileSAM，前腿三角孔与耳尖不得比 GrabCut 基线更差",
            "草地杂线减少且没有用背景块替代主体",
            "没有高速快门或IBIS错误建议",
            "原图—推荐图—文字三者一致",
        ],
    },
    "06": {
        "title": "咖啡：杯沿、奶泡与暖色取舍",
        "risk": "v4未完成真实云复测；主体类别/轮廓和文字一致性",
        "checks": [
            "可见杯沿、奶泡与杯身边界可辨",
            "若启用 MobileSAM，杯底最后可见行不得丢失、杯沿误孔不得造成断线",
            "与计算器的空间关系合理",
            "不补造原图未拍到的杯底或杯把",
            "参数与文字的暖色/白平衡目标一致",
            "推荐图不是计算器框或背景块的拼接",
        ],
    },
    "07": {
        "title": "山湖：山峰、水岸与倒影",
        "risk": "观察协议失败；连续场景结构表达",
        "checks": [
            "峰、水岸和倒影关联保留",
            "没有把山和倒影当作独立物体搬动",
            "识别失败与结构失败分别记录",
            "不出现无依据的精确距离或移动米数",
            "失败提示诚实，不用合成轮廓冒充成功",
        ],
    },
    "08": {
        "title": "拱廊：递进拱门与消失方向",
        "risk": "轮廓/连续结构；当前版本尚未复测",
        "checks": [
            "递进拱门、两侧结构和消失方向可读",
            "合理评价原居中构图，不机械套三分",
            "图文一致",
            "孤立矩形不算建筑成功",
            "连续结构不闭合、不整片填色",
        ],
    },
}

PRIORITY = ["06", "07", "02", "08"]
PRIORITY_RATIONALE = {
    "06": "咖啡 v4 改动未做完整云上传复测，剩余预算应先消除这个已知不确定项。",
    "07": "首轮观察协议失败、二次成功，需在新集成版本确认失败不会复发。",
    "02": "狗的主体身份与分割修复影响最大，也覆盖细腿/孔隙等关键画质。",
    "08": "拱廊历史上有图但轮廓失败；本轮预算不足时保持未验收，不能写成通过。",
}


def build_matrix(runs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    tested = set()
    for run in runs or []:
        if run.get("accepted_for_integrated_version"):
            tested.add(str(run.get("case_id")))
    cases = []
    for case_id in ("02", "06", "07", "08"):
        definition = CASES[case_id]
        cases.append(
            {
                "case_id": case_id,
                "title": definition["title"],
                "risk": definition["risk"],
                "priority": PRIORITY.index(case_id) + 1,
                "status": "not_tested" if case_id not in tested else "evidence_available",
                "passed": False,
                "checks": [
                    {"text": text, "status": "not_tested"} for text in definition["checks"]
                ],
                "note": "No frozen integrated-version evidence; not a pass.",
            }
        )
    return {
        "schema": "line-drawing-acceptance-matrix-v1",
        "integrated_version": None,
        "cases": cases,
        "denominator": {
            "required_full_runs": 4,
            "completed_full_runs": 0,
            "failed_or_incomplete_runs": 0,
            "note": "Historical pre-checkpoint runs are localization evidence only.",
        },
    }


def budget_plan(
    remaining_gateway_posts: int,
    *,
    internal_starts_per_full_run: int = 4,
) -> dict[str, Any]:
    ordered = list(PRIORITY)
    funded = ordered[: max(0, remaining_gateway_posts)]
    unfunded = ordered[len(funded):]
    return {
        "remaining_gateway_posts": remaining_gateway_posts,
        "minimum_gap_for_four_cases": max(0, 4 - remaining_gateway_posts),
        "retest_reserve_needed": 1,
        "gap_if_one_retest_required": max(0, 4 + 1 - remaining_gateway_posts),
        "planned_order": funded,
        "unfunded": unfunded,
        "rationale": PRIORITY_RATIONALE,
        "estimated_internal_request_starts": remaining_gateway_posts
        * internal_starts_per_full_run,
        "notes": [
            "One gateway POST is one complete upload; internal request_started events are counted separately.",
            "A failed attempt still consumes a gateway POST.",
            "Observation protocol repair is an internal request and does not refund budget.",
            "Unfunded cases remain not_tested; in particular 08 must not be reported as passed.",
            "Final order and any budget change require the controller's confirmation after integration.",
        ],
    }
