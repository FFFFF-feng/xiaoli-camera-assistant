"""Zero-API visual replay of saved real results using the unchanged app.py renderer."""
from __future__ import annotations

import base64
import json
import runpy
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from camera_assistant.models import PipelineResult
from camera_assistant.pipeline import CameraAssistantPipeline


def no_generation(*args, **kwargs):
    raise RuntimeError("Saved-result replay forbids new model generation")


CameraAssistantPipeline.run = no_generation
case = st.selectbox("保存的真实结果回看（0 新 API）", ["P02", "P03", "B08", "D10", "D17", "D01"])
st.info("仅回看本轮已保存的真实输出并检查页面布局；这不是新一轮生成或实拍。")
evidence = ROOT / "data/history/main-acceptance-20261014/live"
saved = json.loads((evidence / f"{case}-pipeline.json").read_text(encoding="utf-8"))
saved["inspection"]["model_image_data_url"] = "data:image/jpeg;base64," + base64.b64encode(
    (evidence / f"{case}-sent.jpg").read_bytes()).decode("ascii")
st.session_state["schema_version"] = 10
st.session_state["last_result"] = PipelineResult.model_validate(saved)
runpy.run_path(str(ROOT / "app.py"), run_name="__main__")
