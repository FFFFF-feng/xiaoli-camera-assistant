"""Read stored run manifests without silently resolving ambiguous evidence."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_MISSING = object()


@dataclass(frozen=True)
class ManifestCase:
    case_id: str
    title: str | None
    photo: Path | None
    sha256: str | None
    intent: str | None
    request: dict[str, Any] | None
    sources: tuple[str, ...]
    diagnostics: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class ManifestView:
    cases: dict[str, ManifestCase]
    sources: tuple[str, ...]
    diagnostics: tuple[dict[str, Any], ...]

    def case(self, case_id: str) -> ManifestCase | None:
        return self.cases.get(case_id)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _diagnostic(
    code: str,
    *,
    source: str | None = None,
    field: str | None = None,
    value: Any = _MISSING,
    detail: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {"code": code}
    if source is not None:
        row["source"] = source
    if field is not None:
        row["field"] = field
    if value is not _MISSING:
        row["value"] = value
    if detail is not None:
        row["detail"] = detail
    return row


def _text(entry: dict[str, Any], key: str) -> str | None:
    value = entry.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _request(entry: dict[str, Any], diagnostics: list[dict[str, Any]]) -> dict[str, Any] | None:
    value = entry.get("request")
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    diagnostics.append(_diagnostic("invalid_request_type", field="request"))
    return None


def _sha256(entry: dict[str, Any], diagnostics: list[dict[str, Any]]) -> str | None:
    value = entry.get("sha256")
    if value is None:
        diagnostics.append(_diagnostic("sha256_missing", field="sha256"))
        return None
    if not isinstance(value, str) or not value.strip():
        diagnostics.append(_diagnostic("sha256_invalid", field="sha256"))
        return None
    if not _SHA256.fullmatch(value):
        diagnostics.append(
            _diagnostic("sha256_format_invalid", field="sha256", value=value)
        )
    return value


def _photo(value: Any, *, source: str, field: str, diagnostics: list[dict[str, Any]]) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        diagnostics.append(_diagnostic("photo_invalid", source=source, field=field))
        return None
    if "://" in value or value.lower().startswith(("http:", "https:", "file:")):
        diagnostics.append(
            _diagnostic("photo_url_not_supported", source=source, field=field, value=value)
        )
        return None
    path = Path(value)
    if not path.is_absolute():
        diagnostics.append(
            _diagnostic("photo_not_absolute", source=source, field=field, value=value)
        )
        return None
    return path


def _entry_photo(
    entry: dict[str, Any], *, source: str, diagnostics: list[dict[str, Any]]
) -> Path | None:
    single = entry.get("photo")
    plural = entry.get("photos")
    single_present = single is not None
    plural_present = plural is not None
    single_path = (
        _photo(single, source=source, field="photo", diagnostics=diagnostics)
        if single_present
        else None
    )
    plural_path: Path | None = None
    if plural_present:
        if not isinstance(plural, list):
            diagnostics.append(_diagnostic("photos_invalid", source=source, field="photos"))
        elif len(plural) != 1:
            diagnostics.append(
                _diagnostic(
                    "photos_count_ambiguous",
                    source=source,
                    field="photos",
                    value=len(plural),
                )
            )
        else:
            plural_path = _photo(
                plural[0], source=source, field="photos[0]", diagnostics=diagnostics
            )

    if not single_present and not plural_present:
        diagnostics.append(_diagnostic("photo_missing", source=source, field="photo/photos"))
        return None

    if single_present and plural_present:
        if single_path is None or plural_path is None:
            diagnostics.append(
                _diagnostic("photo_fields_ambiguous", source=source, field="photo/photos")
            )
            return None
    elif (
        (single_present and single_path is None)
        or (plural_present and plural_path is None)
    ):
        return None

    if single_path is not None and plural_path is not None:
        if single_path != plural_path:
            diagnostics.append(
                _diagnostic(
                    "photo_fields_conflict",
                    source=source,
                    field="photo/photos",
                    value=[str(single_path), str(plural_path)],
                )
            )
            return None
        diagnostics.append(_diagnostic("photo_fields_agree", source=source, field="photo/photos"))
    return single_path or plural_path


def normalize_manifest(manifest: dict[str, Any] | None) -> ManifestView:
    """Normalize old ``samples/photos`` and new ``cases/photo`` manifests.

    Duplicate IDs, conflicting photo fields, malformed paths and conflicting
    source metadata are retained as diagnostics and resolve to ``None``.
    """
    if not isinstance(manifest, dict):
        return ManifestView(
            cases={},
            sources=(),
            diagnostics=(_diagnostic("manifest_not_an_object"),),
        )

    grouped: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    diagnostics: list[dict[str, Any]] = []
    sources: list[str] = []
    for section in ("samples", "cases"):
        rows = manifest.get(section, _MISSING)
        if rows is _MISSING:
            continue
        if not isinstance(rows, list):
            diagnostics.append(_diagnostic("manifest_section_not_a_list", field=section))
            continue
        sources.append(section)
        for index, entry in enumerate(rows):
            if not isinstance(entry, dict):
                diagnostics.append(
                    _diagnostic("manifest_entry_not_an_object", source=section, field=str(index))
                )
                continue
            case_id = _text(entry, "id")
            if case_id is None:
                diagnostics.append(
                    _diagnostic("manifest_case_id_missing", source=section, field=str(index))
                )
                continue
            grouped.setdefault(case_id, []).append((section, entry))

    cases: dict[str, ManifestCase] = {}
    for case_id, matches in grouped.items():
        case_diagnostics: list[dict[str, Any]] = []
        case_sources = tuple(source for source, _ in matches)
        if len(matches) != 1:
            case_diagnostics.append(
                _diagnostic(
                    "duplicate_case_id",
                    field="id",
                    value=case_id,
                    detail="duplicate IDs are ambiguous; no entry was selected",
                )
            )
            diagnostics.append(
                _diagnostic(
                    "duplicate_case_id",
                    field="id",
                    value=case_id,
                    detail=f"sources={','.join(case_sources)}",
                )
            )
            cases[case_id] = ManifestCase(
                case_id=case_id,
                title=None,
                photo=None,
                sha256=None,
                intent=None,
                request=None,
                sources=case_sources,
                diagnostics=tuple(case_diagnostics),
            )
            continue

        source, entry = matches[0]
        photo = _entry_photo(entry, source=source, diagnostics=case_diagnostics)
        recorded_sha256 = _sha256(entry, case_diagnostics)
        request = _request(entry, case_diagnostics)
        cases[case_id] = ManifestCase(
            case_id=case_id,
            title=_text(entry, "title"),
            photo=photo,
            sha256=recorded_sha256,
            intent=_text(entry, "intent"),
            request=request,
            sources=case_sources,
            diagnostics=tuple(case_diagnostics),
        )
    return ManifestView(cases=cases, sources=tuple(sources), diagnostics=tuple(diagnostics))


def verify_original(case: ManifestCase | None) -> dict[str, Any]:
    """Verify one manifest photo without substituting another file."""
    if case is None:
        return {
            "status": "manifest_case_missing",
            "path": None,
            "exists": False,
            "sha256_recorded": None,
            "sha256_observed": None,
            "sha256_matches": False,
            "usable": False,
            "diagnostics": [_diagnostic("manifest_case_missing")],
        }
    diagnostics = [dict(item) for item in case.diagnostics]
    if case.photo is None:
        status = "manifest_ambiguous"
        exists = False
        observed = None
    elif not case.photo.is_file():
        status = "missing_file"
        exists = False
        observed = None
    else:
        exists = True
        observed = sha256_file(case.photo)
        if case.sha256 is None:
            status = "hash_unrecorded"
        elif not _SHA256.fullmatch(case.sha256):
            status = "hash_format_invalid"
        elif observed.lower() != case.sha256.lower():
            status = "hash_mismatch"
        else:
            status = "verified"
    usable = status == "verified"
    return {
        "status": status,
        "path": str(case.photo) if case.photo is not None else None,
        "exists": exists,
        "sha256_recorded": case.sha256,
        "sha256_observed": observed,
        "sha256_matches": status == "verified",
        "usable": usable,
        "diagnostics": diagnostics,
    }


def _source_candidates(
    summary: dict[str, Any],
    manifest: dict[str, Any] | None,
    field: str,
) -> list[tuple[str, Any]]:
    candidates: list[tuple[str, Any]] = []
    summary_fingerprint = summary.get("source_fingerprint")
    manifest_fingerprint = (manifest or {}).get("source_fingerprint")
    if isinstance(summary_fingerprint, dict):
        candidates.append((f"summary.source_fingerprint.{field}", summary_fingerprint.get(field)))
    if isinstance(manifest_fingerprint, dict):
        candidates.append(
            (f"manifest.source_fingerprint.{field}", manifest_fingerprint.get(field))
        )
    candidates.extend(
        [
            (f"summary.{field}", summary.get(field)),
            (f"manifest.{field}", (manifest or {}).get(field)),
        ]
    )
    return [
        (source, value)
        for source, value in candidates
        if isinstance(value, str) and value.strip()
    ]


def _resolve_source_field(
    summary: dict[str, Any],
    manifest: dict[str, Any] | None,
    field: str,
    diagnostics: list[dict[str, Any]],
) -> str | None:
    candidates = _source_candidates(summary, manifest, field)
    values = {value for _, value in candidates}
    if len(values) > 1:
        diagnostics.append(
            _diagnostic(
                "source_field_conflict",
                field=field,
                value=[{"source": source, "value": value} for source, value in candidates],
            )
        )
        return None
    return next(iter(values), None)


def _dirty_state(
    summary: dict[str, Any],
    manifest: dict[str, Any] | None,
    diagnostics: list[dict[str, Any]],
) -> tuple[str, list[str] | None]:
    candidates = [
        (source, value)
        for source, value in (
            ("summary.dirty_files", summary.get("dirty_files")),
            ("manifest.dirty_files", (manifest or {}).get("dirty_files")),
        )
        if value is not None
    ]
    normalized: list[tuple[str, tuple[str, ...] | None]] = []
    for source, value in candidates:
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            diagnostics.append(_diagnostic("dirty_state_invalid", source=source))
            normalized.append((source, None))
            continue
        normalized.append((source, tuple(value)))
    distinct = {value for _, value in normalized if value is not None}
    if len(distinct) > 1 or any(value is None for _, value in normalized):
        diagnostics.append(_diagnostic("dirty_state_conflict", field="dirty_files"))
        return "unknown_conflict", None
    if not distinct:
        return "unrecorded_by_run_manifest", None
    files = list(next(iter(distinct)))
    return ("recorded_clean" if not files else "recorded_dirty", files)


def normalize_source(
    summary: dict[str, Any],
    manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    """Resolve recorded source identity without consulting current process state."""
    diagnostics: list[dict[str, Any]] = []
    summary_fingerprint = summary.get("source_fingerprint")
    manifest_fingerprint = (manifest or {}).get("source_fingerprint")
    if summary_fingerprint is not None and not isinstance(summary_fingerprint, dict):
        diagnostics.append(_diagnostic("summary_source_fingerprint_invalid"))
    if manifest_fingerprint is not None and not isinstance(manifest_fingerprint, dict):
        diagnostics.append(_diagnostic("manifest_source_fingerprint_invalid"))

    git_sha = _resolve_source_field(summary, manifest, "git_sha", diagnostics)
    source_tree_sha256 = _resolve_source_field(
        summary, manifest, "source_tree_sha256", diagnostics
    )
    tracked_diff_sha256 = _resolve_source_field(
        summary, manifest, "tracked_diff_sha256", diagnostics
    )
    dirty, dirty_files = _dirty_state(summary, manifest, diagnostics)
    fingerprint = {
        key: value
        for key, value in (
            ("git_sha", git_sha),
            ("source_tree_sha256", source_tree_sha256),
            ("tracked_diff_sha256", tracked_diff_sha256),
        )
        if value is not None
    }
    if any(item["code"] == "source_field_conflict" for item in diagnostics):
        note = (
            "Recorded source fields conflict. Version identity is unknown; "
            "review source.diagnostics before cross-version comparison."
        )
    elif git_sha or source_tree_sha256:
        note = (
            "Source identity comes only from the saved summary/manifest. "
            "Offline replay does not consult the current checkout, model, or service."
        )
    else:
        note = (
            "Source identity was not recorded. Do not infer it from the current "
            "checkout, default model, or service configuration."
        )
    return {
        "git_sha": git_sha,
        "source_fingerprint": fingerprint or None,
        "source_tree_sha256": source_tree_sha256,
        "tracked_diff_sha256": tracked_diff_sha256,
        "dirty": dirty,
        "dirty_files": dirty_files,
        "diagnostics": diagnostics,
        "note": note,
    }
