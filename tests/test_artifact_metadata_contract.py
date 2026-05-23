from __future__ import annotations

from leonardo.data.historical.artifact_metadata_contracts import (
    ARTIFACT_METADATA_SCHEMA_VERSION,
    HISTORICAL_CSV_ARTIFACT_TYPE,
    ArtifactColumnMetadata,
    ArtifactFiles,
    ArtifactFingerprint,
    ArtifactIdentity,
    ArtifactLineage,
    ArtifactQuality,
    ArtifactShape,
    ArtifactTimeRange,
    ArtifactToolMetadata,
    ArtifactValidationMetadata,
    HistoricalArtifactSummary,
    HistoricalCsvArtifactManifest,
)
from leonardo.data.historical.artifact_metadata_naming import (
    build_artifact_id,
    build_artifact_uid,
    metadata_path_for_csv,
    new_unique_id,
)
from leonardo.data.naming import canonicalize
from leonardo.financial_tools.tool_contracts.registry import get_contract


def test_historical_csv_artifact_manifest_roundtrip_with_tool_contract():
    market = canonicalize("bybit", "linear", "BTC/USDT", "30m")
    artifact_id = build_artifact_id(
        artifact_family="oscillator",
        tool_key="rsi",
        instance_key="rsi__default__period-14",
    )
    artifact_uid = build_artifact_uid(market=market, artifact_family="oscillator", artifact_id=artifact_id)
    csv_relpath = "oscillators/rsi__default__period-14.csv"
    meta_relpath = str(metadata_path_for_csv(csv_relpath))
    contract = get_contract("rsi")

    manifest = HistoricalCsvArtifactManifest(
        schema_version=ARTIFACT_METADATA_SCHEMA_VERSION,
        artifact_type=HISTORICAL_CSV_ARTIFACT_TYPE,
        identity=ArtifactIdentity(
            unique_id=new_unique_id(),
            artifact_family="oscillator",
            storage_family="oscillators",
            artifact_id=artifact_id,
            artifact_uid=artifact_uid,
        ),
        market=market,
        files=ArtifactFiles(
            csv_filename="rsi__default__period-14.csv",
            csv_relpath=csv_relpath,
            metadata_filename="rsi__default__period-14.meta.json",
            metadata_relpath=meta_relpath,
        ),
        time_range=ArtifactTimeRange.from_ts_ms(
            first_ts_ms=1_609_459_200_000,
            last_ts_ms=1_609_545_600_000,
        ),
        shape=ArtifactShape(
            row_count=25,
            column_count=2,
            columns=("ts_ms", "rsi_14"),
        ),
        columns=(
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
                name="rsi_14",
                role="feature",
                dtype="float64",
                selectable=True,
                analysis_usable=True,
                renderable=True,
                label="RSI",
            ),
        ),
        tool=ArtifactToolMetadata.from_tool_contract(
            contract=contract,
            instance_key="rsi__default__period-14",
            params={"period": 14},
            params_status="explicit",
            bindings={"source": "close"},
            bindings_status="explicit",
        ),
        lineage=ArtifactLineage.from_timestamps(
            created_at_ms=1_609_459_200_000,
            updated_at_ms=1_609_459_200_000,
        ),
        fingerprint=ArtifactFingerprint.from_file_stat(
            size_bytes=1234,
            modified_at_ms=1_609_459_200_000,
        ),
        quality=ArtifactQuality(
            timeline_status="verified",
            monotonic_ts_ms=True,
            duplicate_ts_ms=False,
            validation_status="ok",
        ),
        validation=ArtifactValidationMetadata(
            status="ok",
            validated_at_ms=1_609_459_200_000,
            validator="HistoricalDatasetValidator",
            row_count=25,
            issue_count=0,
            csv_fingerprint=ArtifactFingerprint.from_file_stat(
                size_bytes=1234,
                modified_at_ms=1_609_459_200_000,
            ),
            message="No validation issues detected.",
        ),
    )

    payload = manifest.to_dict()
    loaded = HistoricalCsvArtifactManifest.from_dict(payload)

    assert loaded.identity.unique_id == manifest.identity.unique_id
    assert loaded.identity.artifact_uid == artifact_uid
    assert loaded.market.symbol == "BTCUSDT"
    assert loaded.files.metadata_filename == "rsi__default__period-14.meta.json"
    assert loaded.time_range.first_ts_rome == "2021-01-01 01:00:00 Europe/Rome"
    assert loaded.tool is not None
    assert loaded.tool.tool_key == "rsi"
    assert loaded.tool.params == {"period": 14}
    assert loaded.tool.param_contracts[0].name == "period"
    assert loaded.tool.output is not None
    assert loaded.tool.output.naming_resolver == "oscillator:rsi"
    assert loaded.tool.oscillator_visual is not None
    assert loaded.quality.timeline_status == "verified"
    assert loaded.validation.status == "ok"
    assert loaded.validation.validator == "HistoricalDatasetValidator"
    assert loaded.validation.row_count == 25
    assert loaded.validation.validated_at == "2021-01-01 00:00:00 UTC"

    summary = HistoricalArtifactSummary.from_manifest(loaded)
    assert summary.unique_id == manifest.identity.unique_id
    assert summary.tool_title == "RSI"
    assert summary.first_ts_rome == "2021-01-01 01:00:00 Europe/Rome"


def test_ohlcv_manifest_can_have_no_tool_section():
    market = canonicalize("bybit", "linear", "BTCUSDT", "1h")
    artifact_id = build_artifact_id(artifact_family="ohlcv")
    artifact_uid = build_artifact_uid(market=market, artifact_family="ohlcv", artifact_id=artifact_id)

    manifest = HistoricalCsvArtifactManifest(
        schema_version=ARTIFACT_METADATA_SCHEMA_VERSION,
        artifact_type=HISTORICAL_CSV_ARTIFACT_TYPE,
        identity=ArtifactIdentity(
            unique_id=new_unique_id(),
            artifact_family="ohlcv",
            storage_family="ohlcv",
            artifact_id=artifact_id,
            artifact_uid=artifact_uid,
        ),
        market=market,
        files=ArtifactFiles(
            csv_filename="candles.csv",
            csv_relpath="ohlcv/candles.csv",
            metadata_filename="candles.meta.json",
            metadata_relpath="ohlcv/candles.meta.json",
        ),
        time_range=ArtifactTimeRange.from_ts_ms(first_ts_ms=None, last_ts_ms=None),
        shape=ArtifactShape(row_count=None, column_count=6, columns=("ts_ms", "open", "high", "low", "close", "volume")),
        columns=(
            ArtifactColumnMetadata(name="ts_ms", role="primary_key", selectable=False, analysis_usable=True, renderable=False),
            ArtifactColumnMetadata(name="open", role="base", analysis_usable=True, renderable=True),
            ArtifactColumnMetadata(name="high", role="base", analysis_usable=True, renderable=True),
            ArtifactColumnMetadata(name="low", role="base", analysis_usable=True, renderable=True),
            ArtifactColumnMetadata(name="close", role="base", analysis_usable=True, renderable=True),
            ArtifactColumnMetadata(name="volume", role="base", analysis_usable=True, renderable=False),
        ),
        tool=None,
        lineage=ArtifactLineage.from_timestamps(created_at_ms=None, updated_at_ms=None),
        fingerprint=ArtifactFingerprint(),
        quality=ArtifactQuality(timeline_status="unverified"),
    )

    loaded = HistoricalCsvArtifactManifest.from_dict(manifest.to_dict())
    assert loaded.tool is None
    assert loaded.identity.artifact_id == "ohlcv__candles"
    assert loaded.validation.status == "unknown"
