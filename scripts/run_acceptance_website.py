"""Launch the actual main website with acceptance-only observation hooks.

Set XIAOLI_ACCEPTANCE_OUTPUT to a new project-local evidence directory, then:
  python -m streamlit run scripts/run_acceptance_website.py --server.port 8501

Browser upload, the actual app.py form and production pipeline remain in use.
Only the observer enforces the predeclared one-attempt/six-image acceptance cap.
"""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from run_main_acceptance import DEFAULT_PLAN, install_page_recording

configured_output = os.environ.get("XIAOLI_ACCEPTANCE_OUTPUT", "").strip()
if not configured_output:
    raise ValueError("XIAOLI_ACCEPTANCE_OUTPUT must name a new local acceptance evidence directory")
configured_plan = os.environ.get("XIAOLI_ACCEPTANCE_PLAN", "").strip()
install_page_recording(Path(configured_plan) if configured_plan else DEFAULT_PLAN,
                       Path(configured_output))
runpy.run_path(str(ROOT / "app.py"), run_name="__main__")
