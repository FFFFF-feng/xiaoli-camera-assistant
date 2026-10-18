"""Verify that a service is the frozen integrated version before any upload.

The gate file is written by A after integration. E never edits product code or
starts the shared service; this module only reads Git, process, port, build and
health facts and refuses to continue when they disagree.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from .evidence import load_json
from .ledger import Ledger

GATE_FIELDS = {
    "status",
    "commit",
    "branch",
    "source_root",
    "source_tree_sha256",
    "dirty_files",
    "port",
    "pid",
    "built_assets",
    "health",
    "frozen_at",
}


class PreflightError(RuntimeError):
    """Raised when the running service cannot be tied to the frozen version."""


def _run(*args: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True, encoding="utf-8", errors="replace")


def source_fingerprint(root: Path) -> dict[str, Any]:
    """Mirror A's source fingerprint so dirty content cannot masquerade as HEAD."""
    files: list[Path] = []
    for folder in (root / "src", root / "mobile" / "src", root / "mobile" / "tests", root / "tests"):
        if folder.is_dir():
            files.extend(
                path
                for path in folder.rglob("*")
                if path.is_file() and path.suffix in {".py", ".mjs", ".ts", ".vue", ".css"}
            )
    digests = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(files)
    }
    return {
        "git_sha": _run("git", "rev-parse", "HEAD", cwd=root).strip(),
        "tracked_diff_sha256": hashlib.sha256(
            subprocess.check_output(["git", "diff", "--binary", "HEAD"], cwd=root)
        ).hexdigest(),
        "source_tree_sha256": hashlib.sha256(
            json.dumps(digests, sort_keys=True).encode()
        ).hexdigest(),
        "source_files": digests,
    }


def dirty_files(root: Path) -> list[str]:
    raw = _run("git", "status", "--porcelain", cwd=root)
    return sorted(line[3:] for line in raw.splitlines() if line.strip())


def listening_pid(port: int) -> int | None:
    """Return the PID listening on 127.0.0.1:<port> using netstat output."""
    try:
        raw = _run("netstat", "-ano")
    except (OSError, subprocess.CalledProcessError):
        return None
    pattern = re.compile(rf"^\s*(?:TCP)\s+\S+:{port}\s+\S+\s+LISTENING\s+(\d+)\s*$", re.IGNORECASE)
    for line in raw.splitlines():
        match = pattern.match(line)
        if match:
            return int(match.group(1))
    return None


def process_command(pid: int) -> str | None:
    script = (
        "Get-CimInstance Win32_Process -Filter \"ProcessId = "
        f"{int(pid)}\" | Select-Object -ExpandProperty CommandLine"
    )
    try:
        output = _run("powershell.exe", "-NoProfile", "-Command", script).strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return output or None


def health_snapshot(origin: str, timeout: float = 10.0) -> dict[str, Any]:
    import httpx

    with httpx.Client(
        base_url=origin, timeout=timeout, trust_env=False,
        transport=httpx.HTTPTransport(retries=0),
    ) as client:
        response = client.get("/health")
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise PreflightError("health response is not an object")
    return payload


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(
    gate_path: Path,
    ledger_path: Path,
    *,
    explicit_live: bool = False,
) -> dict[str, Any]:
    """Verify the gate, Git state, process identity, build and health.

    ``explicit_live=False`` still performs read-only checks; callers that only
    want a dry run pass it and use the returned report. Any upload path must
    pass ``True``.
    """
    gate = load_json(gate_path)
    missing = sorted(GATE_FIELDS - set(gate))
    if missing:
        raise PreflightError(f"gate missing fields: {', '.join(missing)}")
    if gate["status"] != "INTEGRATION_READY":
        raise PreflightError("gate status is not INTEGRATION_READY")
    ledger = Ledger.load(ledger_path)
    if explicit_live:
        ledger.require_live_allowed(explicit_live=True, integration_gate=gate_path)

    root = Path(gate["source_root"]).resolve()
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    head = _run("git", "rev-parse", "HEAD", cwd=root).strip()
    check("git_head_matches_gate", head == gate["commit"], {"head": head, "gate": gate["commit"]})
    branch = _run("git", "rev-parse", "--abbrev-ref", "HEAD", cwd=root).strip()
    check("branch_matches_gate", branch == gate["branch"], {"branch": branch, "gate": gate["branch"]})

    fingerprint = source_fingerprint(root)
    check(
        "source_tree_matches_gate",
        fingerprint["source_tree_sha256"] == gate["source_tree_sha256"],
        {
            "observed": fingerprint["source_tree_sha256"],
            "gate": gate["source_tree_sha256"],
        },
    )
    observed_dirty = dirty_files(root)
    check(
        "dirty_inventory_matches_gate",
        observed_dirty == sorted(gate["dirty_files"]),
        {"observed": observed_dirty, "gate": sorted(gate["dirty_files"])},
    )

    port = int(gate["port"])
    pid = listening_pid(port)
    check(
        "port_owned_by_gate_pid",
        pid == int(gate["pid"]),
        {"observed_pid": pid, "gate_pid": int(gate["pid"]), "port": port},
    )
    command = process_command(int(gate["pid"])) if pid is not None else None
    check(
        "process_command_contains_source_root",
        bool(command and str(root).lower() in command.lower()),
        {"command": command},
    )

    origin = f"http://127.0.0.1:{port}"
    health = health_snapshot(origin)
    expected_health = gate.get("health") or {}
    health_ok = all(health.get(key) == value for key, value in expected_health.items())
    check("health_matches_gate", health_ok, {"observed": health, "expected": expected_health})

    asset_checks = []
    for relative, expected in (gate.get("built_assets") or {}).items():
        path = (root / relative).resolve()
        observed = _hash(path) if path.is_file() else None
        asset_checks.append(
            {"path": relative, "ok": observed == expected, "observed": observed, "expected": expected}
        )
    check("built_assets_match_gate", all(item["ok"] for item in asset_checks), asset_checks)

    segmentation = gate.get("segmentation") or {}
    weights = segmentation.get("weights_path")
    weights_sha = segmentation.get("weights_sha256")
    if weights and weights_sha:
        weights_path = Path(weights)
        observed = _hash(weights_path) if weights_path.is_file() else None
        check(
            "segmentation_weights_match_gate",
            observed == weights_sha,
            {"path": weights, "observed": observed, "expected": weights_sha},
        )
    else:
        check(
            "segmentation_weights_recorded",
            segmentation.get("backend") == "grabcut",
            {"segmentation": segmentation},
        )

    report = {
        "schema": "line-drawing-preflight-v1",
        "gate": str(gate_path),
        "ledger": str(ledger_path),
        "origin": origin,
        "source_fingerprint": {key: value for key, value in fingerprint.items() if key != "source_files"},
        "health": health,
        "checks": checks,
        "ok": all(item["ok"] for item in checks),
        "read_only": True,
        "generated_model_requests": 0,
    }
    if not report["ok"]:
        failed = [item["name"] for item in checks if not item["ok"]]
        raise PreflightError(f"preflight failed: {', '.join(failed)}")
    return report
