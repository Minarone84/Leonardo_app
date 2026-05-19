from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QPushButton, QTableView, QVBoxLayout, QWidget

from leonardo.data.historical.artifact_metadata_naming import format_ts_ms_rome, format_ts_ms_utc


class _DataFrameTableModel(QAbstractTableModel):
    """Read-only Qt table model backed by a pandas DataFrame preview."""

    def __init__(self, dataframe: Optional[pd.DataFrame] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._dataframe = dataframe if dataframe is not None else pd.DataFrame()

    def set_dataframe(self, dataframe: pd.DataFrame) -> None:
        self.beginResetModel()
        self._dataframe = dataframe
        self.endResetModel()

    def clear(self) -> None:
        self.set_dataframe(pd.DataFrame())

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802 - Qt API
        if parent.isValid():
            return 0
        return int(len(self._dataframe.index))

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802 - Qt API
        if parent.isValid():
            return 0
        return int(len(self._dataframe.columns))

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> object:  # noqa: N802 - Qt API
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        try:
            value = self._dataframe.iat[index.row(), index.column()]
        except Exception:
            return None
        if pd.isna(value):
            return ""
        return str(value)

    def headerData(  # noqa: N802 - Qt API
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.DisplayRole,
    ) -> object:
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            try:
                return str(self._dataframe.columns[section])
            except Exception:
                return ""
        return str(section + 1)


class DataFramePreviewWidget(QGroupBox):
    """Read-only, bounded dataframe preview for Data Manager CSV artifacts.

    This widget is an inspection surface only. It does not edit CSVs, compute
    tools, mutate runtime state, or create chart studies.
    """

    def __init__(self, *, max_rows: int = 500, parent: Optional[QWidget] = None) -> None:
        super().__init__("DataFrame Preview", parent)
        self._max_rows = max(1, int(max_rows))
        self._model = _DataFrameTableModel(parent=self)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 14, 10, 10)
        root.setSpacing(8)

        preview_header = QHBoxLayout()
        preview_header.setSpacing(12)
        root.addLayout(preview_header, 0)

        self._summary = QLabel("Select an OHLCV file, saved artifact, or materialized analysis database to preview.", self)
        self._summary.setWordWrap(True)
        self._summary.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        preview_header.addWidget(self._summary, 1)

        timestamp_area = QVBoxLayout()
        timestamp_area.setSpacing(4)
        preview_header.addLayout(timestamp_area, 1)

        timestamp_title_row = QHBoxLayout()
        timestamp_title_row.setSpacing(8)
        self._timestamp_title = QLabel("Visible timestamp range", self)
        self._timestamp_title.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        timestamp_title_row.addWidget(self._timestamp_title)
        timestamp_title_row.addStretch(1)
        self._clear_button = QPushButton("Clear Preview", self)
        self._clear_button.clicked.connect(self.clear)
        timestamp_title_row.addWidget(self._clear_button)
        timestamp_area.addLayout(timestamp_title_row, 0)

        timestamp_values_row = QHBoxLayout()
        timestamp_values_row.setSpacing(12)
        self._first_timestamp_summary = QLabel("", self)
        self._first_timestamp_summary.setWordWrap(True)
        self._first_timestamp_summary.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        timestamp_values_row.addWidget(self._first_timestamp_summary, 1)

        self._last_timestamp_summary = QLabel("", self)
        self._last_timestamp_summary.setWordWrap(True)
        self._last_timestamp_summary.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        timestamp_values_row.addWidget(self._last_timestamp_summary, 1)
        timestamp_area.addLayout(timestamp_values_row, 0)

        self._table = QTableView(self)
        self._table.setModel(self._model)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(False)
        self._table.setSelectionBehavior(QTableView.SelectRows)
        self._table.setEditTriggers(QTableView.NoEditTriggers)
        root.addWidget(self._table, 1)

    def clear(self) -> None:
        self._model.clear()
        self._summary.setText("Select an OHLCV file, saved artifact, or materialized analysis database to preview.")
        self._first_timestamp_summary.clear()
        self._last_timestamp_summary.clear()

    def load_csv_path(self, path: object, title: str = "DataFrame") -> None:
        csv_path = Path(path)
        if not csv_path.exists():
            self._model.clear()
            self._summary.setText(f"Preview failed: file does not exist: {csv_path}")
            self._first_timestamp_summary.clear()
            self._last_timestamp_summary.clear()
            return

        try:
            dataframe = pd.read_csv(csv_path, nrows=self._max_rows)
        except Exception as exc:
            self._model.clear()
            self._summary.setText(f"Preview failed for {csv_path}: {exc!r}")
            self._first_timestamp_summary.clear()
            self._last_timestamp_summary.clear()
            return

        preview_dataframe = self._prepare_preview_dataframe(dataframe)
        self._model.set_dataframe(preview_dataframe)
        self._table.resizeColumnsToContents()
        first_timestamp_summary, last_timestamp_summary = self._visible_timestamp_summaries(dataframe)
        summary_lines = [
            str(title),
            f"Source: {csv_path}",
            (
                f"Showing first {len(preview_dataframe)} row(s), {len(preview_dataframe.columns)} column(s). "
                f"Preview limit: {self._max_rows} row(s)."
            ),
        ]
        self._summary.setText("\n".join(summary_lines))
        self._first_timestamp_summary.setText(first_timestamp_summary)
        self._last_timestamp_summary.setText(last_timestamp_summary)

    def _prepare_preview_dataframe(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        """Return a display-only dataframe without mutating CSV-backed values.

        ``ts_ms`` remains visible as the raw alignment key. For any previewed
        CSV that exposes ``ts_ms`` (OHLCV, saved artifacts, or materialized
        Analysis Databases), readable UTC and Europe/Rome columns are inserted
        next to it. If a separate epoch-like ``time`` column simply duplicates
        ``ts_ms``, that duplicate is hidden in preview only.
        """
        if dataframe.empty:
            return dataframe

        out = dataframe.copy()
        if "ts_ms" not in out.columns:
            return self._format_epoch_time_column_if_present(out)

        ts_ms_values = pd.to_numeric(out["ts_ms"], errors="coerce")
        insert_at = list(out.columns).index("ts_ms") + 1
        out.insert(insert_at, "ts_utc", ts_ms_values.map(self._format_ts_ms_utc_cell))
        out.insert(insert_at + 1, "ts_rome", ts_ms_values.map(self._format_ts_ms_rome_cell))

        if "time" in out.columns and self._time_column_duplicates_ts_ms(out["time"], ts_ms_values):
            out = out.drop(columns=["time"])

        return out

    def _format_epoch_time_column_if_present(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        if "time" not in dataframe.columns:
            return dataframe

        ts_ms_values = self._epoch_series_to_ts_ms(dataframe["time"])
        if ts_ms_values is None:
            return dataframe

        out = dataframe.copy()
        time_index = list(out.columns).index("time")
        out.insert(time_index + 1, "time_utc", ts_ms_values.map(self._format_ts_ms_utc_cell))
        out.insert(time_index + 2, "time_rome", ts_ms_values.map(self._format_ts_ms_rome_cell))
        return out

    def _time_column_duplicates_ts_ms(self, values: pd.Series, ts_ms_values: pd.Series) -> bool:
        time_ts_ms = self._epoch_series_to_ts_ms(values)
        if time_ts_ms is None:
            return False
        try:
            left = pd.to_numeric(time_ts_ms, errors="coerce")
            right = pd.to_numeric(ts_ms_values, errors="coerce")
            comparable = left.notna() & right.notna()
            if not bool(comparable.any()):
                return False
            return bool((left[comparable].astype("int64") == right[comparable].astype("int64")).all())
        except Exception:
            return False

    def _epoch_series_to_ts_ms(self, values: pd.Series) -> Optional[pd.Series]:
        numeric = pd.to_numeric(values, errors="coerce")
        valid = numeric.dropna()
        if valid.empty:
            return None

        max_abs = float(valid.abs().max())
        if max_abs >= 10_000_000_000:
            return numeric.round()
        if max_abs >= 10_000_000:
            return (numeric * 1000.0).round()
        return None

    def _format_ts_ms_utc_cell(self, value: object) -> str:
        try:
            if pd.isna(value):
                return ""
            return format_ts_ms_utc(int(value))
        except Exception:
            return ""

    def _format_ts_ms_rome_cell(self, value: object) -> str:
        try:
            if pd.isna(value):
                return ""
            return format_ts_ms_rome(int(value))
        except Exception:
            return ""

    def _visible_timestamp_summaries(self, dataframe: pd.DataFrame) -> tuple[str, str]:
        if dataframe.empty or "ts_ms" not in dataframe.columns:
            return "", ""
        try:
            first_ts_ms = dataframe["ts_ms"].iloc[0]
            last_ts_ms = dataframe["ts_ms"].iloc[-1]
        except Exception:
            return "", ""
        return (
            self._format_visible_timestamp_summary("First visible", first_ts_ms),
            self._format_visible_timestamp_summary("Last visible", last_ts_ms),
        )

    def _format_visible_timestamp_summary(self, label: str, ts_ms: object) -> str:
        return (
            f"{label}:\n"
            f"ts_ms: {self._format_raw_ts_ms(ts_ms)}\n"
            f"UTC: {format_ts_ms_utc(ts_ms)}\n"
            f"Europe/Rome: {format_ts_ms_rome(ts_ms)}"
        )

    def _format_raw_ts_ms(self, ts_ms: object) -> str:
        try:
            if pd.isna(ts_ms):
                return "(n/a)"
            return str(int(ts_ms))
        except Exception:
            return str(ts_ms)
