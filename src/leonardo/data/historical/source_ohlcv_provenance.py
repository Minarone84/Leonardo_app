from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import time
from typing import Any, Iterable, Literal, Mapping

from leonardo.data.historical.artifact_metadata_contracts import (
    HistoricalCsvArtifactManifest,
    market_to_dict,
)
from leonardo.data.historical.artifact_metadata_naming import (
    format_ts_ms_rome,
    format_ts_ms_utc,
)
from leonardo.data.historical.dataset_service import (
    evaluate_ohlcv_dataset_loadability,
    format_ohlcv_loadability_error,
)
from leonardo.data.historical.store_csv import CsvOHLCVStore
from leonardo.data.naming import MarketId


SOURCE_OHLCV_PROVENANCE_NAMESPACE = "source_ohlcv"
SOURCE_OHLCV_PROVENANCE_KEY = "snapshot"
SOURCE_OHLCV_PROVENANCE_SCHEMA_VERSION = 1
SOURCE_OHLCV_PROVENANCE_KIND = "source_ohlcv_provenance"

SourceOhlcvDriftStatus = Literal["current", "source_drift", "unknown", "blocked"]


@dataclass(frozen=True)
class SourceOhlcvDriftReport:
    """
    Read-only comparison result for recorded versus current source OHLCV truth.

    The report is JSON-safe and intentionally descriptive. It does not mutate
    metadata, repair OHLCV data, regenerate artifacts, or decide GUI behavior.
    """

    matches: bool
    status: SourceOhlcvDriftStatus
    reasons: tuple[str, ...] = ()
    recorded_summary: dict[str, object] = field(default_factory=dict)
    current_summary: dict[str, object] = field(default_factory=dict)
    actionable: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "matches": bool(self.matches),
            "status": self.status,
            "reasons": list(self.reasons),
            "recorded_summary": dict(self.recorded_summary),
            "current_summary": dict(self.current_summary),
            "actionable": bool(self.actionable),
        }


def extract_source_ohlcv_snapshot(metadata_entries: Iterable[object]) -> dict[str, object] | None:
    """
    Extract the Patch C source OHLCV provenance snapshot from metadata entries.

    Missing snapshots are represented as ``None`` for legacy compatibility.
    Malformed snapshot values are represented with a marker so comparison can
    classify the entry as unknown without failing legacy metadata loading.
    """
    for entry in metadata_entries:
        namespace = str(getattr(entry, "namespace", "") or "")
        key = str(getattr(entry, "key", "") or "")
        if namespace != SOURCE_OHLCV_PROVENANCE_NAMESPACE or key != SOURCE_OHLCV_PROVENANCE_KEY:
            continue
        value = getattr(entry, "value", None)
        if isinstance(value, Mapping):
            return dict(value)
        return {"_invalid_source_ohlcv_snapshot": True}
    return None


def build_source_ohlcv_drift_report(
    *,
    historical_root: Path,
    market: MarketId,
    recorded_snapshot: Mapping[str, Any] | None,
) -> SourceOhlcvDriftReport:
    """
    Compare a recorded source OHLCV snapshot with the current accepted source.

    The current source must still satisfy the shared OHLCV loadability policy.
    A blocked current source prevents regeneration/rebuild actionability without
    modifying the recorded artifact or database metadata.
    """
    root = Path(historical_root)
    loadability = evaluate_ohlcv_dataset_loadability(
        historical_root=root,
        market=market,
    )
    if not loadability.loadable:
        return SourceOhlcvDriftReport(
            matches=False,
            status="blocked",
            reasons=("current_source_ohlcv_not_loadable",),
            recorded_summary=_snapshot_summary(recorded_snapshot),
            current_summary={
                "dataset": market_to_dict(market),
                "loadability_reason": loadability.reason,
                "validation_status": loadability.validation_status,
                "csv_path": None if loadability.csv_path is None else str(loadability.csv_path),
                "metadata_path": (
                    None if loadability.metadata_path is None else str(loadability.metadata_path)
                ),
            },
            actionable=False,
        )

    try:
        current_snapshot = build_source_ohlcv_provenance_snapshot(
            historical_root=root,
            market=market,
        )
    except Exception as exc:
        return SourceOhlcvDriftReport(
            matches=False,
            status="blocked",
            reasons=("current_source_ohlcv_not_loadable",),
            recorded_summary=_snapshot_summary(recorded_snapshot),
            current_summary={
                "dataset": market_to_dict(market),
                "snapshot_error": f"{type(exc).__name__}: {exc}",
            },
            actionable=False,
        )

    return compare_source_ohlcv_snapshots(
        recorded_snapshot=recorded_snapshot,
        current_snapshot=current_snapshot,
    )


def compare_source_ohlcv_snapshots(
    *,
    recorded_snapshot: Mapping[str, Any] | None,
    current_snapshot: Mapping[str, Any] | None,
) -> SourceOhlcvDriftReport:
    """
    Compare stable semantic source OHLCV fields from two provenance snapshots.

    Capture timestamps are intentionally ignored because each snapshot records
    when it was taken, not the source data identity itself.
    """
    if recorded_snapshot is None:
        return SourceOhlcvDriftReport(
            matches=False,
            status="unknown",
            reasons=("missing_recorded_source_ohlcv_snapshot",),
            recorded_summary={},
            current_summary=_snapshot_summary(current_snapshot),
            actionable=True,
        )
    if _snapshot_is_invalid(recorded_snapshot):
        return SourceOhlcvDriftReport(
            matches=False,
            status="unknown",
            reasons=("invalid_recorded_source_ohlcv_snapshot",),
            recorded_summary=_snapshot_summary(recorded_snapshot),
            current_summary=_snapshot_summary(current_snapshot),
            actionable=True,
        )
    if current_snapshot is None or _snapshot_is_invalid(current_snapshot):
        return SourceOhlcvDriftReport(
            matches=False,
            status="blocked",
            reasons=("current_source_ohlcv_not_loadable",),
            recorded_summary=_snapshot_summary(recorded_snapshot),
            current_summary=_snapshot_summary(current_snapshot),
            actionable=False,
        )

    recorded_summary = _snapshot_summary(recorded_snapshot)
    current_summary = _snapshot_summary(current_snapshot)
    reasons: list[str] = []

    if not _stable_equal(recorded_summary.get("dataset"), current_summary.get("dataset")):
        reasons.append("source_dataset_identity_mismatch")
    if recorded_summary.get("validation_status") != current_summary.get("validation_status"):
        reasons.append("source_validation_status_changed")
    if recorded_summary.get("quality_validation_status") != current_summary.get(
        "quality_validation_status"
    ):
        reasons.append("source_quality_status_changed")
    if not _stable_equal(
        recorded_summary.get("validation_fingerprint"),
        current_summary.get("validation_fingerprint"),
    ):
        reasons.append("source_validation_fingerprint_changed")
    if not _stable_equal(
        recorded_summary.get("csv_fingerprint"),
        current_summary.get("csv_fingerprint"),
    ):
        reasons.append("source_csv_fingerprint_changed")
    if recorded_summary.get("source_correction_record_count") != current_summary.get(
        "source_correction_record_count"
    ):
        reasons.append("source_correction_record_count_changed")
    if not _stable_equal(
        recorded_summary.get("source_correction_records"),
        current_summary.get("source_correction_records"),
    ):
        reasons.append("source_correction_records_changed")
    if recorded_summary.get("source_needs_recheck") != current_summary.get(
        "source_needs_recheck"
    ):
        reasons.append("source_needs_recheck_changed")

    if reasons:
        return SourceOhlcvDriftReport(
            matches=False,
            status="source_drift",
            reasons=tuple(reasons),
            recorded_summary=recorded_summary,
            current_summary=current_summary,
            actionable=True,
        )

    return SourceOhlcvDriftReport(
        matches=True,
        status="current",
        reasons=(),
        recorded_summary=recorded_summary,
        current_summary=current_summary,
        actionable=False,
    )


def build_source_ohlcv_provenance_snapshot(
    *,
    historical_root: Path,
    market: MarketId,
) -> dict[str, object]:
    """
    Build a JSON-safe provenance snapshot for an accepted source OHLCV dataset.

    The snapshot records the source dataset identity, current CSV fingerprint,
    accepted validation status, and current source-correction provenance. The
    function does not validate, repair, rewrite, or certify OHLCV data; it
    depends on the shared loadability policy and fails when the source dataset
    is not accepted for data-layer loading.
    """
    root = Path(historical_root)
    loadability = evaluate_ohlcv_dataset_loadability(
        historical_root=root,
        market=market,
    )
    if not loadability.loadable:
        raise PermissionError(
            format_ohlcv_loadability_error(
                loadability,
                context="source OHLCV provenance snapshot",
            )
        )

    csv_path = Path(loadability.csv_path)
    metadata_path = Path(loadability.metadata_path)
    manifest = _load_manifest(metadata_path)

    store = CsvOHLCVStore()
    csv_fingerprint = store.file_fingerprint(csv_path)
    correction_records = store.source_correction_records(csv_path, market=market)
    is_modified = str(loadability.validation_status or "").strip().lower() == "modified"
    captured_at_ms = int(time.time() * 1000)

    return {
        "schema_version": SOURCE_OHLCV_PROVENANCE_SCHEMA_VERSION,
        "kind": SOURCE_OHLCV_PROVENANCE_KIND,
        "captured_at_ms": captured_at_ms,
        "captured_at_utc": format_ts_ms_utc(captured_at_ms),
        "captured_at_rome": format_ts_ms_rome(captured_at_ms),
        "dataset": market_to_dict(market),
        "paths": {
            "csv_relpath": _relative_path(csv_path, root),
            "metadata_relpath": _relative_path(metadata_path, root),
        },
        "validation": {
            "status": loadability.validation_status,
            "quality_validation_status": manifest.quality.validation_status,
            "validator": manifest.validation.validator,
            "validated_at_ms": manifest.validation.validated_at_ms,
            "validated_at": manifest.validation.validated_at,
            "validated_at_rome": manifest.validation.validated_at_rome,
            "row_count": manifest.validation.row_count,
            "issue_count": manifest.validation.issue_count,
            "warning_count": manifest.validation.warning_count,
            "error_count": manifest.validation.error_count,
            "message": manifest.validation.message,
            "fingerprint_fresh": True,
            "csv_fingerprint": manifest.validation.csv_fingerprint.to_dict(),
        },
        "fingerprint": csv_fingerprint.to_dict(),
        "source_correction": {
            "is_modified": is_modified,
            "needs_source_recheck": any(
                bool(record.get("needs_source_recheck")) for record in correction_records
            ),
            "record_count": len(correction_records),
            "provenance_missing": bool(is_modified and not correction_records),
            "records": [dict(record) for record in correction_records],
        },
    }


def _load_manifest(metadata_path: Path) -> HistoricalCsvArtifactManifest:
    try:
        with Path(metadata_path).open("r", encoding="utf-8") as handle:
            return HistoricalCsvArtifactManifest.from_dict(json.load(handle))
    except Exception as exc:
        raise RuntimeError(f"Cannot read accepted OHLCV metadata sidecar: {metadata_path}") from exc


def _relative_path(path: Path, root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def _snapshot_is_invalid(snapshot: Mapping[str, Any]) -> bool:
    if bool(snapshot.get("_invalid_source_ohlcv_snapshot")):
        return True
    return str(snapshot.get("kind", "") or "") not in {"", SOURCE_OHLCV_PROVENANCE_KIND}


def _snapshot_summary(snapshot: Mapping[str, Any] | None) -> dict[str, object]:
    if snapshot is None:
        return {}
    if _snapshot_is_invalid(snapshot):
        return {"invalid": True}

    validation = _mapping_value(snapshot, "validation")
    correction = _mapping_value(snapshot, "source_correction")
    return {
        "dataset": _json_safe(snapshot.get("dataset")),
        "validation_status": _json_safe(validation.get("status")),
        "quality_validation_status": _json_safe(
            validation.get("quality_validation_status")
        ),
        "validation_fingerprint": _json_safe(validation.get("csv_fingerprint")),
        "csv_fingerprint": _json_safe(snapshot.get("fingerprint")),
        "source_correction_record_count": _json_safe(correction.get("record_count")),
        "source_correction_records": _json_safe(correction.get("records", ())),
        "source_needs_recheck": _json_safe(correction.get("needs_source_recheck")),
    }


def _mapping_value(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key)
    if isinstance(value, Mapping):
        return value
    return {}


def _stable_equal(left: object, right: object) -> bool:
    return _stable_json(left) == _stable_json(right)


def _stable_json(value: object) -> str:
    return json.dumps(_json_safe(value), sort_keys=True, separators=(",", ":"))


def _json_safe(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
