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
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

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
    "segmentation",
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


def _validate_gate(gate: Any) -> None:
    if not isinstance(gate, dict):
        raise PreflightError("gate must be an object")
    missing = sorted(GATE_FIELDS - set(gate))
    if missing:
        raise PreflightError(f"gate missing fields: {', '.join(missing)}")
    if gate["status"] != "INTEGRATION_READY":
        raise PreflightError("gate status is not INTEGRATION_READY")
    if not isinstance(gate["commit"], str) or not re.fullmatch(r"[0-9a-fA-F]{40}", gate["commit"]):
        raise PreflightError("gate commit must be a full 40-character Git SHA")
    try:
        frozen = datetime.fromisoformat(gate["frozen_at"])
        if frozen.utcoffset() is None:
            raise ValueError("timezone missing")
    except (TypeError, ValueError) as error:
        raise PreflightError("gate frozen_at must be an ISO datetime with timezone") from error
    health = gate["health"]
    if not isinstance(health, dict) or not all(
        isinstance(health.get(key), str) and health[key].strip()
        for key in ("service", "analysis_mode")
    ):
        raise PreflightError("gate health must identify service and analysis_mode")
    assets = gate["built_assets"]
    if not isinstance(assets, dict) or "mobile/dist/index.html" not in assets:
        raise PreflightError("gate built_assets must include mobile/dist/index.html")
    if not all(
        isinstance(name, str) and isinstance(digest, str)
        and re.fullmatch(r"[0-9a-fA-F]{64}", digest)
        for name, digest in assets.items()
    ):
        raise PreflightError("gate built_assets must map local paths to SHA-256 values")
    segmentation = gate["segmentation"]
    if not isinstance(segmentation, dict) or segmentation.get("backend") not in {
        "grabcut", "mobile_sam",
    } or segmentation.get("device") != "cpu":
        raise PreflightError("gate segmentation must select grabcut or mobile_sam on cpu")
    if segmentation["backend"] == "mobile_sam":
        weights = segmentation.get("weights_path")
        digest = segmentation.get("weights_sha256")
        if not isinstance(weights, str) or not Path(weights).is_absolute() or not (
            isinstance(digest, str) and re.fullmatch(r"[0-9a-fA-F]{64}", digest)
        ):
            raise PreflightError("mobile_sam gate requires an absolute weights_path and SHA-256")
    elif segmentation.get("weights_path") or segmentation.get("weights_sha256") is not None:
        raise PreflightError("grabcut gate must not declare model weights")


class _BuildReferences(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for key, value in attrs:
            if key in {"src", "href"} and value:
                self.urls.append(value)


def _required_build_assets(root: Path) -> set[str]:
    dist = root / "mobile" / "dist"
    index = dist / "index.html"
    if not index.is_file():
        raise PreflightError("current mobile/dist/index.html is missing")
    parser = _BuildReferences()
    parser.feed(index.read_text(encoding="utf-8"))
    required = {"mobile/dist/index.html"}
    for url in parser.urls:
        parsed = urlsplit(url)
        path = unquote(parsed.path)
        if Path(path).suffix.lower() not in {".js", ".mjs", ".css"}:
            continue
        if parsed.scheme or parsed.netloc:
            raise PreflightError("build JS/CSS references must be local")
        asset = (dist / path.lstrip("/")).resolve()
        if not asset.is_relative_to(dist.resolve()):
            raise PreflightError("build JS/CSS reference escapes mobile/dist")
        required.add(asset.relative_to(root).as_posix())
    return required


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
    _validate_gate(gate)
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

    required_assets = _required_build_assets(root)
    check(
        "built_assets_cover_current_index",
        required_assets.issubset(gate["built_assets"]),
        {"required": sorted(required_assets)},
    )
    asset_checks = []
    for relative, expected in (gate.get("built_assets") or {}).items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root / "mobile" / "dist"):
            raise PreflightError("built asset path escapes mobile/dist")
        observed = _hash(path) if path.is_file() else None
        asset_checks.append(
            {"path": relative, "ok": observed == expected, "observed": observed, "expected": expected}
        )
    check("built_assets_match_gate", all(item["ok"] for item in asset_checks), asset_checks)

    segmentation = gate.get("segmentation") or {}
    actual_segmentation = health.get("segmentation")
    if not isinstance(actual_segmentation, dict):
        actual_segmentation = {}
    expected_segmentation = {
        "configured_backend": segmentation["backend"],
        "device": segmentation["device"],
        "weights_sha256": segmentation.get("weights_sha256"),
    }
    check(
        "segmentation_configuration_matches_gate",
        all(key in actual_segmentation and actual_segmentation[key] == value
            for key, value in expected_segmentation.items()),
        {"observed": actual_segmentation, "expected": expected_segmentation},
    )
    last_backend = actual_segmentation.get("last_actual_backend")
    last_weights = actual_segmentation.get("last_weights_sha256")
    proven = actual_segmentation.get("inference_proven")
    evidence_fields = {"last_actual_backend", "last_weights_sha256", "inference_proven"}
    evidence_ok = evidence_fields.issubset(actual_segmentation) and (
        (proven is False and last_backend is None and last_weights is None)
        or (proven is True and last_backend == "grabcut" and last_weights is None)
        or (proven is True and last_backend == "mobile_sam"
            and segmentation["backend"] == "mobile_sam"
            and last_weights == segmentation.get("weights_sha256"))
    )
    check("segmentation_execution_evidence_consistent", evidence_ok, {
        "inference_proven": proven, "last_actual_backend": last_backend,
        "last_weights_sha256": last_weights,
    })
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
        "segmentation": actual_segmentation,
        "checks": checks,
        "ok": all(item["ok"] for item in checks),
        "read_only": True,
        "generated_model_requests": 0,
        "health_get_requests": 1,
    }
    if not report["ok"]:
        failed = [item["name"] for item in checks if not item["ok"]]
        raise PreflightError(f"preflight failed: {', '.join(failed)}")
    return report
