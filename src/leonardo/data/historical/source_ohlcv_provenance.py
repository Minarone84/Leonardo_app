from __future__ import annotations

import json
from pathlib import Path
import time

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
