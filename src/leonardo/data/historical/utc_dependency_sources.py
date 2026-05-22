from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from leonardo.data.historical.derived_store_csv import DerivedCsvStore
from leonardo.data.naming import MarketId


def utc_peak_trough_columns_for_purpose(
    params: Mapping[str, Any],
    *,
    purpose: str,
) -> tuple[str, str]:
    """
    Resolve one UTC Peaks & Troughs dependency pair from historical params.

    Trend and range are separate dependency intents. The returned columns match
    the historical controller/data-service behavior used before this helper was
    introduced.
    """
    if purpose == "trend":
        window = int(params.get("trend_fractal_window", params.get("fractal_window", 5)))
        peak_column = str(
            params.get("trend_peak_column")
            or params.get("peak_column")
            or f"peak_fractal_{window}"
        ).strip()
        trough_column = str(
            params.get("trend_trough_column")
            or params.get("trough_column")
            or f"trough_fractal_{window}"
        ).strip()
    elif purpose == "range":
        window = int(params.get("range_fractal_window", 3))
        peak_column = str(params.get("range_peak_column") or f"peak_fractal_{window}").strip()
        trough_column = str(params.get("range_trough_column") or f"trough_fractal_{window}").strip()
    else:
        raise ValueError("UTC dependency purpose must be 'trend' or 'range'.")

    if not peak_column or not trough_column:
        raise ValueError(f"UTC {purpose} Peaks & Troughs dependency columns must be non-empty.")
    return peak_column, trough_column


def utc_peak_trough_columns(params: Mapping[str, Any]) -> tuple[str, ...]:
    """Return all unique Peaks & Troughs columns required by UTC."""
    columns: list[str] = []
    for purpose in ("trend", "range"):
        for column_name in utc_peak_trough_columns_for_purpose(params, purpose=purpose):
            if column_name not in columns:
                columns.append(column_name)
    return tuple(columns)


def utc_dependency_role_name(*, params: Mapping[str, Any], column_name: str) -> str:
    trend_columns = set(utc_peak_trough_columns_for_purpose(params, purpose="trend"))
    range_columns = set(utc_peak_trough_columns_for_purpose(params, purpose="range"))
    if column_name in trend_columns and column_name in range_columns:
        purpose = "trend_range"
    elif column_name in trend_columns:
        purpose = "trend"
    elif column_name in range_columns:
        purpose = "range"
    else:
        purpose = "dependency"
    return f"universal_trend_classifier.{purpose}.{column_name}"


def prepare_utc_peak_trough_dependencies(
    *,
    df: pd.DataFrame,
    historical_root: Path,
    market: MarketId,
    params: Mapping[str, Any],
    expected_instance_key: str = "",
) -> pd.DataFrame:
    """
    Inject saved Peaks & Troughs columns required by UTC into a full dataframe.

    The helper loads the saved ``peaks_troughs`` artifact for the same market
    partition and aligns dependency columns by ``ts_ms`` or ``time``. Positional
    alignment is intentionally unsupported.
    """
    required_columns = utc_peak_trough_columns(params)
    columns_to_inject = [column_name for column_name in required_columns if column_name not in df.columns]
    if not columns_to_inject:
        return df

    src_df = load_saved_peaks_troughs_dataframe(
        historical_root=historical_root,
        market=market,
        expected_instance_key=expected_instance_key,
    )
    missing = [name for name in columns_to_inject if name not in src_df.columns]
    if missing:
        raise ValueError(
            "Saved Peaks & Troughs artifact does not contain the columns required by UTC: "
            f"{missing}"
        )

    out = df
    for column_name in columns_to_inject:
        if column_name in out.columns:
            continue
        out = _merge_source_dataframe_column(
            df=out,
            src_df=src_df,
            column_name=column_name,
            role_name=utc_dependency_role_name(params=params, column_name=column_name),
            source_label="saved Peaks & Troughs artifact",
        )
    return out


def load_saved_peaks_troughs_dataframe(
    *,
    historical_root: Path,
    market: MarketId,
    expected_instance_key: str = "",
) -> pd.DataFrame:
    """Load the saved Peaks & Troughs artifact selected for UTC dependencies."""
    store = DerivedCsvStore(historical_root=Path(historical_root))
    refs = store.list_instances(
        market=market,
        kind="indicators",
        tool_key="peaks_troughs",
    )
    if not refs:
        raise FileNotFoundError(
            "Universal Trend Classifier requires a saved Peaks & Troughs indicator "
            "for this dataset/timeframe before it can run."
        )

    selected_ref = _select_peaks_troughs_ref(refs=refs, expected_instance_key=expected_instance_key)
    raw_path = str(getattr(selected_ref, "path", "")).strip()
    if not raw_path:
        raise FileNotFoundError("Saved Peaks & Troughs artifact reference has no path.")

    path = Path(raw_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Saved Peaks & Troughs artifact not found: {path}")

    src_df = pd.read_csv(path)
    if src_df.empty:
        raise ValueError(f"Saved Peaks & Troughs artifact is empty: {path}")
    return src_df


def _select_peaks_troughs_ref(*, refs: list[Any], expected_instance_key: str) -> Any:
    selected_ref = None
    normalized_expected = str(expected_instance_key or "").strip()
    if normalized_expected:
        for ref in refs:
            if str(getattr(ref, "instance_key", "")).strip() == normalized_expected:
                selected_ref = ref
                break

    if selected_ref is not None:
        return selected_ref

    if len(refs) == 1:
        return refs[0]

    available = ", ".join(str(getattr(ref, "instance_key", "")) for ref in refs)
    raise ValueError(
        "Multiple saved Peaks & Troughs artifacts were found for this dataset/timeframe, "
        "but no canonical default instance could be selected. "
        f"Available instances: {available}"
    )


def _merge_source_dataframe_column(
    *,
    df: pd.DataFrame,
    src_df: pd.DataFrame,
    column_name: str,
    role_name: str,
    source_label: str,
) -> pd.DataFrame:
    out = df.copy()

    join_key = None
    if "ts_ms" in out.columns and "ts_ms" in src_df.columns:
        join_key = "ts_ms"
    elif "time" in out.columns and "time" in src_df.columns:
        join_key = "time"

    if join_key is None:
        raise ValueError(
            f"Source '{column_name}' for role '{role_name}' cannot be aligned safely. "
            "A shared join key ('ts_ms' or 'time') is required."
        )

    if bool(src_df[join_key].duplicated(keep=False).any()):
        raise ValueError(
            f"Source data for role '{role_name}' contains duplicate join-key values "
            f"for '{join_key}', so deterministic alignment is impossible."
        )

    merged = out.merge(
        src_df[[join_key, column_name]],
        on=join_key,
        how="left",
        sort=False,
        validate="many_to_one",
    )

    if column_name not in merged.columns:
        raise ValueError(
            f"Failed to merge source '{column_name}' for role '{role_name}' from '{source_label}'."
        )

    out[column_name] = merged[column_name].values
    return out
