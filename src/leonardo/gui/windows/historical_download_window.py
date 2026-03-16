from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Any

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QMainWindow,
)

from leonardo.data.naming import (
    canonicalize,
    normalize_symbol,
    normalize_timeframe,
)


@dataclass(frozen=True)
class HistoricalDownloadForm:
    exchange: str
    market_type: str
    symbol: str
    timeframe: str
    start_ms: Optional[int]
    end_ms: Optional[int]
    limit: Optional[int]


class HistoricalDownloadWindow(QMainWindow):
    def __init__(
        self,
        core_bridge,
        *,
        exchange_names: list[str],
        get_supported_timeframes: Optional[Callable[[str, str], list[str]]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Historical Download Manager")

        self._bridge = core_bridge
        self._get_supported_timeframes = get_supported_timeframes

        self._job_id: Optional[str] = None
        self._task_name: Optional[str] = None

        self._submit_fut = None
        self._submit_watch = QTimer(self)
        self._submit_watch.setInterval(250)
        self._submit_watch.timeout.connect(self._poll_submit_future)

        # ---- UI ----
        root = QWidget(self)
        self.setCentralWidget(root)

        self.exchange_cb = QComboBox()
        self.exchange_cb.addItems(exchange_names or ["bybit"])

        self.market_cb = QComboBox()
        # Blank default forces explicit user selection
        self.market_cb.addItems(["", "spot", "linear", "inverse", "options"])

        self.symbol_in = QLineEdit()
        self.symbol_in.setPlaceholderText("BTCUSDT / btc-usdt / btc/usdt / BTCUSDT.P ...")

        self.tf_cb = QComboBox()
        # include 1M now that naming + bybit support it
        self.tf_cb.addItems(["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "60m", "1M"])

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

        self.status_lbl = QLabel("Idle.")
        self.status_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)

        form = QFormLayout()
        form.addRow("Exchange", self.exchange_cb)
        form.addRow("Market type", self.market_cb)
        form.addRow("Symbol", self.symbol_in)
        form.addRow("Timeframe", self.tf_cb)
        form.addRow("Start ms", self.start_ms_in)
        form.addRow("End ms", self.end_ms_in)
        form.addRow("Limit", self.limit_sb)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addStretch(1)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addLayout(btn_row)
        layout.addWidget(self.status_lbl)
        root.setLayout(layout)

        # ---- Events ----
        self.exchange_cb.currentTextChanged.connect(self._refresh_timeframes)
        self.market_cb.currentTextChanged.connect(self._refresh_timeframes)

        self.symbol_in.editingFinished.connect(self._normalize_symbol_field)
        self.start_ms_in.editingFinished.connect(self._validate_ms_fields)
        self.end_ms_in.editingFinished.connect(self._validate_ms_fields)

        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn.clicked.connect(self._on_stop)

        # ---- Progress polling timer ----
        self._poll = QTimer(self)
        self._poll.setInterval(500)
        self._poll.timeout.connect(self._poll_progress)

        self._refresh_timeframes()

    # -------------------------
    # UI helpers
    # -------------------------
    def _refresh_timeframes(self) -> None:
        if not self._get_supported_timeframes:
            return

        exchange = self.exchange_cb.currentText().strip()
        market_type = self.market_cb.currentText().strip()

        # market type blank -> do not attempt refresh
        if not market_type:
            return

        try:
            tfs = self._get_supported_timeframes(exchange, market_type)
        except Exception as e:
            self._set_status(f"Timeframes refresh failed: {e}")
            return

        if not tfs:
            return

        current = self.tf_cb.currentText()
        self.tf_cb.clear()
        self.tf_cb.addItems(tfs)
        if current in tfs:
            self.tf_cb.setCurrentText(current)

    def _parse_optional_int(self, s: str) -> Optional[int]:
        s = (s or "").strip()
        if not s:
            return None
        return int(s)

    def _set_status(self, msg: str) -> None:
        self.status_lbl.setText(msg)

    def _set_running(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)

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
    def _collect_form(self) -> HistoricalDownloadForm:
        exchange = self.exchange_cb.currentText().strip()
        market_type = self.market_cb.currentText().strip()

        if not market_type:
            raise ValueError("Market type not selected")

        symbol = normalize_symbol(self.symbol_in.text())
        timeframe = normalize_timeframe(self.tf_cb.currentText())

        start_ms = self._parse_optional_int(self.start_ms_in.text())
        end_ms = self._parse_optional_int(self.end_ms_in.text())

        limit_val = self.limit_sb.value()
        limit = None if limit_val == 0 else int(limit_val)

        return HistoricalDownloadForm(
            exchange=exchange,
            market_type=market_type,
            symbol=symbol,
            timeframe=timeframe,
            start_ms=start_ms,
            end_ms=end_ms,
            limit=limit,
        )

    def _on_start(self) -> None:
        try:
            form = self._collect_form()
            market = canonicalize(form.exchange, form.market_type, form.symbol, form.timeframe)
        except Exception as e:
            # Keep message EXACT when market type missing
            if str(e) == "Market type not selected":
                self._set_status("Market type not selected")
            else:
                self._set_status(f"Invalid input: {e}")
            return

        self._task_name = f"historical_download:{market.exchange}:{market.market_type}:{market.symbol}:{market.timeframe}"
        self._job_id = None

        self._set_running(True)
        self._set_status("Submitting job...")

        # IMPORTANT: capture ctx in GUI thread; do not touch CoreBridge (QObject) inside core thread coroutine
        ctx = self._bridge.context

        async def _submit():
            from leonardo.data.historical.downloader import HistoricalDownloader, DownloadRequest

            dl = HistoricalDownloader()
            job_id = dl.start(
                ctx,
                DownloadRequest(
                    exchange=market.exchange,
                    market_type=market.market_type,
                    symbol=market.symbol,
                    timeframe=market.timeframe,
                    start_ms=form.start_ms,
                    end_ms=form.end_ms,
                    limit=form.limit,
                ),
            )
            return {"job_id": job_id}

        # submit to core loop
        self._submit_fut = self._bridge.submit(_submit())
        self._submit_watch.start()
        self._poll.start()

    def _poll_submit_future(self) -> None:
        fut = self._submit_fut
        if fut is None:
            self._submit_watch.stop()
            return

        if not fut.done():
            if self.status_lbl.text().startswith("Submitting job"):
                self._set_status("Submitting job... (core task pending)")
            return

        # future completed -> finalize submission on GUI thread
        self._submit_watch.stop()

        try:
            res = fut.result()
            self._job_id = res.get("job_id") if isinstance(res, dict) else getattr(res, "job_id", None)
            self._set_status(f"Job submitted. job_id={self._job_id}. Waiting for progress...")
        except Exception as e:
            self._set_status(f"Submit failed: {e}")
            self._set_running(False)
            self._poll.stop()
            return

    def _on_stop(self) -> None:
        self._set_status("Stop requested (cancellation not wired yet).")
        self._poll.stop()
        self._submit_watch.stop()
        self._set_running(False)

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
            if msg == "download completed":
                self._set_status(
                    f"Completed. total={fields.get('total')} fetched={fields.get('fetched')} path={fields.get('path')}"
                )
                self._poll.stop()
                self._set_running(False)
                return

            if msg == "download failed":
                self._set_status(f"Failed: {fields.get('error')}")
                self._poll.stop()
                self._set_running(False)
                return

            if msg == "download started":
                self._set_status(f"Started. path={fields.get('path')}")
                return

            if msg == "download progress":
                self._set_status(
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