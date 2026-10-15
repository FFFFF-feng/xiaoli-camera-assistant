"""Actual app.py form on 8501, with one-attempt observation guards only."""
import runpy
from pathlib import Path

from run_targeted_acceptance import install_page_recording

install_page_recording()
runpy.run_path(str(Path(__file__).resolve().parents[1] / "app.py"), run_name="__main__")
