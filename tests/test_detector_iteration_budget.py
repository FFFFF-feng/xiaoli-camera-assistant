"""Paid-call reservations stay bounded under concurrent batch processes."""
import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "iteration_cli", Path(__file__).resolve().parents[1] / "scripts/run_detector_iteration.py")
iteration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(iteration)


def test_concurrent_reservations_cannot_exceed_real_budget(tmp_path):
    def reserve(index):
        try:
            iteration.reserve_unit(tmp_path, f"unit{index}", "paired")
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        admitted = list(pool.map(reserve, range(40)))
    ledger = json.loads((tmp_path / "request_ledger.json").read_text("utf-8"))
    assert sum(admitted) == len(ledger) == 30
    assert len({row["unit"] for row in ledger}) == 30
    assert not (tmp_path / "request_ledger.lock").exists()


def test_failed_or_unfinished_attempt_cannot_automatically_retry(tmp_path):
    iteration.reserve_unit(tmp_path, "v0/image/paired", "paired")
    with pytest.raises(ValueError, match="Previous attempted"):
        iteration.reserve_unit(tmp_path, "v0/image/paired", "paired")
    ledger = json.loads((tmp_path / "request_ledger.json").read_text("utf-8"))
    assert len(ledger) == 1
    assert ledger[0]["status"] == "reserved_before_execution"
