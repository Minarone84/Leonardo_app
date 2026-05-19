from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pandas as pd


class HistoricalChartConstructSourceMixin:
    def _resolve_construct_sources_into_dataframe(
        self,
        *,
        df: pd.DataFrame,
        payload: Dict[str, Any],
    ) -> pd.DataFrame:
        """
        Resolve all structured construct input bindings into the working dataframe.

        Supported binding shapes:
        - single-role dict metadata (source, fast, mid, slow, etc.)
        - ordered list metadata for multi-source roles such as source_columns

        This method is intentionally role-agnostic. Runtime truth now includes
        unary, fast/slow, fast/mid/slow, and ordered multi-source constructs, so
        controller-side source resolution must consume the full binding contract
        rather than assuming unary-only inputs.
        """
        input_binding_meta = payload.get("input_binding_meta", {}) or {}
        if not isinstance(input_binding_meta, dict) or not input_binding_meta:
            return df

        out = df.copy()

        for role_name, role_meta in input_binding_meta.items():
            if isinstance(role_meta, dict):
                out = self._inject_construct_source_meta_into_dataframe(
                    df=out,
                    source_meta=role_meta,
                    role_name=str(role_name),
                )
                continue

            if isinstance(role_meta, list):
                for idx, entry in enumerate(role_meta):
                    if not isinstance(entry, dict):
                        raise ValueError(
                            f"Invalid source metadata entry for role '{role_name}[{idx}]'."
                        )
                    out = self._inject_construct_source_meta_into_dataframe(
                        df=out,
                        source_meta=entry,
                        role_name=f"{role_name}[{idx}]",
                    )
                continue

            raise ValueError(f"Unsupported source metadata payload for role '{role_name}'.")

        return out

    def _inject_construct_source_meta_into_dataframe(
        self,
        *,
        df: pd.DataFrame,
        source_meta: Dict[str, Any],
        role_name: str,
    ) -> pd.DataFrame:
        """
        Inject a bound construct source series into the working dataframe.

        Supported binding sources:
        - default market columns already present in the dataframe
        - temporary chart-session study outputs
        - saved indicator / oscillator / construct artifact columns

        Matching strategy
        -----------------
        1. if the required column already exists in df, do nothing
        2. otherwise perform a deterministic left-join on ts_ms or time

        Important rule
        --------------
        Positional injection is intentionally forbidden.

        Equal dataframe lengths do NOT prove alignment. Two artifacts may have
        the same row count while referring to different timestamps, sessions, or
        partial datasets. This update therefore removes the old positional
        shortcut and requires an explicit join key.
        """
        family = str(source_meta.get("family", "default")).strip().lower()
        source_kind = str(source_meta.get("source_kind", "saved")).strip().lower()
        column_name = str(source_meta.get("column_name", "")).strip()
        artifact_path = str(source_meta.get("artifact_path", "")).strip()

        if family == "default":
            return df

        if not column_name:
            raise ValueError(f"Invalid source metadata for role '{role_name}'.")

        if column_name in df.columns:
            return df

        if source_kind == "temporary":
            projection_key = str(source_meta.get("projection_key", "")).strip()
            if not projection_key:
                raise ValueError(f"Invalid temporary source metadata for role '{role_name}'.")

            study = self._session.studies_by_projection_key.get(projection_key)
            if study is None:
                raise ValueError(
                    f"Temporary source projection '{projection_key}' is not available for role '{role_name}'."
                )

            source_lines = list(getattr(study, "full_lines", []) or []) + list(
                getattr(study, "full_analysis_source_lines", []) or []
            )
            for line in source_lines:
                if str(line.key).strip() != column_name:
                    continue
                src_df = line.values.rename(column_name).reset_index()
                if src_df.empty:
                    raise ValueError(
                        f"Temporary source '{column_name}' is empty for role '{role_name}'."
                    )
                return self._merge_source_dataframe_column(
                    df=df,
                    src_df=src_df,
                    column_name=column_name,
                    role_name=role_name,
                    source_label=f"temporary projection '{projection_key}'",
                )

            raise ValueError(
                f"Temporary source '{column_name}' was not found in projection '{projection_key}' for role '{role_name}'."
            )

        if not artifact_path:
            raise ValueError(f"Invalid source metadata for role '{role_name}'.")

        path = Path(artifact_path)
        if not path.exists():
            raise FileNotFoundError(f"Source artifact not found for role '{role_name}': {path}")

        src_df = pd.read_csv(path)
        if src_df.empty:
            raise ValueError(f"Source artifact is empty for role '{role_name}': {path}")

        if column_name not in src_df.columns:
            raise ValueError(f"Column '{column_name}' not found in artifact for role '{role_name}': {path}")

        return self._merge_source_dataframe_column(
            df=df,
            src_df=src_df,
            column_name=column_name,
            role_name=role_name,
            source_label=str(path),
        )

    def _merge_source_dataframe_column(
        self,
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
