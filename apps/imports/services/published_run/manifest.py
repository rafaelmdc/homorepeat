from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import (
    ImportContractError,
    MANIFEST_REQUIRED_KEYS,
    V2ArtifactPaths,
    V2_MANIFEST_REQUIRED_KEYS,
)
from .iterators import _parse_timestamp, _string_value


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ImportContractError(f"Required import artifact is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ImportContractError(f"Malformed run manifest JSON: {path}") from exc

    if not isinstance(payload, dict):
        raise ImportContractError(f"Run manifest must contain a top-level JSON object: {path}")

    missing = [key for key in MANIFEST_REQUIRED_KEYS if key not in payload]
    if missing:
        raise ImportContractError(f"Run manifest is missing required keys: {', '.join(missing)}")
    return payload


def _normalize_pipeline_run(
    manifest: dict[str, Any],
    artifact_paths: V2ArtifactPaths,
) -> dict[str, Any]:
    return {
        "run_id": _require_manifest_value(manifest, "run_id"),
        "status": _require_manifest_value(manifest, "status"),
        "profile": _require_manifest_value(manifest, "profile"),
        "acquisition_publish_mode": _require_manifest_value(manifest, "acquisition_publish_mode"),
        "git_revision": _string_value(manifest.get("git_revision")),
        "started_at_utc": _parse_timestamp(manifest.get("started_at_utc"), "started_at_utc"),
        "finished_at_utc": _parse_timestamp(manifest.get("finished_at_utc"), "finished_at_utc"),
        "manifest_path": str(artifact_paths.manifest),
        "publish_root": str(artifact_paths.publish_root),
        "manifest_payload": manifest,
    }


def _ensure_v2_contract(manifest: dict[str, Any]) -> None:
    missing = [key for key in V2_MANIFEST_REQUIRED_KEYS if key not in manifest]
    if missing:
        raise ImportContractError(
            "Run manifest is missing required publish contract v2 keys: "
            f"{', '.join(missing)}"
        )

    value = manifest.get("publish_contract_version")
    if value != 2:
        raise ImportContractError(
            f"Unsupported publish_contract_version={value!r}; expected 2."
        )


def _require_manifest_value(manifest: dict[str, Any], key: str) -> str:
    value = _string_value(manifest.get(key))
    if not value:
        raise ImportContractError(f"Run manifest contains an empty required value for {key!r}")
    return value
