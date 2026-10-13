import os
import subprocess
import sys
from pathlib import Path


def test_real_entrypoint_import_from_project_root():
    root = Path(__file__).resolve().parents[1]
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-c", "from vision_lab_tool.ui import main; print(callable(main))"],
        cwd=root,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
