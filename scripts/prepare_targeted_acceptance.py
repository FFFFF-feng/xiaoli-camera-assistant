"""Freeze controls and old evidence before the bounded 2026-10-15 acceptance."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from main_round_support import database_contents

OUT = ROOT / "data/history/main-targeted-20261015"


def hashes(paths):
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(set(paths)) if p.is_file()}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "start-state.json"
    if target.exists():
        raise SystemExit("Start state already frozen; refusing to overwrite")
    old = ROOT / "data/history/main-acceptance-20261014"
    frozen = [ROOT / "vision_lab.py", *(ROOT / "src/vision_lab_tool").rglob("*.py")]
    state = {
        "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "old_evidence_sha256": hashes(old.rglob("*")),
        "frozen_experiment_sha256": hashes(frozen),
        "production_database": database_contents(ROOT / "data/knowledge.db"),
        "git_status": subprocess.run(["git", "status", "--short"], cwd=ROOT,
                                      capture_output=True, text=True, check=True).stdout,
        "ancestor_agents": [str(p) for p in [ROOT / "AGENTS.md", *[
            parent / "AGENTS.md" for parent in ROOT.parents]] if p.exists()],
        "note": "Snapshot taken during read-only root investigation; domain agents work only assigned code/new evidence.",
    }
    target.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    diff = subprocess.run(["git", "diff", "--binary"], cwd=ROOT,
                          capture_output=True, check=True).stdout
    (OUT / "start-worktree.patch").write_bytes(diff)
    print(json.dumps({"old_files": len(state["old_evidence_sha256"]),
                      "frozen_files": len(state["frozen_experiment_sha256"]),
                      "agents": state["ancestor_agents"], "api_calls": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
