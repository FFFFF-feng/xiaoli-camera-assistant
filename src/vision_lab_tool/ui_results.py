import streamlit as st

from vision_lab_tool.presentation import observation_sections, proposal_sections, reported


def _section(title: str, lines: list[str]):
    st.markdown(f"**{title}**")
    for line in lines:
        st.text(line)


def readable_result(parsed: dict, mode: str):
    st.caption("中文字段在本地转换，描述保留模型原文；自报可信度不代表准确率。")
    observation = parsed if mode == "recognition" else parsed["observation"]
    sections = observation_sections(observation)
    with st.container(border=True):
        for title, lines in sections[:4]:
            _section(title, lines)
        with st.expander("运动线索、不确定信息与补充问题"):
            for title, lines in sections[4:]:
                _section(title, lines)
    if mode == "advice":
        with st.expander("建议所依据的目标、器材与未知条件"):
            _section("用户目标", [parsed["user_goal"] or "未填写"])
            _section("器材事实", reported(parsed["equipment_facts"]))
            _section("未知条件", reported(parsed["unknown_conditions"]))
        for number, proposal in enumerate(parsed["proposals"], 1):
            title, details = proposal_sections(proposal, number)
            with st.container(border=True):
                st.markdown(f"##### {title}")
                for label, lines in details[:2]:
                    _section(label, lines)
                with st.expander("理由、取舍、适用条件与参数"):
                    for label, lines in details[2:]:
                        _section(label, lines)
