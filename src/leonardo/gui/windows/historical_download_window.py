from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional, Any

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QMainWindow,
    QMessageBox,
)

from leonardo.data.naming import (
    canonicalize,
    normalize_symbol,
    normalize_timeframe,
)


_LIVE_PROGRESS_MESSAGES = {"download progress", "download batch progress"}
_PROGRESS_UI_THROTTLE_SECONDS = 0.25


@dataclass(frozen=True)
class HistoricalDownloadForm:
    exchange: str
    market_type: str
    symbol: str
    timeframes: tuple[str, ...]
    start_ms: Optional[int]
    end_ms: Optional[int]
    limit: Optional[int]


def _bump_historical_download_widget_tree_font(widget: QWidget, points: int = 1) -> None:
    if bool(widget.property("_historical_download_font_bump_applied")):
        return

    parent = widget.parentWidget()
    if parent is not None and bool(parent.property("_historical_download_font_bump_applied")):
        bumped = QFont(parent.font())
    else:
        bumped = QFont(widget.font())
        point_size = bumped.pointSize()
        if point_size > 0:
            bumped.setPointSize(point_size + points)
        else:
            point_size_f = bumped.pointSizeF()
            if point_size_f > 0:
                bumped.setPointSizeF(point_size_f + float(points))

    for target in (widget, *widget.findChildren(QWidget)):
        target.setFont(QFont(bumped))
    widget.setProperty("_historical_download_font_bump_applied", True)


class DownloadPreflightConfirmDialog(QDialog):
    """Confirmation dialog for Core-owned OHLCV preflight plans."""

    def __init__(self, *, summary: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Confirm OHLCV Download")
        self.resize(900, 700)
        self.setMinimumSize(760, 560)

        title_lbl = QLabel("Confirm OHLCV Download")
        title_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)

        hint_lbl = QLabel("Review the full download work plan below before starting.")
        hint_lbl.setWordWrap(True)
        hint_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.summary_box = QPlainTextEdit()
        self.summary_box.setReadOnly(True)
        self.summary_box.setPlainText(summary)
        self.summary_box.setMinimumHeight(420)

        self.start_btn = QPushButton("Start Download")
        self.cancel_btn = QPushButton("Cancel")

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self.cancel_btn)
        button_row.addWidget(self.start_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(title_lbl)
        layout.addWidget(hint_lbl)
        layout.addWidget(self.summary_box, 1)
        layout.addLayout(button_row)

        self.start_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)
        _bump_historical_download_widget_tree_font(self)


class DownloadTaskMonitorDialog(QDialog):
    """Lightweight GUI monitor for one Core-owned OHLCV download task.

    The dialog displays audit state produced by Core. It does not build
    download plans, calculate persistence truth, or manage async execution.
    """

    _TERMINAL_MESSAGES = {
        "download failed",
        "download cancelled",
        "download batch completed",
        "download batch cancelled",
        "download batch failed",
    }

    def __init__(self, *, on_stop: Callable[[], None], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("OHLCV Download Task")
        self.resize(900, 720)
        self.setMinimumSize(760, 560)

        self._on_stop = on_stop
        self._job_id: Optional[str] = None
        self._context: dict[str, object] = {}
        self._selected_timeframes: tuple[str, ...] = ()
        self._current_timeframe: Optional[str] = None
        self._timeframe_rows: dict[str, dict[str, object]] = {}
        self._completed_timeframes: list[str] = []
        self._remaining_timeframes: list[str] = []
        self._failed_timeframe: Optional[str] = None
        self._batch_terminal_status: Optional[str] = None
        self._batch_validation_dialog_shown = False
        self._last_live_progress_render_at = 0.0
        self._pending_live_progress: Optional[tuple[str, dict[str, object], str]] = None
        self._progress_bar_states: dict[int, tuple[int, int, int, str]] = {}
        self._progress_flush_timer = QTimer(self)
        self._progress_flush_timer.setSingleShot(True)
        self._progress_flush_timer.timeout.connect(self._flush_pending_live_progress)

        self.title_lbl = QLabel("Preparing download task...")
        self.title_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.context_lbl = QLabel("")
        self.context_lbl.setWordWrap(True)
        self.context_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.status_lbl = QLabel("Submitting job...")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.overall_progress = QProgressBar()
        self.overall_progress.setRange(0, 100)
        self.overall_progress.setValue(0)
        self.overall_progress.setFormat("Overall progress: waiting")

        self.current_progress = QProgressBar()
        self.current_progress.setRange(0, 100)
        self.current_progress.setValue(0)
        self.current_progress.setFormat("Current timeframe: waiting")

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(140)

        self.recap_title_lbl = QLabel("Final recap")
        self.recap_title_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.recap_box = QPlainTextEdit()
        self.recap_box.setReadOnly(True)
        self.recap_box.setMinimumHeight(260)
        self.recap_box.setPlainText("Final recap will appear when the task finishes.")

        self.stop_btn = QPushButton("Stop")
        self.ok_btn = QPushButton("OK")
        self.ok_btn.setEnabled(False)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self.stop_btn)
        button_row.addWidget(self.ok_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self.title_lbl)
        layout.addWidget(self.context_lbl)
        layout.addWidget(self.status_lbl)
        layout.addWidget(self.overall_progress)
        layout.addWidget(self.current_progress)
        layout.addWidget(self.log_box)
        layout.addWidget(self.recap_title_lbl)
        layout.addWidget(self.recap_box, 1)
        layout.addLayout(button_row)

        self.stop_btn.clicked.connect(self._on_stop)
        self.ok_btn.clicked.connect(self.accept)
        _bump_historical_download_widget_tree_font(self)

    def set_context(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframes: tuple[str, ...],
        is_batch: bool,
    ) -> None:
        self._context = {
            "exchange": exchange,
            "market_type": market_type,
            "symbol": symbol,
            "is_batch": bool(is_batch),
        }
        self._selected_timeframes = tuple(timeframes)
        self._current_timeframe = self._selected_timeframes[0] if len(self._selected_timeframes) == 1 else None
        self._timeframe_rows = {tf: {"status": "Queued"} for tf in self._selected_timeframes}
        self._batch_validation_dialog_shown = False
        self._apply_preliminary_validation_style("ok")
        mode = "Batch" if is_batch else "Single timeframe"
        self.overall_progress.setVisible(bool(is_batch))
        self.current_progress.setFormat(f"{self._current_timeframe_label()}: waiting")
        self.context_lbl.setText(
            f"{mode} | exchange={exchange} | market={market_type} | "
            f"symbol={symbol} | timeframes={', '.join(timeframes)}"
        )

    def set_job_id(self, job_id: Optional[str]) -> None:
        self._job_id = job_id
        if job_id:
            self.title_lbl.setText(f"OHLCV download task — job_id={job_id}")
        else:
            self.title_lbl.setText("OHLCV download task")

    def mark_stop_requested(self) -> None:
        self.stop_btn.setEnabled(False)
        self.status_lbl.setText("Stop requested. Waiting for Core cancellation...")
        self.append_log("stop requested", "Waiting for Core cancellation event.")

    def update_from_event(self, message: str, fields: dict[str, object], *, is_batch_job: bool) -> None:
        event_timeframe = self._timeframe_from_fields(fields)
        if event_timeframe is not None:
            self._current_timeframe = event_timeframe
        summary = self._event_summary(message, fields)
        self._record_event(message, fields)
        terminal = message in self._TERMINAL_MESSAGES or (message == "download validated" and not is_batch_job)

        if message in _LIVE_PROGRESS_MESSAGES and not terminal:
            self._queue_or_render_live_progress(message, fields, summary)
        else:
            self._flush_pending_live_progress()
            self._render_event_progress(message, fields, summary)

        if terminal:
            self._progress_flush_timer.stop()
            self._render_final_recap(message, fields, is_batch_job=is_batch_job)
            self.stop_btn.setEnabled(False)
            self.ok_btn.setEnabled(True)
            if message == "download batch completed":
                self._show_batch_validation_dialog_once()

    def _queue_or_render_live_progress(self, message: str, fields: dict[str, object], summary: str) -> None:
        now = time.monotonic()
        if (
            self._last_live_progress_render_at <= 0.0
            or now - self._last_live_progress_render_at >= _PROGRESS_UI_THROTTLE_SECONDS
        ):
            self._progress_flush_timer.stop()
            self._pending_live_progress = None
            self._render_event_progress(message, fields, summary)
            self._last_live_progress_render_at = now
            return

        self._pending_live_progress = (message, dict(fields), summary)
        remaining_ms = max(
            1,
            int((_PROGRESS_UI_THROTTLE_SECONDS - (now - self._last_live_progress_render_at)) * 1000),
        )
        self._progress_flush_timer.start(remaining_ms)

    def _flush_pending_live_progress(self) -> None:
        pending = self._pending_live_progress
        if pending is None:
            return
        self._pending_live_progress = None
        self._progress_flush_timer.stop()
        message, fields, summary = pending
        self._render_event_progress(message, fields, summary)
        self._last_live_progress_render_at = time.monotonic()

    def _render_event_progress(self, message: str, fields: dict[str, object], summary: str) -> None:
        if self.status_lbl.text() != summary:
            self.status_lbl.setText(summary)
        self.append_log(message, summary)
        self._update_progress(message, fields)

    def _record_event(self, message: str, fields: dict[str, object]) -> None:
        timeframe = self._timeframe_from_fields(fields)
        if timeframe is not None:
            row = self._timeframe_rows.setdefault(timeframe, {})
            if message == "download started":
                row.update({
                    "status": "Started",
                    "path": fields.get("path"),
                    "local_rows": fields.get("local_row_count"),
                    "local_first_ts_ms": fields.get("local_first_ts_ms"),
                    "local_last_ts_ms": fields.get("local_last_ts_ms"),
                    "metadata_valid": fields.get("local_metadata_valid"),
                    "metadata_repaired": fields.get("local_metadata_repaired"),
                })
            elif message == "download plan ready":
                row.update({
                    "status": "Up to date" if bool(fields.get("up_to_date")) else "Planned",
                    "mode": fields.get("mode"),
                    "expected_bars": fields.get("expected_bars"),
                    "expected_pages": fields.get("expected_pages"),
                    "planned_start_ms": fields.get("effective_start_ms"),
                    "planned_end_ms": fields.get("planned_end_ms"),
                    "latest_closed_ts_ms": fields.get("latest_closed_ts_ms"),
                    "path": fields.get("path") or row.get("path"),
                })
            elif message == "download progress":
                row.update({
                    "status": "Running",
                    "downloaded_bars": fields.get("downloaded_bars"),
                    "expected_bars": fields.get("expected_bars"),
                    "progress_ratio": fields.get("progress_ratio"),
                    "total_rows": fields.get("total_rows"),
                    "first_ts": fields.get("first_ts"),
                    "last_ts": fields.get("last_ts"),
                    "dataframe_first_ts_ms": fields.get("dataframe_first_ts_ms") or fields.get("first_ts"),
                    "dataframe_last_ts_ms": fields.get("dataframe_last_ts_ms") or fields.get("last_ts"),
                    "downloaded_first_ts_ms": fields.get("downloaded_first_ts_ms") or fields.get("oldest_ts"),
                    "downloaded_last_ts_ms": fields.get("downloaded_last_ts_ms") or fields.get("newest_ts"),
                    "last_page_first_ts_ms": fields.get("oldest_ts"),
                    "last_page_last_ts_ms": fields.get("newest_ts"),
                    "path": fields.get("path") or row.get("path"),
                })
            elif message == "download retrying":
                row.update({
                    "status": "Retrying",
                    "retry_reason": fields.get("reason"),
                    "retry_attempt": fields.get("attempt"),
                    "max_attempts": fields.get("max_attempts"),
                })
            elif message == "download stalled":
                row.update({
                    "status": "Stalled",
                    "failure_reason": fields.get("reason"),
                    "stalled_page": fields.get("page"),
                })
            elif message == "download completed":
                row.update({
                    "status": "Downloaded",
                    "fetched": fields.get("fetched"),
                    "downloaded_bars": fields.get("downloaded_bars"),
                    "expected_bars": fields.get("expected_bars"),
                    "total_rows": fields.get("total"),
                    "path": fields.get("path") or row.get("path"),
                    "mode": fields.get("mode") or row.get("mode"),
                    "reason": fields.get("reason"),
                    "progress_ratio": fields.get("progress_ratio"),
                    "dataframe_first_ts_ms": fields.get("dataframe_first_ts_ms") or fields.get("first_ts") or row.get("dataframe_first_ts_ms"),
                    "dataframe_last_ts_ms": fields.get("dataframe_last_ts_ms") or fields.get("last_ts") or row.get("dataframe_last_ts_ms"),
                    "downloaded_first_ts_ms": fields.get("downloaded_first_ts_ms") or row.get("downloaded_first_ts_ms"),
                    "downloaded_last_ts_ms": fields.get("downloaded_last_ts_ms") or row.get("downloaded_last_ts_ms"),
                })
            elif message == "download validated":
                status = self._fmt(fields.get("status"))
                row.update({
                    "status": f"Preliminary validation {status}",
                    "validation_status": fields.get("status"),
                    "validation_rows": fields.get("row_count"),
                    "validation_issues": fields.get("issues") or [],
                    "validation_issue_count": fields.get("issue_count"),
                    "validation_warning_count": fields.get("warning_count"),
                    "validation_error_count": fields.get("error_count"),
                    "metadata_validation_status": fields.get("metadata_validation_status"),
                    "timeframe_step_ms": fields.get("timeframe_step_ms"),
                    "timeframe_continuity": fields.get("timeframe_continuity"),
                    "path": fields.get("path") or row.get("path"),
                    "total_rows": fields.get("row_count") or row.get("total_rows"),
                    "dataframe_first_ts_ms": fields.get("dataframe_first_ts_ms") or fields.get("first_ts") or row.get("dataframe_first_ts_ms"),
                    "dataframe_last_ts_ms": fields.get("dataframe_last_ts_ms") or fields.get("last_ts") or row.get("dataframe_last_ts_ms"),
                })
            elif message == "download cancelled":
                row.update({
                    "status": "Cancelled",
                    "total_rows": fields.get("total"),
                    "path": fields.get("path") or row.get("path"),
                    "mode": fields.get("mode") or row.get("mode"),
                    "reason": fields.get("reason"),
                })
            elif message == "download failed":
                row.update({
                    "status": "Failed",
                    "error": fields.get("error"),
                })

        if message == "download batch item started":
            batch_tf = self._fmt(fields.get("timeframe"))
            self._timeframe_rows.setdefault(batch_tf, {}).update({"status": "Running"})
        elif message == "download batch item completed":
            batch_tf = self._fmt(fields.get("timeframe"))
            row = self._timeframe_rows.setdefault(batch_tf, {})
            validation_status = row.get("validation_status")
            status_text = (
                f"Completed / Preliminary validation {self._fmt(validation_status)}"
                if validation_status is not None
                else "Completed"
            )
            row.update({
                "status": status_text,
                "path": fields.get("path") or row.get("path"),
                "total_rows": fields.get("total_rows") or row.get("total_rows"),
            })
        elif message == "download batch progress":
            self._completed_timeframes = self._string_list(fields.get("completed_timeframes"))
            self._remaining_timeframes = self._string_list(fields.get("remaining_timeframes"))
        elif message == "download batch completed":
            self._batch_terminal_status = "Completed"
            self._completed_timeframes = self._string_list(fields.get("completed_timeframes"))
            self._remaining_timeframes = []
            self._apply_batch_timeframe_results(fields.get("timeframe_results"))
        elif message == "download batch cancelled":
            self._batch_terminal_status = "Cancelled"
            self._completed_timeframes = self._string_list(fields.get("completed_timeframes"))
            self._remaining_timeframes = self._string_list(fields.get("remaining_timeframes"))
            for tf in self._remaining_timeframes:
                self._timeframe_rows.setdefault(tf, {}).setdefault("status", "Cancelled / not completed")
        elif message == "download batch failed":
            self._batch_terminal_status = "Failed"
            self._completed_timeframes = self._string_list(fields.get("completed_timeframes"))
            self._remaining_timeframes = self._string_list(fields.get("remaining_timeframes"))
            self._apply_batch_timeframe_results(fields.get("timeframe_results"))
            failed = fields.get("failed_timeframe")
            self._failed_timeframe = str(failed) if failed else None
            if self._failed_timeframe:
                self._timeframe_rows.setdefault(self._failed_timeframe, {}).update({
                    "status": "Failed",
                    "error": fields.get("error"),
                })

    def _apply_batch_timeframe_results(self, value: object) -> None:
        if not isinstance(value, list):
            return

        for item in value:
            if not isinstance(item, dict):
                continue
            timeframe = str(item.get("timeframe") or "").strip()
            if not timeframe:
                continue

            row = self._timeframe_rows.setdefault(timeframe, {})
            validation_status = item.get("validation_status")
            status_text = item.get("status") or row.get("status")
            if validation_status is not None:
                status_text = f"Completed / Preliminary validation {self._fmt(validation_status)}"

            row.update({
                "status": status_text or "Completed",
                "path": item.get("path") or row.get("path"),
                "total_rows": item.get("total_rows") or row.get("total_rows"),
                "dataframe_first_ts_ms": item.get("dataframe_first_ts_ms") or row.get("dataframe_first_ts_ms"),
                "dataframe_last_ts_ms": item.get("dataframe_last_ts_ms") or row.get("dataframe_last_ts_ms"),
                "validation_status": validation_status if validation_status is not None else row.get("validation_status"),
                "validation_rows": item.get("validation_rows") or row.get("validation_rows"),
                "validation_issues": item.get("validation_issues") if isinstance(item.get("validation_issues"), list) else row.get("validation_issues", []),
                "validation_issue_count": item.get("validation_issue_count") if item.get("validation_issue_count") is not None else row.get("validation_issue_count"),
                "validation_warning_count": item.get("validation_warning_count") if item.get("validation_warning_count") is not None else row.get("validation_warning_count"),
                "validation_error_count": item.get("validation_error_count") if item.get("validation_error_count") is not None else row.get("validation_error_count"),
                "metadata_validation_status": item.get("metadata_validation_status") or row.get("metadata_validation_status"),
                "timeframe_step_ms": item.get("timeframe_step_ms") if item.get("timeframe_step_ms") is not None else row.get("timeframe_step_ms"),
                "timeframe_continuity": item.get("timeframe_continuity") or row.get("timeframe_continuity"),
            })

    def append_log(self, label: str, detail: str) -> None:
        self.log_box.appendPlainText(f"[{label}] {detail}")

    def _set_bar_ratio(self, bar: QProgressBar, ratio: object, *, label: str) -> None:
        try:
            value = float(ratio) if ratio is not None else None
        except Exception:
            value = None

        if value is None:
            self._set_progress_bar_state(bar, 0, 100, 0, f"{label}: waiting")
            return

        pct = max(0, min(100, int(round(value * 100))))
        self._set_progress_bar_state(bar, 0, 100, pct, f"{label}: {pct}%")

    def _set_progress_bar_state(
        self,
        bar: QProgressBar,
        minimum: int,
        maximum: int,
        value: int,
        text: str,
    ) -> None:
        state = (minimum, maximum, value, text)
        key = id(bar)
        if self._progress_bar_states.get(key) == state:
            return

        if bar.minimum() != minimum or bar.maximum() != maximum:
            bar.setRange(minimum, maximum)
        if bar.value() != value:
            bar.setValue(value)
        if bar.format() != text:
            bar.setFormat(text)
        self._progress_bar_states[key] = state

    def _update_progress(self, message: str, fields: dict[str, object]) -> None:
        if message == "download batch started":
            self._set_bar_ratio(self.overall_progress, 0.0, label="Overall progress")
            self._set_progress_bar_state(
                self.current_progress,
                0,
                100,
                0,
                f"{self._current_timeframe_label()}: waiting",
            )
            return

        if message == "download batch item started":
            tf = self._fmt(fields.get("timeframe"))
            if tf != "—":
                self._current_timeframe = tf
            self._set_bar_ratio(self.current_progress, 0.0, label=self._current_timeframe_label())
            return

        if message == "download batch progress":
            self._set_bar_ratio(self.overall_progress, fields.get("progress_ratio"), label="Overall progress")
            return

        if message == "download batch completed":
            self._set_bar_ratio(self.overall_progress, 1.0, label="Overall progress")
            self._set_bar_ratio(self.current_progress, 1.0, label=self._current_timeframe_label())
            return

        if message == "download plan ready":
            if bool(fields.get("up_to_date")):
                self._set_bar_ratio(self.current_progress, 1.0, label=self._current_timeframe_label())
            else:
                self._set_bar_ratio(self.current_progress, 0.0, label=self._current_timeframe_label())
            return

        if message == "download progress":
            self._set_bar_ratio(self.current_progress, fields.get("progress_ratio"), label=self._current_timeframe_label())
            return

        if message in {"download completed", "download validated"}:
            self._set_bar_ratio(self.current_progress, 1.0, label=self._current_timeframe_label())
            return

        if message in {"download failed", "download cancelled", "download batch failed", "download batch cancelled"}:
            self._set_progress_bar_state(
                self.overall_progress,
                self.overall_progress.minimum(),
                self.overall_progress.maximum(),
                self.overall_progress.value(),
                "Overall progress: stopped",
            )
            self._set_progress_bar_state(
                self.current_progress,
                self.current_progress.minimum(),
                self.current_progress.maximum(),
                self.current_progress.value(),
                f"{self._current_timeframe_label()}: stopped",
            )

    def _render_final_recap(self, message: str, fields: dict[str, object], *, is_batch_job: bool) -> None:
        status = self._terminal_status(message, fields, is_batch_job=is_batch_job)
        validation_severity = self._preliminary_validation_severity(message, fields, is_batch_job=is_batch_job)
        self._apply_preliminary_validation_style(validation_severity)
        lines = [
            "Final recap",
            f"Status: {status}",
            f"Job ID: {self._fmt(self._job_id)}",
            (
                f"Market: {self._fmt(self._context.get('exchange'))} / "
                f"{self._fmt(self._context.get('market_type'))} / "
                f"{self._fmt(self._context.get('symbol'))}"
            ),
            f"Requested timeframes: {self._join_list(self._selected_timeframes)}",
        ]

        if is_batch_job:
            if self._completed_timeframes:
                lines.append(f"Completed timeframes: {self._join_list(self._completed_timeframes)}")
            if self._remaining_timeframes:
                lines.append(f"Remaining / not completed: {self._join_list(self._remaining_timeframes)}")
            if self._failed_timeframe:
                lines.append(f"Failed timeframe: {self._failed_timeframe}")
        lines.append("")
        lines.append("Per-timeframe results:")

        for timeframe in self._selected_timeframes:
            row = self._timeframe_rows.get(timeframe, {})
            lines.extend(self._timeframe_recap_lines(timeframe, row))

        if message in {"download failed", "download batch failed"}:
            lines.append("")
            lines.append(f"Failure detail: {self._fmt(fields.get('error'))}")
        elif message in {"download cancelled", "download batch cancelled"}:
            lines.append("")
            lines.append(f"Cancellation reason: {self._fmt(fields.get('reason'))}")

        self.recap_box.setPlainText("\n".join(lines))

    def _timeframe_recap_lines(self, timeframe: str, row: dict[str, object]) -> list[str]:
        separator = "=" * 72
        lines = [
            "",
            separator,
            f"TIMEFRAME: {timeframe}",
            separator,
            f"Status: {self._fmt(row.get('status'), missing='No result recorded')}",
        ]

        details: list[str] = []
        for label, key in (
            ("mode", "mode"),
            ("rows", "total_rows"),
            ("fetched", "fetched"),
            ("downloaded", "downloaded_bars"),
            ("expected", "expected_bars"),
            ("preliminary_validation", "validation_status"),
        ):
            value = row.get(key)
            if value is not None:
                details.append(f"{label}={self._fmt(value)}")
        if details:
            lines.append("Summary: " + " | ".join(details))

        if row.get("path"):
            lines.append(f"Saved file: {self._fmt(row.get('path'))}")

        dataframe_first = row.get("dataframe_first_ts_ms") or row.get("first_ts") or row.get("local_first_ts_ms")
        dataframe_last = row.get("dataframe_last_ts_ms") or row.get("last_ts") or row.get("local_last_ts_ms")
        lines.append(
            "DataFrame range: "
            f"{self._fmt_ts_ms(dataframe_first)} → {self._fmt_ts_ms(dataframe_last)}"
        )

        downloaded_first = row.get("downloaded_first_ts_ms")
        downloaded_last = row.get("downloaded_last_ts_ms")
        if downloaded_first is not None or downloaded_last is not None:
            lines.append(
                "Downloaded range: "
                f"{self._fmt_ts_ms(downloaded_first)} → {self._fmt_ts_ms(downloaded_last)}"
            )
        elif row.get("fetched") == 0:
            lines.append("Downloaded range: No new bars downloaded")
        else:
            lines.append("Downloaded range: —")

        planned_start = row.get("planned_start_ms")
        planned_end = row.get("planned_end_ms")
        if planned_start is not None or planned_end is not None:
            lines.append(
                "Planned range: "
                f"{self._fmt_ts_ms(planned_start)} → {self._fmt_ts_ms(planned_end)}"
            )

        continuity = row.get("timeframe_continuity")
        step_ms = row.get("timeframe_step_ms")
        if continuity == "fixed" and step_ms is not None:
            lines.append(f"Selected timeframe check: fixed step {self._fmt(step_ms)} ms")
        elif continuity == "variable":
            lines.append("Selected timeframe check: variable duration; exact fixed-step continuity is skipped")

        validation_status = row.get("validation_status")
        issues = row.get("validation_issues")
        if validation_status is not None:
            status_text = self._fmt_validation_status(validation_status)
            counts = (
                f"issues={self._fmt(row.get('validation_issue_count'), missing='0')} | "
                f"warnings={self._fmt(row.get('validation_warning_count'), missing='0')} | "
                f"errors={self._fmt(row.get('validation_error_count'), missing='0')}"
            )
            if isinstance(issues, list) and issues:
                lines.append(
                    "Preliminary validation: "
                    + status_text
                    + " | "
                    + counts
                    + " | "
                    + "; ".join(str(issue) for issue in issues[:5])
                )
            else:
                lines.append(f"Preliminary validation: {status_text} | {counts} | No issues detected")
        elif isinstance(issues, list) and issues:
            lines.append("Preliminary validation issues: " + "; ".join(str(issue) for issue in issues[:5]))

        metadata_status = row.get("metadata_validation_status")
        if metadata_status is not None:
            lines.append(f"Metadata validation.status: {self._fmt_validation_status(metadata_status)}")
        if validation_status is not None:
            if self._validation_severity(validation_status) in {"error", "warning"}:
                lines.append(
                    "User action: Open Historical > OHLCV Maintenance to inspect, validate, repair, or source-correct this dataset."
                )
            else:
                lines.append(
                    "User action: Manual OHLCV Maintenance validation is still required before this download is accepted."
                )

        if row.get("error"):
            lines.append(f"Error: {self._fmt(row.get('error'))}")
        if row.get("failure_reason"):
            lines.append(f"Failure reason: {self._fmt(row.get('failure_reason'))}")
        if row.get("reason"):
            lines.append(f"Reason: {self._fmt(row.get('reason'))}")

        return lines

    def _preliminary_validation_severity(
        self,
        message: str,
        fields: dict[str, object],
        *,
        is_batch_job: bool,
    ) -> str:
        if is_batch_job:
            severity = "ok"
            for timeframe in self._selected_timeframes:
                status = str(self._timeframe_rows.get(timeframe, {}).get("validation_status") or "").lower()
                if status == "error":
                    return "error"
                if status == "warning":
                    severity = "warning"
                elif not status and message == "download batch completed":
                    severity = "warning"
            return severity

        if message == "download validated":
            return self._validation_severity(fields.get("status"))
        return "ok"

    def _validation_severity(self, status: object) -> str:
        value = str(status or "").strip().lower()
        if value == "error":
            return "error"
        if value == "warning":
            return "warning"
        return "ok"

    def _fmt_validation_status(self, status: object) -> str:
        value = str(status or "").strip().lower()
        if value == "ok":
            return "OK"
        if value == "warning":
            return "WARNING"
        if value == "error":
            return "ERROR"
        if value == "unknown":
            return "UNKNOWN"
        return self._fmt(status)

    def _apply_preliminary_validation_style(self, severity: str) -> None:
        if severity == "error":
            label_style = "font-weight: 700; color: #b00020;"
            recap_style = "border: 2px solid #b00020;"
        elif severity == "warning":
            label_style = "font-weight: 700; color: #8a5a00;"
            recap_style = "border: 2px solid #b8860b;"
        else:
            label_style = ""
            recap_style = ""
        self.status_lbl.setStyleSheet(label_style)
        self.recap_title_lbl.setStyleSheet(label_style)
        self.recap_box.setStyleSheet(recap_style)

    def _show_batch_validation_dialog_once(self) -> None:
        if self._batch_validation_dialog_shown:
            return
        self._batch_validation_dialog_shown = True

        severity, text = self._batch_validation_summary()
        if severity == "error":
            QMessageBox.critical(self, "Preliminary Validation Failed", text)
        elif severity == "warning":
            QMessageBox.warning(self, "Preliminary Validation Warning", text)
        else:
            QMessageBox.information(self, "Preliminary Validation OK", text)

    def _batch_validation_summary(self) -> tuple[str, str]:
        lines: list[str] = []
        severity = "ok"
        all_clean = True

        for timeframe in self._selected_timeframes:
            row = self._timeframe_rows.get(timeframe, {})
            status = str(row.get("validation_status") or "").lower()
            issues = row.get("validation_issues") or []

            if not status:
                all_clean = False
                if severity != "error":
                    severity = "warning"
                lines.append(f"{timeframe}: preliminary validation result not recorded.")
                continue

            if status == "error":
                severity = "error"
                all_clean = False
            elif status == "warning" and severity != "error":
                severity = "warning"
                all_clean = False

            if isinstance(issues, list) and issues:
                all_clean = False
                issue_text = "; ".join(str(issue) for issue in issues[:8])
                lines.append(f"{timeframe}: preliminary {status} — {issue_text}")
            else:
                lines.append(f"{timeframe}: preliminary {status} — No issues detected")

        if severity == "ok" and all_clean:
            return (
                "ok",
                "Preliminary validation found no issues. Manual OHLCV Maintenance validation is still required.",
            )

        text = "\n".join(lines) if lines else "No preliminary validation details recorded."
        return severity, text + "\n\nOpen Historical > OHLCV Maintenance to inspect and validate the dataset."

    def _terminal_status(self, message: str, fields: dict[str, object], *, is_batch_job: bool) -> str:
        _ = fields
        if message in {"download failed", "download batch failed"}:
            return "Failed"
        if message in {"download cancelled", "download batch cancelled"}:
            return "Cancelled"
        if message == "download batch completed":
            return "Completed"
        if message == "download validated" and not is_batch_job:
            validation_status = str(fields.get("status") or "").lower()
            if validation_status == "ok":
                return "Completed"
            if validation_status == "warning":
                return "Completed with preliminary validation warnings"
            if validation_status == "error":
                return "Completed with preliminary validation errors"
        return self._fmt(self._batch_terminal_status, missing="Completed")

    def _timeframe_from_fields(self, fields: dict[str, object]) -> Optional[str]:
        value = fields.get("timeframe")
        if value is None:
            if len(self._selected_timeframes) == 1:
                return self._selected_timeframes[0]
            return None
        text = str(value).strip()
        return text or None

    def _string_list(self, value: object) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value]
        if isinstance(value, tuple):
            return [str(item) for item in value]
        if value is None:
            return []
        return [str(value)]

    def _join_list(self, values: object) -> str:
        items = self._string_list(values)
        return ", ".join(items) if items else "—"

    def _current_timeframe_label(self) -> str:
        if self._current_timeframe:
            return f"Current timeframe {self._current_timeframe}"
        return "Current timeframe"

    def _fmt_ts_ms(self, value: object) -> str:
        if value is None:
            return "—"
        try:
            dt = datetime.fromtimestamp(int(value) / 1000.0, tz=timezone.utc)
            return f"{dt.strftime('%Y-%m-%d %H:%M:%S')} UTC ({int(value)})"
        except Exception:
            return self._fmt(value)

    def _event_summary(self, message: str, fields: dict[str, object]) -> str:
        fmt = self._fmt
        if message == "download batch started":
            timeframes = fields.get("timeframes") or []
            tf_text = ", ".join(str(tf) for tf in timeframes) if isinstance(timeframes, list) else fmt(timeframes)
            return f"Batch started: {fmt(fields.get('symbol'))} | {tf_text}"
        if message == "download batch item started":
            return (
                f"Batch item started: {fmt(fields.get('timeframe'))} "
                f"({fmt(fields.get('timeframe_index'))}/{fmt(fields.get('total_timeframes'))})"
            )
        if message == "download batch progress":
            return (
                f"Batch progress: {self._fmt_progress(fields.get('progress_ratio'))} "
                f"completed={fmt(fields.get('completed_count'))}/{fmt(fields.get('total_timeframes'))}"
            )
        if message == "download batch completed":
            return f"Batch completed: {fmt(fields.get('completed_count'))}/{fmt(fields.get('total_timeframes'))} timeframes"
        if message == "download batch cancelled":
            return "Batch cancelled by user."
        if message == "download batch failed":
            return f"Batch failed on {fmt(fields.get('failed_timeframe'))}: {fmt(fields.get('error'))}"
        if message == "download started":
            return f"Started: {fmt(fields.get('timeframe'))} | path={fmt(fields.get('path'))}"
        if message == "download plan ready":
            return (
                f"Plan ready: mode={fmt(fields.get('mode'))} "
                f"expected_bars={fmt(fields.get('expected_bars'))} "
                f"expected_pages={fmt(fields.get('expected_pages'))}"
            )
        if message == "download progress":
            return (
                f"Progress: {self._fmt_progress(fields.get('progress_ratio'))} "
                f"page={fmt(fields.get('page'))}/{fmt(fields.get('expected_pages'))} "
                f"downloaded={fmt(fields.get('downloaded_bars'))}/{fmt(fields.get('expected_bars'))}"
            )
        if message == "download retrying":
            return (
                f"Retrying request: attempt={fmt(fields.get('attempt'))} "
                f"next={fmt(fields.get('next_attempt'))}/{fmt(fields.get('max_attempts'))} "
                f"reason={fmt(fields.get('reason'))}"
            )
        if message == "download stalled":
            return f"Download stalled: reason={fmt(fields.get('reason'))} page={fmt(fields.get('page'))}"
        if message == "download completed":
            return (
                f"Download completed: total_rows={fmt(fields.get('total'))} "
                f"fetched={fmt(fields.get('fetched'))}"
            )
        if message == "download validated":
            return f"Preliminary validation {fmt(fields.get('status'))}: row_count={fmt(fields.get('row_count'))}"
        if message == "download cancelled":
            return "Download cancelled by user."
        if message == "download failed":
            return f"Download failed: {fmt(fields.get('error'))}"
        return message or "Running..."

    def _fmt(self, value: object, *, missing: str = "—") -> str:
        if value is None:
            return missing
        if isinstance(value, str) and not value:
            return missing
        return str(value)

    def _fmt_progress(self, ratio: object) -> str:
        if ratio is None:
            return "unknown"
        try:
            return f"{float(ratio) * 100.0:.1f}%"
        except Exception:
            return "unknown"


class HistoricalDownloadWindow(QMainWindow):
    ohlcv_maintenance_requested = Signal()

    def __init__(
        self,
        core_bridge,
        *,
        exchange_names: list[str],
        get_supported_markets: Optional[Callable[[str], list[str]]] = None,
        get_supported_timeframes: Optional[Callable[[str, str], list[str]]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Historical Download Manager")
        self.resize(860, 620)
        self.setMinimumSize(760, 540)

        self._bridge = core_bridge
        self._get_supported_markets = get_supported_markets
        self._get_supported_timeframes = get_supported_timeframes

        self._job_id: Optional[str] = None
        self._stop_requested_pending = False
        self._task_name: Optional[str] = None
        self._validation_dialog_shown = False
        self._is_batch_job = False
        self._task_dialog: Optional[DownloadTaskMonitorDialog] = None
        self._dialog_event_keys_seen: set[tuple[object, object, object]] = set()
        self._last_live_status_render_at = 0.0
        self._pending_live_status: Optional[str] = None

        self._submit_fut = None
        self._submit_watch = QTimer(self)
        self._submit_watch.setInterval(250)
        self._submit_watch.timeout.connect(self._poll_submit_future)

        self._preflight_fut = None
        self._preflight_watch = QTimer(self)
        self._preflight_watch.setInterval(250)
        self._preflight_watch.timeout.connect(self._poll_preflight_future)
        self._pending_form: Optional[HistoricalDownloadForm] = None
        self._pending_market: Any = None

        # ---- UI ----
        root = QWidget(self)
        self.setCentralWidget(root)

        self.exchange_cb = QComboBox()
        self.exchange_cb.addItems(exchange_names or [])

        self.market_cb = QComboBox()
        # Blank default forces explicit user selection
        self._set_market_items([])

        self.symbol_in = QLineEdit()
        self.symbol_in.setPlaceholderText("BTCUSDT / btc-usdt / btc/usdt / BTCUSDT.P ...")

        self.tf_list = QListWidget()
        self.tf_list.setMinimumHeight(120)
        self.tf_list.setMaximumHeight(180)
        self._set_timeframe_items([], selected=())

        self.select_all_tf_btn = QPushButton("Select All Timeframes")
        self.clear_tf_btn = QPushButton("Clear Timeframes")

        self.start_ms_in = QLineEdit()
        self.start_ms_in.setPlaceholderText("start timestamp ms (optional)")

        self.end_ms_in = QLineEdit()
        self.end_ms_in.setPlaceholderText("end timestamp ms (optional)")

        self.limit_sb = QSpinBox()
        self.limit_sb.setRange(0, 5000)
        self.limit_sb.setValue(0)
        self.limit_sb.setToolTip("0 = adapter default")

        self.start_btn = QPushButton("Start")
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.maintenance_btn = QPushButton("OHLCV Maintenance...")

        self._status_text = "Idle."
        self.status_panel = QPlainTextEdit()
        self.status_panel.setReadOnly(True)
        self.status_panel.setPlainText(self._status_text)
        self.status_panel.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.status_panel.setMinimumHeight(84)
        self.status_panel.setMaximumHeight(120)

        form = QFormLayout()
        form.addRow("Exchange", self.exchange_cb)
        form.addRow("Market type", self.market_cb)
        timeframe_box = QWidget()
        timeframe_layout = QVBoxLayout()
        timeframe_layout.setContentsMargins(0, 0, 0, 0)
        timeframe_layout.addWidget(self.tf_list)
        timeframe_button_row = QHBoxLayout()
        timeframe_button_row.addWidget(self.select_all_tf_btn)
        timeframe_button_row.addWidget(self.clear_tf_btn)
        timeframe_button_row.addStretch(1)
        timeframe_layout.addLayout(timeframe_button_row)
        timeframe_box.setLayout(timeframe_layout)

        form.addRow("Symbol", self.symbol_in)
        form.addRow("Timeframes", timeframe_box)
        form.addRow("Start ms", self.start_ms_in)
        form.addRow("End ms", self.end_ms_in)
        form.addRow("Limit", self.limit_sb)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addWidget(self.maintenance_btn)
        btn_row.addStretch(1)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addLayout(btn_row)
        layout.addWidget(self.status_panel)
        root.setLayout(layout)
        _bump_historical_download_widget_tree_font(self)

        # ---- Events ----
        self.exchange_cb.currentTextChanged.connect(self._refresh_markets)
        self.market_cb.currentTextChanged.connect(self._refresh_timeframes)

        self.symbol_in.editingFinished.connect(self._normalize_symbol_field)
        self.start_ms_in.editingFinished.connect(self._validate_ms_fields)
        self.end_ms_in.editingFinished.connect(self._validate_ms_fields)

        self.select_all_tf_btn.clicked.connect(self._select_all_timeframes)
        self.clear_tf_btn.clicked.connect(self._clear_timeframes)

        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn.clicked.connect(self._on_stop)
        self.maintenance_btn.clicked.connect(self.ohlcv_maintenance_requested.emit)

        # ---- Progress polling timer ----
        self._poll = QTimer(self)
        self._poll.setInterval(500)
        self._poll.timeout.connect(self._poll_progress)

        self._live_status_timer = QTimer(self)
        self._live_status_timer.setSingleShot(True)
        self._live_status_timer.timeout.connect(self._flush_pending_live_status)

        self._refresh_markets()

    # -------------------------
    # UI helpers
    # -------------------------
    def _refresh_markets(self) -> None:
        exchange = self.exchange_cb.currentText().strip()

        try:
            markets = self._supported_markets_for_selection(exchange)
        except Exception as e:
            self._set_market_items([])
            self._set_timeframe_items([], selected=())
            self._set_status(f"Market refresh failed: {e}")
            return

        current = self.market_cb.currentText().strip()
        self._set_market_items(markets, selected=current if current in markets else None)
        self._refresh_timeframes()

    def _supported_markets_for_selection(self, exchange: str) -> list[str]:
        """Return market types from the selected exchange/capability source."""
        if self._get_supported_markets is None:
            return []
        markets = self._get_supported_markets(exchange)
        return [str(market) for market in markets]

    def _set_market_items(self, markets: list[str], *, selected: str | None = None) -> None:
        self.market_cb.blockSignals(True)
        self.market_cb.clear()
        self.market_cb.addItem("")
        for market in markets:
            text = str(market)
            self.market_cb.addItem(text)
        if selected:
            index = self.market_cb.findText(selected)
            if index >= 0:
                self.market_cb.setCurrentIndex(index)
        else:
            self.market_cb.setCurrentIndex(0)
        self.market_cb.blockSignals(False)

    def _refresh_timeframes(self) -> None:
        exchange = self.exchange_cb.currentText().strip()
        market_type = self.market_cb.currentText().strip()

        # market type blank -> do not attempt refresh
        if not market_type:
            self._set_timeframe_items([], selected=())
            return

        try:
            tfs = self._supported_timeframes_for_selection(exchange, market_type)
        except Exception as e:
            self._set_status(f"Timeframes refresh failed: {e}")
            return

        if not tfs:
            self._set_timeframe_items([], selected=())
            self._set_status(f"No supported timeframes reported for {exchange}/{market_type}.")
            return

        current = self._checked_timeframes()
        self._set_timeframe_items(tfs, selected=tuple(current) if current else None)

    def _supported_timeframes_for_selection(self, exchange: str, market_type: str) -> list[str]:
        """Return timeframes from the selected exchange/capability source.

        The Download Manager must not own hardcoded timeframe truth. The active
        exchange/capability callback is the source of supported values.
        """
        if self._get_supported_timeframes is None:
            return []
        tfs = self._get_supported_timeframes(exchange, market_type)
        return [str(timeframe) for timeframe in tfs]

    def _set_timeframe_items(self, timeframes: list[str], *, selected: tuple[str, ...] | None = None) -> None:
        checked = set(selected or ())
        if not checked and timeframes:
            checked.add(str(timeframes[0]))

        self.tf_list.clear()
        for timeframe in timeframes:
            text = str(timeframe)
            item = QListWidgetItem(text)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            item.setCheckState(Qt.Checked if text in checked else Qt.Unchecked)
            self.tf_list.addItem(item)

    def _checked_timeframes(self) -> list[str]:
        out: list[str] = []
        for row in range(self.tf_list.count()):
            item = self.tf_list.item(row)
            if item is not None and item.checkState() == Qt.Checked:
                out.append(item.text())
        return out

    def _select_all_timeframes(self) -> None:
        for row in range(self.tf_list.count()):
            item = self.tf_list.item(row)
            if item is not None:
                item.setCheckState(Qt.Checked)

    def _clear_timeframes(self) -> None:
        for row in range(self.tf_list.count()):
            item = self.tf_list.item(row)
            if item is not None:
                item.setCheckState(Qt.Unchecked)

    def _parse_optional_int(self, s: str) -> Optional[int]:
        s = (s or "").strip()
        if not s:
            return None
        return int(s)

    def _set_status(self, msg: str) -> None:
        if self._status_text == msg:
            return
        self._status_text = msg
        self.status_panel.setPlainText(msg)

    def _set_live_progress_status(self, msg: str) -> None:
        now = time.monotonic()
        if (
            self._last_live_status_render_at <= 0.0
            or now - self._last_live_status_render_at >= _PROGRESS_UI_THROTTLE_SECONDS
        ):
            self._live_status_timer.stop()
            self._pending_live_status = None
            self._last_live_status_render_at = now
            self._set_status(msg)
            return

        self._pending_live_status = msg
        remaining_ms = max(
            1,
            int((_PROGRESS_UI_THROTTLE_SECONDS - (now - self._last_live_status_render_at)) * 1000),
        )
        self._live_status_timer.start(remaining_ms)

    def _flush_pending_live_status(self) -> None:
        pending = self._pending_live_status
        if pending is None:
            return
        self._pending_live_status = None
        self._live_status_timer.stop()
        self._last_live_status_render_at = time.monotonic()
        self._set_status(pending)

    def _set_running(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)

    def _fmt(self, value: object, *, missing: str = "—") -> str:
        if value is None:
            return missing
        if isinstance(value, str) and not value:
            return missing
        return str(value)

    def _fmt_progress(self, ratio: object) -> str:
        if ratio is None:
            return "unknown"
        try:
            return f"{float(ratio) * 100.0:.1f}%"
        except Exception:
            return "unknown"

    def _normalize_symbol_field(self) -> None:
        raw = self.symbol_in.text()
        if not raw.strip():
            return
        try:
            canon = normalize_symbol(raw)
            if canon != raw.strip():
                self.symbol_in.setText(canon)
        except Exception as e:
            self._set_status(f"Symbol invalid: {e}")

    def _validate_ms_fields(self) -> None:
        for label, widget in (("Start ms", self.start_ms_in), ("End ms", self.end_ms_in)):
            s = widget.text().strip()
            if not s:
                continue
            try:
                int(s)
            except Exception:
                self._set_status(f"{label} invalid: must be integer ms epoch")
                return

    def _ui(self, fn) -> None:
        """
        Ensure UI mutations happen on the Qt GUI thread.
        Future callbacks run on the core thread; touching Qt there causes killTimer warnings.
        """
        QTimer.singleShot(0, fn)

    # -------------------------
    # Actions
    # -------------------------
    def _open_task_dialog(self, form: HistoricalDownloadForm, market) -> None:
        if self._task_dialog is not None:
            try:
                self._task_dialog.close()
            except Exception:
                pass

        self._task_dialog = DownloadTaskMonitorDialog(on_stop=self._on_stop, parent=self)
        self._task_dialog.set_context(
            exchange=market.exchange,
            market_type=market.market_type,
            symbol=market.symbol,
            timeframes=form.timeframes,
            is_batch=len(form.timeframes) > 1,
        )
        self._task_dialog.set_job_id(None)
        self._task_dialog.show()
        self._task_dialog.raise_()
        self._task_dialog.activateWindow()

    def _collect_form(self) -> HistoricalDownloadForm:
        exchange = self.exchange_cb.currentText().strip()
        market_type = self.market_cb.currentText().strip()

        if not market_type:
            raise ValueError("Market type not selected")

        symbol = normalize_symbol(self.symbol_in.text())
        timeframes = tuple(normalize_timeframe(tf) for tf in self._checked_timeframes())
        if not timeframes:
            raise ValueError("At least one timeframe must be selected")

        start_ms = self._parse_optional_int(self.start_ms_in.text())
        end_ms = self._parse_optional_int(self.end_ms_in.text())

        limit_val = self.limit_sb.value()
        limit = None if limit_val == 0 else int(limit_val)

        return HistoricalDownloadForm(
            exchange=exchange,
            market_type=market_type,
            symbol=symbol,
            timeframes=timeframes,
            start_ms=start_ms,
            end_ms=end_ms,
            limit=limit,
        )

    def _on_start(self) -> None:
        try:
            form = self._collect_form()
            market = canonicalize(form.exchange, form.market_type, form.symbol, form.timeframes[0])
        except Exception as e:
            # Keep message EXACT when market type missing
            if str(e) == "Market type not selected":
                self._set_status("Market type not selected")
            else:
                self._set_status(f"Invalid input: {e}")
            return

        self._pending_form = form
        self._pending_market = market
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self._set_status("Preparing download range. Checking local metadata and exchange candles...")

        self._preflight_fut = self._bridge.preflight_historical_download_batch(
            exchange=market.exchange,
            market_type=market.market_type,
            symbol=market.symbol,
            timeframes=form.timeframes,
            start_ms=form.start_ms,
            end_ms=form.end_ms,
            limit=form.limit,
        )
        self._preflight_watch.start()

    def _poll_preflight_future(self) -> None:
        fut = self._preflight_fut
        if fut is None:
            self._preflight_watch.stop()
            return

        if not fut.done():
            if self._status_text.startswith("Preparing download range"):
                self._set_status("Preparing download range... (Core preflight pending)")
            return

        self._preflight_watch.stop()

        try:
            result = fut.result()
        except Exception as e:
            self._set_status(f"Download preflight failed: {e}")
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self._pending_form = None
            self._pending_market = None
            return

        summary = self._format_preflight_summary(result)
        can_download = bool(getattr(result, "can_download", False))
        if not can_download:
            QMessageBox.warning(self, "Download Preflight", summary)
            self._set_status("Download preflight did not produce a complete downloadable range.")
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self._pending_form = None
            self._pending_market = None
            return

        dialog = DownloadPreflightConfirmDialog(summary=summary, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._set_status("Download cancelled before start.")
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self._pending_form = None
            self._pending_market = None
            return

        form = self._pending_form
        market = self._pending_market
        self._pending_form = None
        self._pending_market = None
        if form is None or market is None:
            self._set_status("Download preflight finished, but pending form state was unavailable.")
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            return

        self._start_confirmed_download(form, market)

    def _format_preflight_summary(self, result: object) -> str:
        items = tuple(getattr(result, "items", ()) or ())
        exchange_raw = self._fmt(getattr(result, "exchange", None))
        exchange = exchange_raw.capitalize() if exchange_raw != "—" else exchange_raw
        market_type = self._fmt(getattr(result, "market_type", None))
        symbol = self._fmt(getattr(result, "symbol", None))
        selected_timeframes = ", ".join(str(getattr(item, "timeframe", "—")) for item in items) or "—"

        def _mode_label(value: object) -> str:
            labels = {
                "new_download": "New download",
                "update_latest": "Update existing file",
                "custom_range": "Custom date range",
                "up_to_date": "Already up to date",
            }
            raw = self._fmt(value)
            return labels.get(raw, raw)

        def _fmt_count(value: object) -> str:
            if value is None:
                return "—"
            try:
                return f"{int(value):,}"
            except Exception:
                return self._fmt(value)

        lines = [
            "Download preflight complete",
            "",
            f"Exchange: {exchange}",
            f"Market: {market_type}",
            f"Asset: {symbol}",
            f"Selected timeframes: {selected_timeframes}",
            "",
            "Work plan:",
            "",
        ]

        separator = "=" * 45
        for item in items:
            timeframe = self._fmt(getattr(item, "timeframe", None))
            local_rows = getattr(item, "local_row_count", None)
            local_exists = bool(getattr(item, "local_csv_exists", False))
            local_first = getattr(item, "local_first_ts_ms", None)
            local_last = getattr(item, "local_last_ts_ms", None)
            planned_start = getattr(item, "planned_start_ms", None)
            planned_end = getattr(item, "planned_end_ms", None)

            lines.extend([
                separator,
                f"Timeframe: {timeframe}",
                separator,
                f"Mode: {_mode_label(getattr(item, 'mode', None))}",
                "",
                "Existing local data:",
            ])

            if not local_exists or int(local_rows or 0) == 0:
                lines.append("No local OHLCV file found.")
            else:
                lines.append("Local OHLCV file found.")
            lines.append(f"Rows: {_fmt_count(local_rows)}")
            lines.append(
                "Local range: "
                f"{self._fmt_ts_ms(local_first)} → {self._fmt_ts_ms(local_last)}"
            )
            lines.extend([
                "",
                "Download data range preview:",
                "Planned range:",
                f"- Oldest data:   {self._fmt_ts_ms(planned_start)}",
                f"- Youngest data: {self._fmt_ts_ms(planned_end)}",
                "",
                "Estimated workload:",
                f"Expected bars: {_fmt_count(getattr(item, 'expected_bars', None))}",
                f"Pages: {_fmt_count(getattr(item, 'expected_pages', None))}",
                f"Page limit: {_fmt_count(getattr(item, 'page_limit', None))}",
            ])

            reason = getattr(item, "reason", None)
            if reason:
                lines.append(f"Reason: {self._fmt(reason)}")
            issues = getattr(item, "local_state_issues", ()) or ()
            if issues:
                lines.append("Local metadata notes: " + "; ".join(str(i) for i in issues))
            lines.append("")

        return "\n".join(lines).rstrip()

    def _fmt_ts_ms(self, value: object) -> str:
        if value is None:
            return "—"
        try:
            dt = datetime.fromtimestamp(int(value) / 1000.0, tz=timezone.utc)
            return f"{dt.strftime('%Y-%m-%d %H:%M:%S')} UTC ({int(value)})"
        except Exception:
            return self._fmt(value)

    def _start_confirmed_download(self, form: HistoricalDownloadForm, market: Any) -> None:
        self._is_batch_job = len(form.timeframes) > 1
        suffix = "batch" if self._is_batch_job else form.timeframes[0]
        self._task_name = f"historical_download:{market.exchange}:{market.market_type}:{market.symbol}:{suffix}"
        self._job_id = None
        self._stop_requested_pending = False
        self._validation_dialog_shown = False
        self._dialog_event_keys_seen.clear()

        self._set_running(True)
        self._set_status("Submitting job...")
        self._open_task_dialog(form, market)

        if len(form.timeframes) == 1:
            self._submit_fut = self._bridge.start_historical_download(
                exchange=market.exchange,
                market_type=market.market_type,
                symbol=market.symbol,
                timeframe=form.timeframes[0],
                start_ms=form.start_ms,
                end_ms=form.end_ms,
                limit=form.limit,
            )
        else:
            self._submit_fut = self._bridge.start_historical_download_batch(
                exchange=market.exchange,
                market_type=market.market_type,
                symbol=market.symbol,
                timeframes=form.timeframes,
                start_ms=form.start_ms,
                end_ms=form.end_ms,
                limit=form.limit,
            )
        self._submit_watch.start()
        self._poll.start()

    def _poll_submit_future(self) -> None:
        fut = self._submit_fut
        if fut is None:
            self._submit_watch.stop()
            return

        if not fut.done():
            if self._status_text.startswith("Submitting job"):
                self._set_status("Submitting job... (core task pending)")
            return

        # future completed -> finalize submission on GUI thread
        self._submit_watch.stop()

        try:
            res = fut.result()
            self._job_id = res.get("job_id") if isinstance(res, dict) else getattr(res, "job_id", None)
            if self._task_dialog is not None:
                self._task_dialog.set_job_id(self._job_id)
            timeframes = res.get("timeframes") if isinstance(res, dict) else None
            if timeframes and len(tuple(timeframes)) > 1:
                self._set_status(
                    f"Batch job submitted. job_id={self._job_id}. "
                    f"timeframes={', '.join(str(tf) for tf in timeframes)}. Waiting for progress..."
                )
            else:
                self._set_status(f"Job submitted. job_id={self._job_id}. Waiting for progress...")

            if self._stop_requested_pending and self._job_id:
                self._request_cancel_current_job()
        except Exception as e:
            self._stop_requested_pending = False
            self._set_status(f"Submit failed: {e}")
            self._set_running(False)
            self._poll.stop()
            return

    def _on_stop(self) -> None:
        self._stop_requested_pending = True
        if not self._job_id:
            self.stop_btn.setEnabled(False)
            self._set_status("Stop requested. Waiting for download job creation...")
            if self._task_dialog is not None:
                self._task_dialog.mark_stop_requested()
            return

        self._request_cancel_current_job()

    def _request_cancel_current_job(self) -> None:
        job_id = self._job_id
        if not job_id:
            return

        try:
            cancel_fut = self._bridge.cancel_historical_download(job_id)
        except Exception as e:
            self._stop_requested_pending = False
            self._set_status(f"Stop request failed: {e}")
            self.stop_btn.setEnabled(True)
            return

        self.stop_btn.setEnabled(False)
        self._set_status(f"Stop requested. job_id={job_id}. Waiting for Core cancellation...")
        if self._task_dialog is not None:
            self._task_dialog.mark_stop_requested()

        def _done(_fut) -> None:
            def _apply() -> None:
                try:
                    accepted = bool(_fut.result())
                except Exception as e:
                    self._stop_requested_pending = False
                    self._set_status(f"Stop request failed: {e}")
                    self.stop_btn.setEnabled(True)
                    return
                if accepted:
                    self._set_status(f"Stop accepted. job_id={job_id}. Waiting for cancellation event...")
                    if self._task_dialog is not None:
                        self._task_dialog.append_log("stop accepted", "Waiting for cancellation event from Core.")
                else:
                    self._stop_requested_pending = False
                    self._set_status(f"Stop requested, but no active download task was found for job_id={job_id}.")
                    self._set_running(False)
                    self._poll.stop()
                    if self._task_dialog is not None:
                        self._task_dialog.update_from_event(
                            "download cancelled",
                            {"reason": "no_active_task", "total": None, "path": None, "mode": None},
                            is_batch_job=self._is_batch_job,
                        )

            self._ui(_apply)

        cancel_fut.add_done_callback(_done)

    # -------------------------
    # Progress (audit polling)
    # -------------------------
    def _poll_progress(self) -> None:
        if not self._job_id:
            return

        snap = self._bridge.try_get_audit_snapshot()
        if not snap:
            return

        events = snap.get("events") or []
        if not isinstance(events, list):
            return

        matching_events: list[tuple[int, dict[str, object]]] = []
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                continue
            if event.get("event_type") != "historical_download":
                continue
            event_fields = event.get("fields") or {}
            if not isinstance(event_fields, dict):
                continue
            if event_fields.get("job_id") != self._job_id:
                continue
            matching_events.append((index, event))

        if self._task_dialog is not None:
            for index, event in matching_events:
                event_fields = event.get("fields") or {}
                if not isinstance(event_fields, dict):
                    continue
                event_key = (index, event.get("ts_ms"), event.get("message"))
                if event_key in self._dialog_event_keys_seen:
                    continue
                self._task_dialog.update_from_event(
                    str(event.get("message", "")),
                    event_fields,
                    is_batch_job=self._is_batch_job,
                )
                self._dialog_event_keys_seen.add(event_key)

        for ev in reversed(events):
            if not isinstance(ev, dict):
                continue
            if ev.get("event_type") != "historical_download":
                continue
            fields = ev.get("fields") or {}
            if not isinstance(fields, dict):
                continue
            if fields.get("job_id") != self._job_id:
                continue

            msg = ev.get("message", "")
            if msg not in _LIVE_PROGRESS_MESSAGES:
                self._flush_pending_live_status()

            if msg == "download batch started":
                timeframes = fields.get("timeframes") or []
                self._set_status(
                    "Batch download started.\n"
                    f"symbol={self._fmt(fields.get('symbol'))} "
                    f"timeframes={', '.join(str(tf) for tf in timeframes) if isinstance(timeframes, list) else self._fmt(timeframes)}\n"
                    f"total_timeframes={self._fmt(fields.get('total_timeframes'))}"
                )
                return

            if msg == "download batch item started":
                completed = fields.get("completed_timeframes") or []
                self._set_status(
                    "Batch item started.\n"
                    f"timeframe={self._fmt(fields.get('timeframe'))} "
                    f"item={self._fmt(fields.get('timeframe_index'))}/{self._fmt(fields.get('total_timeframes'))}\n"
                    f"completed={', '.join(str(tf) for tf in completed) if isinstance(completed, list) else self._fmt(completed)}"
                )
                return

            if msg == "download batch item completed":
                self._set_status(
                    "Batch item completed.\n"
                    f"timeframe={self._fmt(fields.get('timeframe'))} "
                    f"item={self._fmt(fields.get('timeframe_index'))}/{self._fmt(fields.get('total_timeframes'))}\n"
                    f"total_rows={self._fmt(fields.get('total_rows'))} "
                    f"path={self._fmt(fields.get('path'))}"
                )
                return

            if msg == "download batch progress":
                completed = fields.get("completed_timeframes") or []
                remaining = fields.get("remaining_timeframes") or []
                self._set_live_progress_status(
                    "Batch progress.\n"
                    f"overall={self._fmt_progress(fields.get('progress_ratio'))} "
                    f"completed={self._fmt(fields.get('completed_count'))}/{self._fmt(fields.get('total_timeframes'))}\n"
                    f"completed_timeframes={', '.join(str(tf) for tf in completed) if isinstance(completed, list) else self._fmt(completed)}\n"
                    f"remaining_timeframes={', '.join(str(tf) for tf in remaining) if isinstance(remaining, list) else self._fmt(remaining)}"
                )
                return

            if msg == "download batch completed":
                self._stop_requested_pending = False
                completed = fields.get("completed_timeframes") or []
                self._set_status(
                    "Batch download completed.\n"
                    f"completed={self._fmt(fields.get('completed_count'))}/{self._fmt(fields.get('total_timeframes'))}\n"
                    f"completed_timeframes={', '.join(str(tf) for tf in completed) if isinstance(completed, list) else self._fmt(completed)}"
                )
                self._poll.stop()
                self._set_running(False)
                return

            if msg == "download batch cancelled":
                self._stop_requested_pending = False
                completed = fields.get("completed_timeframes") or []
                remaining = fields.get("remaining_timeframes") or []
                self._set_status(
                    "Batch download cancelled.\n"
                    f"completed={', '.join(str(tf) for tf in completed) if isinstance(completed, list) else self._fmt(completed)}\n"
                    f"remaining={', '.join(str(tf) for tf in remaining) if isinstance(remaining, list) else self._fmt(remaining)}"
                )
                self._poll.stop()
                self._set_running(False)
                return

            if msg == "download batch failed":
                self._stop_requested_pending = False
                self._set_status(
                    "Batch download failed.\n"
                    f"failed_timeframe={self._fmt(fields.get('failed_timeframe'))}\n"
                    f"error={self._fmt(fields.get('error'))}"
                )
                self._poll.stop()
                self._set_running(False)
                return

            if msg == "download validated":
                status = fields.get("status")
                issues = fields.get("issues") or []
                timeframe_text = self._fmt(fields.get("timeframe"))

                if status == "ok":
                    self._set_status(f"Validation OK for {timeframe_text}. Dataset is clean.")
                elif status == "warning":
                    self._set_status(f"Validation warnings for {timeframe_text}:\n" + "\n".join(issues))
                elif status == "error":
                    self._set_status(f"Validation FAILED for {timeframe_text}:\n" + "\n".join(issues))
                else:
                    self._set_status(f"Validation finished for {timeframe_text}.")

                if self._is_batch_job:
                    return

                # ---- dialog (shown once) ----
                if not self._validation_dialog_shown:
                    self._validation_dialog_shown = True

                    text = "\n".join(issues) if issues else "No issues detected."

                    if status == "ok":
                        QMessageBox.information(self, "Validation OK", text)
                    elif status == "warning":
                        QMessageBox.warning(self, "Validation Warning", text)
                    elif status == "error":
                        QMessageBox.critical(self, "Validation Failed", text)
                    else:
                        QMessageBox.information(self, "Validation", text)

                self._stop_requested_pending = False
                self._poll.stop()
                self._set_running(False)
                return

            if msg == "download cancelled":
                self._stop_requested_pending = False
                self._set_status(
                    "Download cancelled.\n"
                    f"reason={self._fmt(fields.get('reason'))}"
                )
                self._poll.stop()
                self._set_running(False)
                return

            if msg == "download failed":
                self._stop_requested_pending = False
                self._set_status(f"Failed: {fields.get('error')}")
                self._poll.stop()
                self._set_running(False)
                return

            if msg == "download stalled":
                self._set_status(
                    "Download stalled.\n"
                    f"reason={self._fmt(fields.get('reason'))} "
                    f"page={self._fmt(fields.get('page'))}/{self._fmt(fields.get('expected_pages'))} "
                    f"attempts={self._fmt(fields.get('attempt'))}/{self._fmt(fields.get('max_attempts'))}\n"
                    f"timeout_seconds={self._fmt(fields.get('timeout_seconds'))} "
                    f"cursor_ms={self._fmt(fields.get('cursor_ms'))}"
                )
                return

            if msg == "download retrying":
                self._set_status(
                    "Download request retrying.\n"
                    f"reason={self._fmt(fields.get('reason'))} "
                    f"attempt={self._fmt(fields.get('attempt'))} "
                    f"next_attempt={self._fmt(fields.get('next_attempt'))}/{self._fmt(fields.get('max_attempts'))}\n"
                    f"page={self._fmt(fields.get('page'))}/{self._fmt(fields.get('expected_pages'))} "
                    f"timeout_seconds={self._fmt(fields.get('timeout_seconds'))}\n"
                    f"error={self._fmt(fields.get('error'))}"
                )
                return

            if msg == "download completed":
                self._set_status(
                    f"Download completed. total={fields.get('total')} "
                    f"fetched={fields.get('fetched')} "
                    f"path={fields.get('path')} "
                    f"Waiting for validation..."
                )
                return

            if msg == "download started":
                self._set_status(f"Started. path={fields.get('path')}")
                return

            if msg == "download progress":
                self._set_live_progress_status(
                    f"Progress: page={fields.get('page')} "
                    f"page_fetched={fields.get('page_fetched')} "
                    f"total_rows={fields.get('total_rows')} "
                    f"last_ts={fields.get('last_ts')}"
                )
                return

            self._set_status(msg or "Running...")
            return

    # Keeping this method to avoid unnecessary churn; it is no longer used by _poll_progress.
    def _on_progress_event(self, fut) -> None:
        def _apply() -> None:
            try:
                ev: Any = fut.result()
                if not ev:
                    return
                msg = ev.get("message") if isinstance(ev, dict) else getattr(ev, "message", "")
                fields = ev.get("fields") if isinstance(ev, dict) else getattr(ev, "fields", {}) or {}
                self._set_status(msg or "Running...")
            except Exception as e:
                self._set_status(f"Progress read error: {e}")

        self._ui(_apply)
