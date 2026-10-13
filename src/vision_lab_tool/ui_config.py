import streamlit as st
from pydantic import ValidationError

from vision_lab_tool.configuration import PRESETS
from vision_lab_tool.models import ModelConfig, Price


def edit_configs(store, secrets):
    with st.expander("编辑 / 新增模型配置"):
        st.caption("预设是可编辑示例。模型 ID、图片和推理能力须在服务商控制台确认。")
        configs = st.session_state.lab_configs
        selected = st.selectbox(
            "编辑配置",
            [c.config_id for c in configs],
            format_func=lambda cid: next(c.name for c in configs if c.config_id == cid),
        )
        config = next(c for c in configs if c.config_id == selected)
        p = f"config:{selected}:"
        with st.form(p + "form"):
            name = st.text_input("配置名称", config.name)
            provider = st.text_input("服务商", config.provider)
            options = ["mock", "chat", "responses", "anthropic", "gemini"]
            protocol = st.selectbox("协议", options, index=options.index(config.protocol))
            base_url = st.text_input("Base URL（不含接口路径和密钥）", config.base_url)
            model_id = st.text_input("模型 ID（可手动填写）", config.model_id)
            key_env = st.text_input("密钥环境变量 / secrets 名称", config.key_env)
            timeout = st.number_input("超时（秒）", 1.0, 600.0, float(config.timeout))
            max_output = st.number_input("最大输出 token", 128, 65536, config.max_output)
            details = ["omit", "auto", "low", "high"]
            detail = st.selectbox(
                "图片 detail（按已确认能力选择）", details, index=details.index(config.detail)
            )
            structures = ["prompt", "json_object", "json_schema"]
            structured = st.selectbox(
                "结构化输出方式", structures, index=structures.index(config.structured)
            )
            reasoning_options = [
                "omit",
                "enable_thinking",
                "thinking_type",
                "effort",
                "budget_tokens",
                "thinking_budget",
            ]
            reasoning = st.selectbox(
                "推理参数（按已确认能力选择）",
                reasoning_options,
                index=reasoning_options.index(config.reasoning),
            )
            reasoning_value = st.text_input("推理参数值", config.reasoning_value)
            cases = ["correct", "omission", "malformed", "invalid_box", "failure"]
            mock_case = st.selectbox("模拟夹具", cases, index=cases.index(config.mock_case))
            st.caption("price 单位为每百万 token，留空表示未知；估算必须有来源与核价日期。")
            price_input = st.text_input(
                "输入单价",
                ""
                if config.price.input_per_million is None
                else str(config.price.input_per_million),
            )
            price_output = st.text_input(
                "输出单价",
                ""
                if config.price.output_per_million is None
                else str(config.price.output_per_million),
            )
            price_cache = st.text_input(
                "缓存读取单价",
                ""
                if config.price.cache_per_million is None
                else str(config.price.cache_per_million),
            )
            price_write = st.text_input(
                "缓存写入单价（如 Anthropic）",
                ""
                if config.price.cache_write_per_million is None
                else str(config.price.cache_write_per_million),
            )
            currency = st.selectbox(
                "币种", ["CNY", "USD"], index=["CNY", "USD"].index(config.price.currency)
            )
            source = st.text_input("价格来源 URL", config.price.source_url)
            date = st.text_input("核价日期（YYYY-MM-DD）", config.price.checked_on)
            limitations = st.text_input("估算范围 / 特殊计费限制", config.price.limitations)
            apply = st.form_submit_button("应用配置")
        if apply:
            try:
                price = Price(
                    input_per_million=float(price_input) if price_input.strip() else None,
                    output_per_million=float(price_output) if price_output.strip() else None,
                    cache_per_million=float(price_cache) if price_cache.strip() else None,
                    cache_write_per_million=float(price_write) if price_write.strip() else None,
                    currency=currency,
                    source_url=source,
                    checked_on=date,
                    limitations=limitations,
                )
                edited = ModelConfig(
                    config_id=config.config_id,
                    name=name,
                    provider=provider,
                    protocol=protocol,
                    base_url=base_url,
                    model_id=model_id,
                    key_env=key_env,
                    timeout=timeout,
                    max_output=max_output,
                    detail=detail,
                    structured=structured,
                    reasoning=reasoning,
                    reasoning_value=reasoning_value,
                    mock_case=mock_case,
                    price=price,
                )
                configs[configs.index(config)] = edited
                st.success("已应用到会话；尚未请求模型。")
            except (ValidationError, ValueError) as exc:
                st.error(f"配置非法：{exc}")
        preset = st.selectbox("新增配置模板", list(PRESETS))
        if st.button("新增独立配置"):
            configs.append(ModelConfig(name=preset + f" #{len(configs) + 1}", **PRESETS[preset]))
            st.rerun()
        if st.button("保存配置到本地"):
            store.save_configs(configs, secrets)
            st.session_state.lab_config_load_failed = False
            st.success("已保存。仅保存密钥变量名，不保存临时密钥。")
