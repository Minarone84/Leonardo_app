from __future__ import annotations

import csv
import json
import os
import tempfile
import time
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterable, List, Dict

from leonardo.data.naming import MarketId, canonicalize

from .artifact_metadata_contracts import (
    ARTIFACT_METADATA_SCHEMA_VERSION,
    HISTORICAL_CSV_ARTIFACT_TYPE,
    ArtifactColumnMetadata,
    ArtifactFiles,
    ArtifactFingerprint,
    ArtifactIdentity,
    ArtifactLineage,
    ArtifactMetadataEntry,
    ArtifactQuality,
    ArtifactShape,
    ArtifactTimeRange,
    ArtifactValidationMetadata,
    HistoricalCsvArtifactManifest,
    metadata_files_from_csv,
)
from .artifact_metadata_naming import (
    build_artifact_id,
    build_artifact_uid,
    metadata_path_for_csv,
    new_unique_id,
)
from .paths import storage_segment_to_timeframe

SOURCE_CORRECTIONS_METADATA_NAMESPACE = "ohlcv"
SOURCE_CORRECTIONS_METADATA_KEY = "source_corrections"


@dataclass(frozen=True)
class Candle:
    """
    Canonical candle representation for persistence.
    Timestamp is ms epoch UTC.
    """
    ts_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class OHLCVLocalState:
    """Local state summary for one OHLCV CSV partition.

    The CSV remains the value truth. Metadata is used as a fast
    range/identity guide when it is present and consistent.
    """

    file_path: Path
    metadata_path: Path
    csv_exists: bool
    metadata_exists: bool
    metadata_valid: bool
    metadata_repaired: bool
    source: str
    first_ts_ms: int | None
    last_ts_ms: int | None
    row_count: int
    issues: tuple[str, ...] = ()


class CsvOHLCVStore:
    """
    CSV store for a single partition:
      .../<exchange>/<market_type>/<symbol>/<timeframe_storage_segment>/ohlcv/candles.csv

    Guarantees:
    - read returns sorted by ts_ms ascending
    - write_atomic replaces the file atomically
    - merge_idempotent dedupes by ts_ms and prefers incoming on collision
    """

    FILENAME = "candles.csv"
    HEADER = ["ts_ms", "open", "high", "low", "close", "volume"]

    def file_path(self, ohlcv_dir: Path) -> Path:
        return ohlcv_dir / self.FILENAME

    def inspect(
        self,
        file_path: Path,
        *,
        market: MarketId | None = None,
        repair_metadata: bool = True,
    ) -> OHLCVLocalState:
        """Inspect local OHLCV CSV/metadata state for download planning.

        Metadata is trusted only when it matches the requested market, the
        expected OHLCV shape, and the current CSV fingerprint. If metadata is
        missing or stale, the CSV is scanned and the sidecar can be restored
        without changing CSV values.
        """
        csv_path = Path(file_path)
        metadata_path = metadata_path_for_csv(csv_path)
        csv_exists = csv_path.exists()
        metadata_exists = metadata_path.exists()

        if not csv_exists:
            return OHLCVLocalState(
                file_path=csv_path,
                metadata_path=metadata_path,
                csv_exists=False,
                metadata_exists=metadata_exists,
                metadata_valid=False,
                metadata_repaired=False,
                source="missing",
                first_ts_ms=None,
                last_ts_ms=None,
                row_count=0,
                issues=(),
            )

        issues: list[str] = []
        manifest = self._load_existing_manifest(metadata_path)
        if metadata_exists and manifest is None:
            issues.append("metadata unreadable or invalid")

        if manifest is not None:
            validation_issue = self._manifest_issue_for_csv(
                manifest=manifest,
                file_path=csv_path,
                market=market,
            )
            if validation_issue is None:
                return OHLCVLocalState(
                    file_path=csv_path,
                    metadata_path=metadata_path,
                    csv_exists=True,
                    metadata_exists=metadata_exists,
                    metadata_valid=True,
                    metadata_repaired=False,
                    source="metadata",
                    first_ts_ms=manifest.time_range.first_ts_ms,
                    last_ts_ms=manifest.time_range.last_ts_ms,
                    row_count=int(manifest.shape.row_count or 0),
                    issues=(),
                )
            issues.append(validation_issue)
        elif not metadata_exists:
            issues.append("metadata missing")

        candles = self.read(csv_path)
        metadata_repaired = False
        if repair_metadata:
            self._write_metadata_sidecar(file_path=csv_path, candles=list(candles), market=market)
            metadata_repaired = True

        return OHLCVLocalState(
            file_path=csv_path,
            metadata_path=metadata_path,
            csv_exists=True,
            metadata_exists=metadata_exists,
            metadata_valid=False,
            metadata_repaired=metadata_repaired,
            source="csv",
            first_ts_ms=candles[0].ts_ms if candles else None,
            last_ts_ms=candles[-1].ts_ms if candles else None,
            row_count=len(candles),
            issues=tuple(issues),
        )

    def _manifest_issue_for_csv(
        self,
        *,
        manifest: HistoricalCsvArtifactManifest,
        file_path: Path,
        market: MarketId | None,
    ) -> str | None:
        if manifest.identity.artifact_family != "ohlcv":
            return "metadata artifact family is not ohlcv"

        if market is not None and manifest.market != market:
            return "metadata market identity does not match requested partition"

        if tuple(manifest.shape.columns) != tuple(self.HEADER):
            return "metadata columns do not match OHLCV CSV header"

        fingerprint = self._fingerprint_for_file(file_path)
        if (
            manifest.fingerprint.size_bytes is not None
            and fingerprint.size_bytes is not None
            and int(manifest.fingerprint.size_bytes) != int(fingerprint.size_bytes)
        ):
            return "metadata file size fingerprint is stale"

        if (
            manifest.fingerprint.modified_at_ms is not None
            and fingerprint.modified_at_ms is not None
            and int(manifest.fingerprint.modified_at_ms) != int(fingerprint.modified_at_ms)
        ):
            return "metadata modified-time fingerprint is stale"

        return None

    def read(self, file_path: Path) -> List[Candle]:
        if not file_path.exists():
            return []

        out: List[Candle] = []
        with file_path.open("r", newline="") as f:
            r = csv.DictReader(f)
            # tolerate missing header/columns with clear error
            for row in r:
                out.append(
                    Candle(
                        ts_ms=int(row["ts_ms"]),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row["volume"]),
                    )
                )

        out.sort(key=lambda c: c.ts_ms)
        return out

    def read_ts_ms_by_row(self, file_path: Path) -> tuple[int | None, ...]:
        """Return CSV-order ``ts_ms`` values without parsing OHLCV values."""
        csv_path = Path(file_path)
        if not csv_path.exists():
            return ()

        values: list[int | None] = []
        with csv_path.open("r", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None or "ts_ms" not in reader.fieldnames:
                return ()
            for row in reader:
                try:
                    values.append(int(row["ts_ms"]))
                except Exception:
                    values.append(None)
        return tuple(values)

    def write_atomic(
        self,
        file_path: Path,
        candles: List[Candle],
        *,
        market: MarketId | None = None,
        write_metadata: bool = True,
    ) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write to temp file in same directory then atomic replace
        fd, tmp_path = tempfile.mkstemp(
            prefix=file_path.name + ".",
            suffix=".tmp",
            dir=str(file_path.parent),
        )
        try:
            with os.fdopen(fd, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(self.HEADER)
                for c in candles:
                    w.writerow([c.ts_ms, c.open, c.high, c.low, c.close, c.volume])

            self._replace_file_atomic(tmp_path, file_path)
            if write_metadata:
                self._write_metadata_sidecar(file_path=file_path, candles=list(candles), market=market)
        finally:
            # If replace failed, try cleanup temp
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass

    def rebuild_metadata_sidecar(self, file_path: Path, *, market: MarketId | None = None) -> OHLCVLocalState:
        """
        Rewrite the OHLCV metadata sidecar from an existing CSV file.

        The CSV values are read but not modified. The generated sidecar uses the
        same OHLCV manifest contract as ``write_atomic`` and is intended for
        explicit maintenance workflows that need to replace missing, corrupt, or
        stale metadata without redownloading candles.
        """
        csv_path = Path(file_path)
        if not csv_path.is_file():
            raise FileNotFoundError(f"OHLCV CSV not found: {csv_path}")
        candles = self.read(csv_path)
        if not candles:
            raise ValueError(f"Cannot rebuild OHLCV metadata for empty CSV: {csv_path}")
        self._write_metadata_sidecar(file_path=csv_path, candles=list(candles), market=market)
        return self.inspect(csv_path, market=market, repair_metadata=False)

    def record_validation_result(
        self,
        file_path: Path,
        *,
        market: MarketId | None,
        status: str,
        row_count: int,
        issues: Iterable[tuple[str, str]],
        validator: str,
        message_override: str | None = None,
    ) -> bool:
        """Persist an explicit validation result in the adjacent metadata sidecar."""
        csv_path = Path(file_path)
        if not csv_path.is_file():
            raise FileNotFoundError(f"OHLCV CSV not found: {csv_path}")

        metadata_path = metadata_path_for_csv(csv_path)
        manifest = self._load_existing_manifest(metadata_path)
        if manifest is not None and self._manifest_issue_for_csv(
            manifest=manifest,
            file_path=csv_path,
            market=market,
        ) is not None:
            manifest = None
        if manifest is None:
            self.rebuild_metadata_sidecar(csv_path, market=market)
            manifest = self._load_existing_manifest(metadata_path)
        if manifest is None:
            raise RuntimeError(f"Cannot update OHLCV validation metadata: {metadata_path}")

        issue_pairs = tuple((str(severity), str(message)) for severity, message in issues)
        warning_count = sum(1 for severity, _message in issue_pairs if severity == "warning")
        error_count = sum(1 for severity, _message in issue_pairs if severity == "error")
        canonical_status = self._canonical_validation_status(status)
        fingerprint = self._fingerprint_for_file(csv_path)
        validation = ArtifactValidationMetadata(
            status=canonical_status,  # type: ignore[arg-type]
            validated_at_ms=int(time.time() * 1000),
            validator=str(validator),
            row_count=int(row_count),
            issue_count=len(issue_pairs),
            warning_count=warning_count,
            error_count=error_count,
            csv_fingerprint=fingerprint,
            message=str(message_override) if message_override else self._validation_message(issue_pairs),
        )
        quality_status = "not_validated" if canonical_status == "unknown" else canonical_status
        updated_manifest = replace(
            manifest,
            fingerprint=fingerprint,
            quality=replace(
                manifest.quality,
                validation_status=quality_status,  # type: ignore[arg-type]
                validation_notes=tuple(f"{severity}: {message}" for severity, message in issue_pairs),
            ),
            validation=validation,
        )
        self._atomic_write_json(updated_manifest.to_dict(), metadata_path)
        return True

    def source_correction_records(
        self,
        file_path: Path,
        *,
        market: MarketId | None = None,
    ) -> tuple[dict[str, object], ...]:
        """
        Return current source-correction provenance records from metadata.

        Records are returned only when the sidecar identity and fingerprint still
        match the CSV. Stale or mismatched metadata is treated as having no
        current source-correction provenance.
        """
        csv_path = Path(file_path)
        manifest = self._load_existing_manifest(metadata_path_for_csv(csv_path))
        if manifest is None:
            return ()
        if self._manifest_issue_for_csv(manifest=manifest, file_path=csv_path, market=market) is not None:
            return ()
        return self._source_correction_records_from_manifest(manifest)

    def has_current_source_corrections(
        self,
        file_path: Path,
        *,
        market: MarketId | None = None,
    ) -> bool:
        """Return whether metadata records current source corrections for the CSV."""
        return bool(self.source_correction_records(file_path, market=market))

    def record_source_corrections(
        self,
        file_path: Path,
        *,
        market: MarketId | None,
        records: Iterable[dict[str, object]],
        existing_records: Iterable[dict[str, object]] = (),
    ) -> bool:
        """
        Append source-correction provenance to the adjacent metadata sidecar.

        The helper preserves existing manifest fields, rebuilds stale sidecars
        before writing, and stores correction history as artifact metadata under
        the OHLCV namespace. CSV values are not read or modified by this method.
        """
        csv_path = Path(file_path)
        if not csv_path.is_file():
            raise FileNotFoundError(f"OHLCV CSV not found: {csv_path}")

        metadata_path = metadata_path_for_csv(csv_path)
        manifest = self._load_existing_manifest(metadata_path)
        if manifest is not None and self._manifest_issue_for_csv(
            manifest=manifest,
            file_path=csv_path,
            market=market,
        ) is not None:
            manifest = None
        if manifest is None:
            self.rebuild_metadata_sidecar(csv_path, market=market)
            manifest = self._load_existing_manifest(metadata_path)
        if manifest is None:
            raise RuntimeError(f"Cannot update OHLCV source correction metadata: {metadata_path}")

        merged_records = self._dedupe_source_correction_records(
            tuple(dict(item) for item in existing_records)
            + tuple(dict(item) for item in records)
        )
        metadata = tuple(
            entry
            for entry in manifest.metadata
            if not (
                entry.namespace == SOURCE_CORRECTIONS_METADATA_NAMESPACE
                and entry.key == SOURCE_CORRECTIONS_METADATA_KEY
            )
        )
        if merged_records:
            metadata += (
                ArtifactMetadataEntry(
                    namespace=SOURCE_CORRECTIONS_METADATA_NAMESPACE,
                    key=SOURCE_CORRECTIONS_METADATA_KEY,
                    value=list(merged_records),
                    label="OHLCV source corrections",
                    description="Documented local corrections applied to source-invalid OHLCV candles.",
                    tags=("source_correction", "ohlcv"),
                    searchable=False,
                    identity_affecting=False,
                ),
            )

        self._atomic_write_json(replace(manifest, metadata=metadata).to_dict(), metadata_path)
        return True

    def _write_metadata_sidecar(
        self,
        *,
        file_path: Path,
        candles: List[Candle],
        market: MarketId | None,
    ) -> None:
        resolved_market = market or self._infer_market_from_path(file_path)
        if resolved_market is None:
            return

        partition_dir = Path(file_path).parent.parent
        metadata_path = metadata_path_for_csv(file_path)
        existing = self._load_existing_manifest(metadata_path)

        now_ms = int(time.time() * 1000)
        unique_id = existing.identity.unique_id if existing is not None else new_unique_id()
        created_at_ms = (
            existing.lineage.created_at_ms
            if existing is not None and existing.lineage.created_at_ms is not None
            else now_ms
        )
        ts_values = [int(c.ts_ms) for c in candles]
        duplicate_ts = len(ts_values) != len(set(ts_values))
        monotonic_ts = all(left < right for left, right in zip(ts_values, ts_values[1:]))
        timeline_status = "verified" if (not duplicate_ts and monotonic_ts) else "error"
        validation_status = "ok" if timeline_status == "verified" else "error"
        validation_notes: tuple[str, ...] = ()
        if duplicate_ts:
            validation_notes += ("duplicate ts_ms values detected",)
        if not monotonic_ts:
            validation_notes += ("ts_ms values are not strictly increasing",)

        first_ts_ms = min(ts_values) if ts_values else None
        last_ts_ms = max(ts_values) if ts_values else None
        artifact_id = build_artifact_id(artifact_family="ohlcv")
        artifact_uid = build_artifact_uid(
            market=resolved_market,
            artifact_family="ohlcv",
            artifact_id=artifact_id,
        )
        files = metadata_files_from_csv(csv_path=Path(file_path), partition_dir=partition_dir)
        fingerprint = self._fingerprint_for_file(file_path)

        manifest = HistoricalCsvArtifactManifest(
            schema_version=ARTIFACT_METADATA_SCHEMA_VERSION,
            artifact_type=HISTORICAL_CSV_ARTIFACT_TYPE,
            identity=ArtifactIdentity(
                unique_id=unique_id,
                artifact_family="ohlcv",
                storage_family="ohlcv",
                artifact_id=artifact_id,
                artifact_uid=artifact_uid,
            ),
            market=resolved_market,
            files=files,
            time_range=ArtifactTimeRange.from_ts_ms(
                first_ts_ms=first_ts_ms,
                last_ts_ms=last_ts_ms,
            ),
            shape=ArtifactShape(
                row_count=len(candles),
                column_count=len(self.HEADER),
                columns=tuple(self.HEADER),
            ),
            columns=self._ohlcv_column_metadata(),
            tool=None,
            lineage=ArtifactLineage.from_timestamps(
                created_at_ms=created_at_ms,
                updated_at_ms=now_ms,
            ),
            fingerprint=fingerprint,
            quality=ArtifactQuality(
                timeline_status=timeline_status,  # type: ignore[arg-type]
                monotonic_ts_ms=monotonic_ts,
                duplicate_ts_ms=duplicate_ts,
                validation_status=validation_status,  # type: ignore[arg-type]
                validation_notes=validation_notes,
            ),
        )
        self._atomic_write_json(manifest.to_dict(), metadata_path)

    def _infer_market_from_path(self, file_path: Path) -> MarketId | None:
        try:
            path = Path(file_path)
            if path.name != self.FILENAME or path.parent.name != "ohlcv":
                return None
            timeframe_dir = path.parents[1]
            symbol_dir = path.parents[2]
            market_type_dir = path.parents[3]
            exchange_dir = path.parents[4]
            timeframe = storage_segment_to_timeframe(timeframe_dir.name)
            return canonicalize(exchange_dir.name, market_type_dir.name, symbol_dir.name, timeframe)
        except Exception:
            return None

    def _load_existing_manifest(self, metadata_path: Path) -> HistoricalCsvArtifactManifest | None:
        if not metadata_path.exists():
            return None
        try:
            with metadata_path.open("r", encoding="utf-8") as handle:
                return HistoricalCsvArtifactManifest.from_dict(json.load(handle))
        except Exception:
            return None

    def file_fingerprint(self, file_path: Path) -> ArtifactFingerprint:
        """Return the fingerprint fields used by OHLCV metadata sidecars."""
        return self._fingerprint_for_file(file_path)

    def _canonical_validation_status(self, status: str) -> str:
        value = str(status or "").strip().lower()
        if value in {"ok", "modified", "warning", "error"}:
            return value
        return "unknown"

    def _source_correction_records_from_manifest(
        self,
        manifest: HistoricalCsvArtifactManifest,
    ) -> tuple[dict[str, object], ...]:
        for entry in manifest.metadata:
            if (
                entry.namespace == SOURCE_CORRECTIONS_METADATA_NAMESPACE
                and entry.key == SOURCE_CORRECTIONS_METADATA_KEY
            ):
                records = entry.value
                if not isinstance(records, list):
                    return ()
                return tuple(dict(item) for item in records if isinstance(item, dict))
        return ()

    def _dedupe_source_correction_records(
        self,
        records: tuple[dict[str, object], ...],
    ) -> tuple[dict[str, object], ...]:
        out: list[dict[str, object]] = []
        seen: set[str] = set()
        for record in records:
            key = json.dumps(
                {
                    "ts_ms": record.get("ts_ms"),
                    "action": record.get("action"),
                    "source_csv_fingerprint": record.get("source_csv_fingerprint"),
                    "corrected_csv_fingerprint": record.get("corrected_csv_fingerprint"),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(dict(record))
        return tuple(out)

    def _validation_message(self, issues: tuple[tuple[str, str], ...]) -> str:
        if not issues:
            return "No validation issues detected."
        severity, message = issues[0]
        if len(issues) == 1:
            return f"{severity}: {message}"
        return f"{len(issues)} validation issues detected; first: {severity}: {message}"

    def _fingerprint_for_file(self, file_path: Path) -> ArtifactFingerprint:
        try:
            stat = Path(file_path).stat()
        except OSError:
            return ArtifactFingerprint()
        return ArtifactFingerprint.from_file_stat(
            size_bytes=int(stat.st_size),
            modified_at_ms=int(stat.st_mtime * 1000),
        )

    def _atomic_write_json(self, data: dict[str, object], target_path: Path) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            suffix=".tmp",
            prefix="ohlcv_metadata_",
            dir=str(target_path.parent),
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
            try:
                json.dump(data, tmp, indent=2, sort_keys=True)
                tmp.write("\n")
            except Exception:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass
                raise
        self._replace_file_atomic(tmp_path, target_path)

    def _replace_file_atomic(self, source_path: str | Path, target_path: Path) -> None:
        """Atomically replace ``target_path`` with retries for transient Windows locks.

        Windows may briefly deny replacing a file if another process such as an
        antivirus scanner, indexer, or previewer opens the current destination
        between page writes. The write remains atomic: the destination is only
        replaced by a fully written temp file, and a persistent lock still
        raises the original OS error.
        """
        source = str(source_path)
        target = str(target_path)
        delays_s = (0.05, 0.10, 0.20, 0.40, 0.80, 1.20)
        last_error: OSError | None = None

        for attempt in range(len(delays_s) + 1):
            try:
                os.replace(source, target)
                return
            except PermissionError as e:
                last_error = e
            except OSError as e:
                # Retry only common transient Windows destination-lock cases.
                winerror = getattr(e, "winerror", None)
                if winerror not in {5, 32, 33} and getattr(e, "errno", None) != 13:
                    raise
                last_error = e

            if attempt < len(delays_s):
                time.sleep(delays_s[attempt])

        if last_error is not None:
            raise last_error
        raise RuntimeError(f"failed to replace {target!r} with {source!r}")

    def _ohlcv_column_metadata(self) -> tuple[ArtifactColumnMetadata, ...]:
        return (
            ArtifactColumnMetadata(
                name="ts_ms",
                role="primary_key",
                dtype="int64",
                selectable=False,
                analysis_usable=True,
                renderable=False,
                label="Timestamp",
                semantic_role="primary_key",
                value_type="int",
            ),
            ArtifactColumnMetadata(
                name="open",
                role="base",
                dtype="float64",
                selectable=True,
                analysis_usable=True,
                renderable=True,
                label="Open",
                semantic_role="open",
            ),
            ArtifactColumnMetadata(
                name="high",
                role="base",
                dtype="float64",
                selectable=True,
                analysis_usable=True,
                renderable=True,
                label="High",
                semantic_role="high",
            ),
            ArtifactColumnMetadata(
                name="low",
                role="base",
                dtype="float64",
                selectable=True,
                analysis_usable=True,
                renderable=True,
                label="Low",
                semantic_role="low",
            ),
            ArtifactColumnMetadata(
                name="close",
                role="base",
                dtype="float64",
                selectable=True,
                analysis_usable=True,
                renderable=True,
                label="Close",
                semantic_role="close",
            ),
            ArtifactColumnMetadata(
                name="volume",
                role="base",
                dtype="float64",
                selectable=True,
                analysis_usable=True,
                renderable=False,
                label="Volume",
                semantic_role="volume",
            ),
        )


def merge_idempotent(existing: Iterable[Candle], incoming: Iterable[Candle]) -> List[Candle]:
    """
    Merge by ts_ms, removing duplicates.
    On collision (same timestamp), prefer incoming.
    """
    by_ts: Dict[int, Candle] = {c.ts_ms: c for c in existing}
    for c in incoming:
        by_ts[c.ts_ms] = c

    out = list(by_ts.values())
    out.sort(key=lambda c: c.ts_ms)
    return out
