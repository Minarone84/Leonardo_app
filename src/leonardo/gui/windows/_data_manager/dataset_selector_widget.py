from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional, TYPE_CHECKING


MarketKey = tuple[str, str, str, str]

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from leonardo.data.naming import MarketId, canonicalize
from leonardo.gui.windows._data_manager.button_rack import make_button_rack

if TYPE_CHECKING:
    from leonardo.gui.core_bridge import CoreBridge


@dataclass(frozen=True)
class DatasetSelectorOption:
    market: MarketId
    validation_status: str
    reason: str = ""


class DatasetSelectorWidget(QGroupBox):
    """Select one existing historical dataset partition.

    Discovery is CoreBridge-backed and read-only. The widget displays only
    Core/data-approved OHLCV datasets and does not inspect metadata sidecars or
    load candle data into GUI-owned truth.
    """

    NO_LOADABLE_DATASETS_MESSAGE = (
        "No validated OHLCV datasets available.\n"
        "Open Historical \u2192 OHLCV Maintenance to analyze, repair, or source-correct datasets."
    )

    dataset_changed = Signal(object)  # MarketId | None
    preview_ohlcv_requested = Signal()

    def __init__(
        self,
        *,
        historical_root: Path,
        core_bridge: Optional["CoreBridge"] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__("Dataset", parent)
        self._historical_root = Path(historical_root)
        self._core = core_bridge
        self._datasets: list[DatasetSelectorOption] = []
        self._catalog_error = ""

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
            self._dataset_combo.addItem("No validated OHLCV datasets available", None)
            hint = self.NO_LOADABLE_DATASETS_MESSAGE
            if self._catalog_error:
                hint = f"{self._catalog_error}\n{hint}"
            self._hint_label.setText(f"{hint}\nRoot: {self._historical_root}")
        else:
            selected_idx = 0
            for idx, option in enumerate(datasets):
                self._dataset_combo.addItem(_dataset_label(option), option.market)
                if selected_key is not None and _market_key(option.market) == selected_key:
                    selected_idx = idx
            self._dataset_combo.setCurrentIndex(selected_idx)
            self._hint_label.setText(
                f"Found {len(datasets)} validated dataset(s). Root: {self._historical_root}"
            )

        self._dataset_combo.blockSignals(False)
        self._emit_current_dataset()

    def _discover_datasets(self) -> list[DatasetSelectorOption]:
        self._catalog_error = ""
        list_catalog = getattr(self._core, "list_loadable_historical_ohlcv_datasets", None)
        if callable(list_catalog):
            try:
                return _options_from_loadability_reports(list_catalog())
            except Exception as exc:
                self._catalog_error = f"Historical dataset catalog is unavailable: {exc!r}"
                return []

        if self._core is None:
            self._catalog_error = "Historical dataset catalog is unavailable."
            return []

        return self._discover_datasets_from_core_facets()

    def _discover_datasets_from_core_facets(self) -> list[DatasetSelectorOption]:
        datasets: list[DatasetSelectorOption] = []
        try:
            exchange_names = self._core.list_historical_dataset_exchanges()
            for exchange_name in exchange_names:
                market_type_names = self._core.list_historical_dataset_market_types(exchange_name)
                for market_type_name in market_type_names:
                    symbol_names = self._core.list_historical_dataset_symbols(
                        exchange_name,
                        market_type_name,
                    )
                    for symbol_name in symbol_names:
                        timeframe_names = self._core.list_historical_dataset_timeframes(
                            exchange_name,
                            market_type_name,
                            symbol_name,
                        )
                        for timeframe_name in timeframe_names:
                            loadability = self._dataset_loadability(
                                exchange=exchange_name,
                                market_type=market_type_name,
                                symbol=symbol_name,
                                timeframe=timeframe_name,
                            )
                            if not _loadability_is_loadable(loadability):
                                continue
                            datasets.append(
                                DatasetSelectorOption(
                                    market=canonicalize(
                                        exchange_name,
                                        market_type_name,
                                        symbol_name,
                                        timeframe_name,
                                    ),
                                    validation_status=_loadability_validation_status(loadability),
                                    reason=_loadability_reason(loadability),
                                )
                            )
        except Exception as exc:
            self._catalog_error = f"Historical dataset catalog is unavailable: {exc!r}"
            return []

        return _deduplicate_options(datasets)

    def _dataset_loadability(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
    ) -> object:
        loadability_fn = getattr(self._core, "historical_dataset_loadability", None)
        if callable(loadability_fn):
            return loadability_fn(
                exchange=exchange,
                market_type=market_type,
                symbol=symbol,
                timeframe=timeframe,
            )
        return {"loadable": True, "validation_status": "", "reason": ""}

    def _emit_current_dataset(self) -> None:
        current_market = self.current_market()
        self._preview_ohlcv_button.setEnabled(current_market is not None)
        self.dataset_changed.emit(current_market)


def _options_from_loadability_reports(reports: Iterable[object]) -> list[DatasetSelectorOption]:
    options: list[DatasetSelectorOption] = []
    for report in reports:
        if not _loadability_is_loadable(report):
            continue
        dataset_id = _loadability_dataset_id(report)
        if dataset_id is None:
            continue
        market = canonicalize(
            getattr(dataset_id, "exchange", ""),
            getattr(dataset_id, "market_type", ""),
            getattr(dataset_id, "symbol", ""),
            getattr(dataset_id, "timeframe", ""),
        )
        options.append(
            DatasetSelectorOption(
                market=market,
                validation_status=_loadability_validation_status(report),
                reason=_loadability_reason(report),
            )
        )
    return _deduplicate_options(options)


def _deduplicate_options(options: Iterable[DatasetSelectorOption]) -> list[DatasetSelectorOption]:
    seen: set[MarketKey] = set()
    unique: list[DatasetSelectorOption] = []
    for option in options:
        key = _market_key(option.market)
        if key in seen:
            continue
        seen.add(key)
        unique.append(option)
    return unique


def _market_key(market: MarketId) -> MarketKey:
    return (market.exchange, market.market_type, market.symbol, market.timeframe)


def _dataset_label(option: DatasetSelectorOption) -> str:
    market = option.market
    label = f"{market.exchange} / {market.market_type} / {market.symbol} / {market.timeframe}"
    if option.validation_status.strip().lower() == "modified":
        return f"{label} (Modified)"
    return label


def _loadability_dataset_id(loadability: object) -> object | None:
    if isinstance(loadability, Mapping):
        return loadability.get("dataset_id")
    return getattr(loadability, "dataset_id", None)


def _loadability_is_loadable(loadability: object) -> bool:
    if isinstance(loadability, Mapping):
        return bool(loadability.get("loadable"))
    return bool(getattr(loadability, "loadable", False))


def _loadability_validation_status(loadability: object) -> str:
    if isinstance(loadability, Mapping):
        value = loadability.get("validation_status")
    else:
        value = getattr(loadability, "validation_status", "")
    return str(value or "").strip().lower()


def _loadability_reason(loadability: object) -> str:
    if isinstance(loadability, Mapping):
        value = loadability.get("reason")
    else:
        value = getattr(loadability, "reason", "")
    return str(value or "").strip()
