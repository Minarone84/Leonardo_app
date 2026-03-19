from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, List, Literal, Optional

import os
import re

import pandas as pd

from leonardo.data.historical.paths import DatasetType, HistoricalPaths
from leonardo.data.naming import MarketId


DerivedKind = Literal["indicators", "oscillators", "constructs"]


@dataclass(frozen=True)
class DerivedArtifactRef:
    """
    Metadata reference for one persisted derived artifact.
    """
    kind: DerivedKind
    tool_key: str
    instance_key: str
    filename: str
    path: Path


class DerivedCsvStore:
    """
    Generic CSV persistence for derived historical artifacts such as:
    - indicators
    - oscillators
    - constructs

    Design goals:
    - canonical path resolution through paths.py
    - atomic writes
    - GUI-independent
    - simple listing/loading for Financial Tool Manager
    """

    _SAFE_SEGMENT_RE = re.compile(r"[^a-zA-Z0-9_.-]+")

    def __init__(self, *, historical_root: Path) -> None:
        self._historical_root = Path(historical_root)
        self._paths = HistoricalPaths(root=self._historical_root)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save_dataframe(
        self,
        *,
        market: MarketId,
        kind: DerivedKind,
        tool_key: str,
        instance_key: str,
        df: pd.DataFrame,
    ) -> Path:
        """
        Persist a derived dataframe as CSV under the canonical historical partition.

        Expected dataframe shape:
        - may contain 'time' and 'timeframe'
        - contains one or more derived output columns
        - index is ignored for persistence; CSV is stored index-free

        Returns:
            Absolute file path of the saved artifact.
        """
        self._validate_kind(kind)
        safe_tool_key = self._sanitize_segment(tool_key)
        safe_instance_key = self._sanitize_segment(instance_key)

        if df is None or df.empty:
            raise ValueError("Cannot save an empty derived dataframe.")

        dataset_dir = self._dataset_dir(market=market, kind=kind)
        filename = self._build_filename(tool_key=safe_tool_key, instance_key=safe_instance_key)
        target_path = dataset_dir / filename

        write_df = df.copy()

        # Persist index-free to keep files display/load friendly and deterministic.
        self._atomic_write_csv(write_df, target_path)
        return target_path

    def load_dataframe(
        self,
        *,
        market: MarketId,
        kind: DerivedKind,
        tool_key: str,
        instance_key: str,
    ) -> pd.DataFrame:
        """
        Load one persisted derived dataframe by canonical identity.
        """
        self._validate_kind(kind)
        path = self.resolve_path(
            market=market,
            kind=kind,
            tool_key=tool_key,
            instance_key=instance_key,
        )

        if not path.exists():
            raise FileNotFoundError(f"Derived artifact not found: {path}")

        return pd.read_csv(path)

    def resolve_path(
        self,
        *,
        market: MarketId,
        kind: DerivedKind,
        tool_key: str,
        instance_key: str,
    ) -> Path:
        """
        Resolve the canonical file path for a derived artifact.
        """
        self._validate_kind(kind)
        safe_tool_key = self._sanitize_segment(tool_key)
        safe_instance_key = self._sanitize_segment(instance_key)

        dataset_dir = self._dataset_dir(market=market, kind=kind)
        filename = self._build_filename(tool_key=safe_tool_key, instance_key=safe_instance_key)
        return dataset_dir / filename

    def exists(
        self,
        *,
        market: MarketId,
        kind: DerivedKind,
        tool_key: str,
        instance_key: str,
    ) -> bool:
        """
        Check whether a canonical derived artifact already exists.
        """
        return self.resolve_path(
            market=market,
            kind=kind,
            tool_key=tool_key,
            instance_key=instance_key,
        ).exists()

    def list_instances(
        self,
        *,
        market: MarketId,
        kind: DerivedKind,
        tool_key: Optional[str] = None,
    ) -> List[DerivedArtifactRef]:
        """
        List saved derived artifacts for one market partition.

        If tool_key is provided, results are filtered to that family only.
        """
        self._validate_kind(kind)
        dataset_dir = self._dataset_dir(market=market, kind=kind)
        if not dataset_dir.exists():
            return []

        safe_tool_filter = self._sanitize_segment(tool_key) if tool_key else None

        refs: List[DerivedArtifactRef] = []
        for path in sorted(dataset_dir.glob("*.csv")):
            parsed = self._parse_filename(path.name)
            if parsed is None:
                continue

            parsed_tool_key, parsed_instance_key = parsed
            if safe_tool_filter and parsed_tool_key != safe_tool_filter:
                continue

            refs.append(
                DerivedArtifactRef(
                    kind=kind,
                    tool_key=parsed_tool_key,
                    instance_key=parsed_instance_key,
                    filename=path.name,
                    path=path,
                )
            )

        return refs

    def delete_instance(
        self,
        *,
        market: MarketId,
        kind: DerivedKind,
        tool_key: str,
        instance_key: str,
    ) -> None:
        """
        Delete one derived artifact if it exists.
        """
        path = self.resolve_path(
            market=market,
            kind=kind,
            tool_key=tool_key,
            instance_key=instance_key,
        )
        if path.exists():
            path.unlink()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _dataset_dir(self, *, market: MarketId, kind: DerivedKind) -> Path:
        dataset_type = self._kind_to_dataset_type(kind)
        return self._paths.ensure_dataset_dir(market, dataset_type)

    def _kind_to_dataset_type(self, kind: DerivedKind) -> DatasetType:
        if kind == "indicators":
            return "indicators"
        if kind == "oscillators":
            return "oscillators"
        if kind == "constructs":
            return "constructs"
        raise ValueError(f"Unsupported derived kind: {kind}")

    def _validate_kind(self, kind: str) -> None:
        if kind not in {"indicators", "oscillators", "constructs"}:
            raise ValueError(f"Unsupported derived kind: {kind}")

    def _sanitize_segment(self, value: Any) -> str:
        raw = str(value).strip()
        if not raw:
            raise ValueError("Empty path segment is not allowed.")

        safe = self._SAFE_SEGMENT_RE.sub("-", raw)
        safe = safe.strip(".-_")
        if not safe:
            raise ValueError(f"Could not sanitize path segment: {value!r}")

        return safe.lower()

    def _build_filename(self, *, tool_key: str, instance_key: str) -> str:
        return f"{tool_key}__{instance_key}.csv"

    def _parse_filename(self, filename: str) -> Optional[tuple[str, str]]:
        """
        Parse filenames of the form:
            <tool_key>__<instance_key>.csv
        """
        if not filename.lower().endswith(".csv"):
            return None

        stem = filename[:-4]
        if "__" not in stem:
            return None

        tool_key, instance_key = stem.split("__", 1)
        tool_key = tool_key.strip()
        instance_key = instance_key.strip()

        if not tool_key or not instance_key:
            return None

        return tool_key, instance_key

    def _atomic_write_csv(self, df: pd.DataFrame, target_path: Path) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)

        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            suffix=".tmp",
            prefix="derived_",
            dir=str(target_path.parent),
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
            try:
                df.to_csv(tmp, index=False)
            except Exception:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass
                raise

        os.replace(tmp_path, target_path)