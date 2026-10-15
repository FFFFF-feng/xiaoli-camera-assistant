"""Zero-API saved-result UI using the production app's actual rendering functions."""
import ast
import base64
import json
import sys
from pathlib import Path

import httpx
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from camera_assistant.models import PipelineResult


def forbidden(*args, **kwargs):
    raise AssertionError("Saved-result replay forbids model HTTP requests")


httpx.Client.post = forbidden
st.set_page_config(page_title="小栗定向验收结果回看｜0 API", layout="centered")
source = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
definitions = [node for node in source.body if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef))
               or isinstance(node, ast.Assign) and any(
                   isinstance(target, ast.Name) and target.id in {
                       "ROOT", "SESSION_SCHEMA_VERSION", "PIPELINE_RESOURCE_VERSION"}
                   for target in node.targets)]
namespace = {"__file__": str(ROOT / "app.py"), "__name__": "saved_production_renderer"}
exec(compile(ast.Module(body=definitions, type_ignores=[]), str(ROOT / "app.py"), "exec"), namespace)  # noqa: S102 - trusted local production renderer definitions only
namespace["load_css"]()
OUT = ROOT / "data/history/main-targeted-20261015"
paths = {
    "旧D17缺失提示": ROOT / "data/history/main-acceptance-20261014/live/D17-pipeline.json",
    "D17新完整流程": OUT / "live/D17-pipeline.json",
    "D01新完整流程": OUT / "live/D01-pipeline.json",
    "B08仅构图": OUT / "composition/only/B08-pipeline.json",
    "D10仅构图": OUT / "composition/only/D10-pipeline.json",
    "P03有库参数": OUT / "parameters/with/P03-pipeline.json",
    "D17有库参数": OUT / "parameters/with/D17-pipeline.json",
    "P03截断后保留构图": OUT / "parameters/without/P03-pipeline.json",
    "D17最终规则重审（0 API）": OUT / "post-acceptance-rule-review/live/D17-pipeline.json",
    "D01最终规则重审（0 API）": OUT / "post-acceptance-rule-review/live/D01-pipeline.json",
}
paths = {label: path for label, path in paths.items() if path.exists()}
st.warning("保存结果的零API页面回看；这不是新的模型生成，也不是独立真人摄影师验收。")
choice = st.selectbox("保存结果回看（0 新 API）", list(paths))
path = paths[choice]
data = json.loads(path.read_text(encoding="utf-8"))
case_id = path.name.split("-", 1)[0]
sent = ROOT / f"data/history/main-acceptance-20261014/live/{case_id}-sent.jpg"
data["inspection"]["model_image_data_url"] = "data:image/jpeg;base64," + base64.b64encode(sent.read_bytes()).decode("ascii")
namespace["render_result"](PipelineResult.model_validate(data))
st.caption("本次回看记录：" + choice + " · 0 API")
