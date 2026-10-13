import os

import streamlit as st

from vision_lab_tool.configuration import resolve_key
from vision_lab_tool.credentials import KEY_NAMES
from vision_lab_tool.models import ModelConfig

LABELS = {
    "DASHSCOPE_API_KEY": "百炼 API Key（Qwen）",
    "ARK_API_KEY": "火山方舟 API Key（两个 Doubao 共用）",
    "ZHIPU_API_KEY": "智谱 API Key（GLM）",
}


def read_saved_keys(vault):
    try:
        return vault.load()
    except (ValueError, OSError) as exc:
        st.error(str(exc))
        return {}


def edit_keys(vault, saved, secrets):
    generation = st.session_state.get("lab_key_input_generation", 0)
    if st.session_state.pop("lab_clear_key_inputs", False):
        generation += 1
        st.session_state.lab_key_input_generation = generation
        for key in list(st.session_state):
            if key.startswith("api-input:"):
                del st.session_state[key]
    with st.expander("API Key（本机长期保存）", expanded=True):
        st.caption(
            "四个模型需要三份 Key，两个豆包共用火山方舟 Key。填写后点保存；留空保留已有密钥。"
        )
        with st.form("lab_key_form"):
            entries = {}
            for name, label in LABELS.items():
                entries[name] = st.text_input(
                    label,
                    type="password",
                    key=f"api-input:{name}:{generation}",
                    placeholder="粘贴 API Key；已有密钥可留空",
                )
                config = ModelConfig(name="credential", provider="", protocol="chat", key_env=name)
                status = (
                    "已在本机加密保存"
                    if saved.get(name)
                    else "已从环境变量 / secrets 读取"
                    if resolve_key(config, secrets=secrets)
                    else "尚未配置"
                )
                st.caption(label.split("（")[0] + "：" + status)
            submitted = st.form_submit_button("保存 API Key 到本机", disabled=os.name != "nt")
        if submitted:
            try:
                if not any(value.strip() for value in entries.values()):
                    st.info("没有填写新密钥；已有配置保持不变。")
                else:
                    vault.update(entries)
                    st.session_state.lab_clear_key_inputs = True
                    st.session_state.lab_key_saved_notice = True
                    st.rerun()
            except (ValueError, OSError) as exc:
                st.error(str(exc))
        if st.session_state.pop("lab_key_saved_notice", False):
            st.success("已加密保存到本机，重启后自动读取；没有调用模型。")
        st.caption(
            "密钥按当前 Windows 账号加密；换账号或电脑需重新填写。不会进入配置、历史或下载文件。"
        )
        with st.expander("删除本机保存的密钥"):
            name = st.selectbox("删除哪一份本机密钥", KEY_NAMES, format_func=LABELS.get)
            if st.button("删除选中的本机密钥", disabled=os.name != "nt"):
                try:
                    vault.delete(name)
                    st.session_state.lab_clear_key_inputs = True
                    st.rerun()
                except (ValueError, OSError) as exc:
                    st.error(str(exc))
            st.caption("仅删除本机保存项；如果环境变量或 secrets 仍有 Key，它们仍可被读取。")
