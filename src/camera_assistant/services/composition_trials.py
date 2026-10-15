"""Bounded action interpretation and goal-specific, unmeasured field checks.

An angle word is never enough to infer pitch. Source actions are retained by
the caller; this module emits only explicit action kinds and program trials.
"""
from __future__ import annotations

import re

from camera_assistant.candidate_models import FieldCheck, TrialAction

NEGATED = re.compile(r"不要|不应|不得|不可|不能|不宜|避免|无需|不必|不需要|不移动|不旋转|不转动|(?<!分)别|勿|禁止|不准|不许|不(?:向|往|朝|横移|后退|靠近|抬|降|转)")
CONDITION = re.compile(r"^(?:如果|若|只有|当|在.{0,20}(?:时|后))")


def interpret_actions(actions: list[str]) -> list[TrialAction]:
    """Keep object and direction distinct; unsupported prose stays in evidence."""
    result: list[TrialAction] = []
    for source in actions:
        for sentence in re.split(r"[；;。\n]", source):
            if "否则" in sentence:
                # This bounded interpreter cannot bind arbitrary alternative
                # branches reliably. Keep source evidence, withhold the move.
                continue
            condition = ""
            for clause in re.split(r"[，,]", sentence):
                clause = clause.strip()
                if not clause:
                    continue
                if CONDITION.search(clause):
                    condition = clause
                    # A condition may itself contain an action, but '灯具可移动'
                    # does not direct anybody to move the light.
                    if not re.search(r"(?:才|则|可尝试|试着|试将|将|请).*(?:移|转|拍|抬|降|退)", clause):
                        continue
                if NEGATED.search(clause):
                    continue
                # 'towards the person's right side' locates the move. The
                # person is a spatial reference, not its grammatical actor.
                actor_clause = re.sub(
                    r"(?:向|往|朝)(?:人物|模特|主体|相机|机身|光源|灯具)(?:的)?(?=[左右前后])",
                    "向", clause,
                )
                found: list[tuple[str, str, str]] = []
                light_actor = bool(re.search(r"(?:移|升|降|抬|转).{0,5}(?:光源|灯具|灯|反光板)|(?:光源|灯具|灯|反光板).{0,8}(?:移|升|降|抬|转)", actor_clause))
                subject_actor = bool(re.search(r"(?:人物|模特|主体|脸部|头部|下巴).{0,8}(?:移动|后退|向后退|向[左右].{0,3}移|靠近|转脸|转头|转身|侧脸|抬头|低头|姿态)|(?:移动|挪动|转动).{0,4}(?:人物|模特|主体|脸部|头部)", actor_clause))
                camera_actor = bool(re.search(r"相机|机身|机位|镜头", actor_clause))
                if sum((light_actor, subject_actor, camera_actor)) > 1:
                    # A shared clause with multiple actionable objects has no
                    # reliable subject/verb binding in this bounded interpreter.
                    continue
                if light_actor:
                    # '光线从侧面照射' is an effect, not a light-position action.
                    if re.search(r"(?:移|升|降|抬|转).{0,5}(?:光源|灯具|灯|反光板)|(?:光源|灯具|灯|反光板).{0,8}(?:移|升|降|抬|转)", clause):
                        found.append(("light_position", "light", _direction(clause, "相对调整光源位置")))
                elif subject_actor or (re.search(r"人物|模特|主体|脸|头部|下巴", clause) and re.search(r"转脸|转头|转身|侧脸|抬头|低头|下巴|调整.{0,4}姿态", clause)):
                    turning = bool(re.search(r"转脸|转头|转身|侧脸|抬头|低头|下巴|姿态", clause))
                    direction = ("向左" if re.search(r"向左|往左|朝左", clause) else "向右" if re.search(r"向右|往右|朝右", clause) else "稍微后退" if re.search(r"后退|向后退", clause) else "稍微靠近" if "靠近" in clause else "小幅调整")
                    direction += "转脸或调整姿态" if turning else "移动主体"
                    found.append(("subject_pose", "subject", direction))
                elif re.search(r"对焦|合焦|焦点", clause) and re.search(r"对准|对焦|选择|放在|跟焦", clause):
                    target = "花瓣" if "花瓣" in clause else "眼睛" if re.search(r"眼睛|眼部", clause) else "目标主体"
                    found.append(("focus", "focus", f"将对焦目标放在{target}并检查合焦"))
                else:
                    if re.search(r"侧移|侧向移动|向侧面移动|横移|左右平移|(?:向|往|朝)[左右].{0,5}(?:移|挪)|[左右]移", actor_clause):
                        found.append(("lateral_translation", "camera", _direction(actor_clause, "向侧面横移相机")))
                    if re.search(r"后退|退后|后移|向后|靠近|接近|微近|前移|向前", clause):
                        direction = "稍微后退" if re.search(r"后退|退后|后移|向后", clause) else "稍微靠近"
                        found.append(("depth_translation", "camera", direction))
                    if re.search(r"降低.{0,5}(?:高度|机位)|(?:相机|镜头).{0,3}降低|降低(?:相机|镜头)|低机位|蹲下|放.{0,4}(?:地面|低)", clause):
                        found.append(("height_translation", "camera", "降低相机高度"))
                    elif re.search(r"提高.{0,5}(?:高度|机位)|抬高.{0,4}(?:相机|镜头|机位)|高机位", clause):
                        found.append(("height_translation", "camera", "提高相机高度"))
                    if re.search(r"俯拍|仰拍|俯仰|向下倾|向上倾|从下往上拍|从上往下拍", clause):
                        direction = "向下俯拍" if re.search(r"俯拍|向下倾|从上往下拍", clause) else "向上仰拍" if re.search(r"仰拍|向上倾|从下往上拍", clause) else "小幅调整相机俯仰"
                        found.append(("pitch", "camera", direction))
                    if re.search(r"(?:旋转|转动).{0,4}(?:相机|机身|镜头)|(?:相机|机身).{0,4}(?:旋转|转动)|横竖构图|横拍|竖拍", clause):
                        found.append(("rotation", "camera", "小幅旋转相机并比较构图"))
                for kind, target, direction in found:
                    item = TrialAction(kind=kind, target=target, direction=direction,
                                       condition=condition, source_text=source)
                    if item not in result:
                        result.append(item)
    return result


def _direction(clause: str, fallback: str) -> str:
    if re.search(r"向左|往左|朝左|左移", clause):
        return "向左相对移动" if re.search(r"灯|光源|反光板", clause) else "向左试取景"
    if re.search(r"向右|往右|朝右|右移", clause):
        return "向右相对移动" if re.search(r"灯|光源|反光板", clause) else "向右试取景"
    return fallback


def render_actions(actions: list[TrialAction]) -> list[str]:
    labels = {"camera": "相机", "subject": "人物/主体", "light": "光源", "focus": "对焦"}
    result = []
    for action in actions:
        condition = ("仅在“" + action.condition + "”成立时；") if action.condition else "在现场安全可行且主体允许时；"
        result.append(condition + labels[action.target] + "：" + action.direction + "，先试取景再比较。")
    return list(dict.fromkeys(result))


def goal_field_checks(intent: str) -> list[FieldCheck]:
    """Select only checks motivated by a user's concrete subject and goal.

    These are bounded program suggestions. They do not certify observations,
    light placement, equipment features, or a new successful photograph.
    """
    checks: list[FieldCheck] = []
    # Negated improvements are not positive goals. Keep independent positive
    # clauses (e.g. '不要靠近，但让花瓣更分明') and preserve an explicit user gate.
    positive = "；".join(part for part in re.split(r"[，,。；;]", intent)
        if not re.search(r"不要|不想|不必|不需要|不希望|无需|(?<!分)别|勿|禁止", part))
    keep_reflection = bool(re.search(r"(?:保留|保持).{0,8}(?:镜片|眼镜)?.{0,3}反光", positive))
    portrait_goal = bool(re.search(r"眼睛|眼部|笑脸|人像|人物|戴.{0,3}眼镜", positive))
    expression = "笑脸与原有亲近感" if re.search(r"笑脸|亲近感", positive) else "用户要求保留的表情与脸部呈现"
    if (portrait_goal and re.search(r"眼镜|镜片", positive)
            and re.search(r"反光|反射", positive) and not keep_reflection):
        checks.extend([
            FieldCheck(issue="镜片反光与眼睛实际位置及表现需分别核对",
                observe="先在预览中分别找到眼睛、镜框和镜片亮斑；对眼睛对焦后放大检查合焦。保持" + expression + "，沿原动作方向比较前后亮斑位置与眼睛的相对关系。",
                accept_when="只有反光位置或面积更符合目标、眼睛仍清晰且" + expression + "保留时，才采用这次调整；效果不理想就回到原机位。",
                protect="保护" + expression + "与眼睛，检查当前可见脸部边界及用户明确要求的保护内容；不能恢复画外或被遮挡内容。",
                basis="用户原文目标：" + intent),
            FieldCheck(issue="反光取决于相机、脸部/镜片和光源的相对角度，光源位置未知",
                observe="按本方案已明确的动作对象与方向比较取景，不把主体动作当成相机移动；若人物愿意，可另做轻微转脸比较；只有确认光源可移动且获允许时，才单独调整光源位置。每次只变一个对象，再比较相机、脸部/镜片和光源的相对关系以及镜片亮斑与眼睛、脸部比例。",
                accept_when="保留" + expression + "、眼睛合焦和所需背景后，选择反光更合意的相对关系；旋转相机不保证减少镜片反光，也不能由机位变化推断光源已经移动。",
                protect="保护脸部姿态及用户原文目标，不要求摘眼镜或假设画外灯具存在。",
                basis="程序现场比较建议；用户希望眼镜反光减少，未提供光源位置"),
        ])
    if re.search(r"花|花瓣", positive) and re.search(r"边缘|轮廓|层次", positive):
        checks.append(FieldCheck(issue="花瓣边缘的合焦与明暗轮廓需要分开检查",
            observe="先选用户想强调的一层花瓣或边缘作为对焦目标，放大试拍查看合焦；再沿原动作方向试取景，比较该花瓣与相邻花瓣、背景的明暗轮廓。只移动相机不会改变光源相对花朵的照射方向。",
            accept_when="所选花瓣合焦、轮廓可辨且高光仍保留细节时采用；若层次不足，先重新选择对焦位置，只有现场确认可控制光源时才另行试调照明。",
            protect="保护花朵当前可见花瓣与花瓣边缘余量，不假定全部花瓣处于同一焦平面。",
            basis="用户原文目标：" + intent))
        if re.search(r"黑背景|背景.{0,6}黑", positive):
            checks.append(FieldCheck(issue="保持黑背景是用户目标，不能用后退、长焦或侧移保证背景变黑",
                observe="每次重新取景后，检查花瓣四周是否带入亮物、背景是否仍呈所需黑色，并与原图比较花瓣轮廓；试拍放大检查亮部细节，背景暗不等于花瓣一定欠曝。",
                accept_when="背景仍为所需黑色、花瓣合焦轮廓保留且边缘不挤出画面时采用；不能靠全局提亮替代轮廓检查。",
                protect="同时保护黑背景、花瓣细节与完整可见轮廓。",
                basis="用户明确要求保持黑背景；程序试拍检查，不是绝对照度判断"))
    two_players = bool(re.search(r"两(?:个|位|名)?(?:人|球员|运动员)|两位|两名", positive))
    if (two_players and re.search(r"争球|抢球", positive)
            and re.search(r"跳|跃", positive) and re.search(r"附近|周围|队友|队员", intent)):
        checks.extend([
            FieldCheck(issue="跳起争球的主体需要连续跟焦，单帧不能证明下一刻位置",
                observe="先在预览中核对用户要保留的两位争球者，按最终对焦模式将对焦区域放到目标球员上并持续跟焦；在动作发生前跟随，短连拍后放大核对脸部或躯干合焦和运动模糊。若跟到背景观众，重新获取目标。",
                accept_when="目标球员合焦、动作清晰且两位争球者都保留时采用；跟焦方式与可用设置以最终参数及器材确认结果为准。",
                protect="保护两位争球者及球的可见关系，不猜身份、号码或未见动作。",
                basis="用户原文目标：" + intent),
            FieldCheck(issue="球与举起的手需要上方余量，附近队员的四肢边界仍需现场核对",
                observe="保持跟随取景，检查球和举起的手上方是否留有可继续动作的余量，再检查两侧及下方可见四肢、脚与附近队员边界；先核对哪些是用户要保留的队员，不能把背景观众都当成队员。",
                accept_when="当前预览和试拍中球、手及用户指定队员的可见四肢均未因新取景被截断时采用；靠近后若保护内容逼近边缘，就停止靠近并比较较宽取景。",
                protect="保护两位跃起者、球、手上方空间和附近队员当前可见四肢，不能恢复原图画外或遮挡身体。",
                basis="用户要求留空间、附近队员别裁断；程序边界检查"),
            FieldCheck(issue="灯具频闪未知，不能从单帧亮度推定灯具特性",
                observe="按最终快门与驱动设置短连拍，比较相邻试拍的亮暗、色偏或条带；若异常，先核对现场灯具及相机可用防频闪功能。",
                accept_when="试拍未出现影响目标的条带或连续帧亮暗变化，并且动作清晰时再继续；一次检查不保证此后所有帧都无频闪。",
                protect="兼顾凝固动作与连续帧表现，不编造灯具频率或保证某个快门消除频闪。",
                basis="程序待确认项：现场灯具与频闪未由用户确认"),
        ])
    user_conditions = re.findall(r"(?:如果|只有|若|当)[^，,。；;]+", intent)
    if user_conditions:
        gate = "仅在用户原文条件成立时（" + "；".join(user_conditions) + "）；否则保持原方案。"
        checks = [check.model_copy(update={
            "observe": gate + check.observe,
            "accept_when": gate + check.accept_when,
        }) for check in checks]
    return checks
