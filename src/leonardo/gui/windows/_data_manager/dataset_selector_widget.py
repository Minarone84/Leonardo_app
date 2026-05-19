from __future__ import annotations

from pathlib import Path
from typing import Optional


MarketKey = tuple[str, str, str, str]

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from leonardo.data.naming import MarketId, canonicalize
from leonardo.gui.windows._data_manager.button_rack import make_button_rack


class DatasetSelectorWidget(QGroupBox):
    """Select one existing historical dataset partition.

    Discovery is filesystem-only and read-only. The widget does not open chart
    sessions and does not load candle data into GUI-owned truth.
    """

    dataset_changed = Signal(object)  # MarketId | None
    preview_ohlcv_requested = Signal()

    def __init__(self, *, historical_root: Path, parent: Optional[QWidget] = None) -> None:
        super().__init__("Dataset", parent)
        self._historical_root = Path(historical_root)
        self._datasets: list[MarketId] = []

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 14, 10, 10)
        root.setSpacing(8)

        content = QVBoxLayout()
        content.setSpacing(8)
        root.addLayout(content, 1)

        form = QFormLayout()
        form.setSpacing(8)
        content.addLayout(form)

        self._dataset_combo = QComboBox(self)
        self._dataset_combo.currentIndexChanged.connect(self._emit_current_dataset)
        form.addRow("Market", self._dataset_combo)

        self._hint_label = QLabel("", self)
        self._hint_label.setWordWrap(True)
        content.addWidget(self._hint_label)

        self._refresh_button = QPushButton("Refresh Datasets", self)
        self._refresh_button.clicked.connect(self.refresh)

        self._preview_ohlcv_button = QPushButton("Preview OHLCV", self)
        self._preview_ohlcv_button.setEnabled(False)
        self._preview_ohlcv_button.clicked.connect(self.preview_ohlcv_requested.emit)
        root.addLayout(make_button_rack(self._refresh_button, self._preview_ohlcv_button), 0)

        self.refresh()

    def current_market(self) -> Optional[MarketId]:
        data = self._dataset_combo.currentData()
        if isinstance(data, MarketId):
            return data
        return None

    def refresh(self) -> None:
        current = self.current_market()
        selected_key = _market_key(current) if current is not None else None
        datasets = self._discover_datasets()
        self._datasets = datasets

        self._dataset_combo.blockSignals(True)
        self._dataset_combo.clear()

        if not datasets:
            self._dataset_combo.addItem("No historical datasets found", None)
            self._hint_label.setText(f"Root: {self._historical_root}")
        else:
            selected_idx = 0
            for idx, market in enumerate(datasets):
                label = f"{market.exchange} / {market.market_type} / {market.symbol} / {market.timeframe}"
                self._dataset_combo.addItem(label, market)
                if selected_key is not None and _market_key(market) == selected_key:
                    selected_idx = idx
            self._dataset_combo.setCurrentIndex(selected_idx)
            self._hint_label.setText(f"Found {len(datasets)} dataset(s). Root: {self._historical_root}")

        self._dataset_combo.blockSignals(False)
        self._emit_current_dataset()

    def _discover_datasets(self) -> list[MarketId]:
        root = self._historical_root
        if not root.exists():
            return []

        datasets: list[MarketId] = []
        for candles_path in sorted(root.glob("*/*/*/*/ohlcv/candles.csv")):
            try:
                timeframe_dir = candles_path.parents[1]
                symbol_dir = candles_path.parents[2]
                market_type_dir = candles_path.parents[3]
                exchange_dir = candles_path.parents[4]
                datasets.append(
                    canonicalize(
                        exchange_dir.name,
                        market_type_dir.name,
                        symbol_dir.name,
                        timeframe_dir.name,
                    )
                )
            except Exception:
                continue

        seen: set[MarketKey] = set()
        unique: list[MarketId] = []
        for market in datasets:
            key = _market_key(market)
            if key in seen:
                continue
            seen.add(key)
            unique.append(market)
        return unique

    def _emit_current_dataset(self) -> None:
        current_market = self.current_market()
        self._preview_ohlcv_button.setEnabled(current_market is not None)
        self.dataset_changed.emit(current_market)


def _market_key(market: MarketId) -> MarketKey:
    return (market.exchange, market.market_type, market.symbol, market.timeframe)
