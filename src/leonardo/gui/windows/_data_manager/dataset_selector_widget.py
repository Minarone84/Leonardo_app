from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional, TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import QComboBox, QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from leonardo.data.naming import MarketId, canonicalize
from leonardo.gui.windows._data_manager.button_rack import make_button_rack

if TYPE_CHECKING:
    from leonardo.gui.core_bridge import CoreBridge


MarketKey = tuple[str, str, str, str]

INVALID_SELECTION_STYLE = "QComboBox { color: #b00020; font-weight: 700; }"


@dataclass(frozen=True)
class DatasetSelectorOption:
    market: MarketId
    loadable: bool
    validation_status: str
    reason: str = ""
    csv_path: str = ""
    metadata_path: str = ""


class DatasetSelectorWidget(QGroupBox):
    """Select one historical OHLCV dataset partition.

    Discovery is CoreBridge-backed and read-only. The widget displays
    Core/data-owned loadability reports and does not inspect metadata sidecars,
    parse CSV files, or decide validation policy locally.
    """

    NO_DATASETS_MESSAGE = (
        "No OHLCV datasets available.\n"
        "Open Historical -> OHLCV Maintenance to analyze, repair, or source-correct datasets."
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
        self._updating = False

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 14, 10, 10)
        root.setSpacing(8)

        content = QVBoxLayout()
        content.setSpacing(8)
        root.addLayout(content, 1)

        selector_row = QHBoxLayout()
        selector_row.setSpacing(8)
        content.addLayout(selector_row)

        self._exchange_combo = self._new_combo("dataset_exchange_combo")
        self._exchange_combo.currentIndexChanged.connect(self._on_exchange_changed)
        selector_row.addWidget(self._exchange_combo, 1)

        self._market_type_combo = self._new_combo("dataset_market_type_combo")
        self._market_type_combo.currentIndexChanged.connect(self._on_market_type_changed)
        selector_row.addWidget(self._market_type_combo, 1)

        self._symbol_combo = self._new_combo("dataset_symbol_combo")
        self._symbol_combo.currentIndexChanged.connect(self._on_symbol_changed)
        selector_row.addWidget(self._symbol_combo, 1)

        self._timeframe_combo = self._new_combo("dataset_timeframe_combo")
        self._timeframe_combo.currentIndexChanged.connect(self._emit_current_dataset)
        selector_row.addWidget(self._timeframe_combo, 1)

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
        option = self.current_option()
        return option.market if option is not None else None

    def current_option(self) -> Optional[DatasetSelectorOption]:
        data = self._timeframe_combo.currentData()
        if isinstance(data, DatasetSelectorOption):
            return data
        return None

    def current_loadability(self) -> object | None:
        return self.current_option()

    def refresh(self) -> None:
        current = self.current_market()
        selected_key = _market_key(current) if current is not None else None
        self._datasets = self._discover_datasets()

        self._updating = True
        try:
            self._populate_from_selection(selected_key)
        finally:
            self._updating = False
        self._emit_current_dataset()

    def _new_combo(self, object_name: str) -> QComboBox:
        combo = QComboBox(self)
        combo.setObjectName(object_name)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(10)
        return combo

    def _populate_from_selection(self, selected_key: MarketKey | None) -> None:
        self._clear_combo(self._exchange_combo, "Exchange")
        self._clear_combo(self._market_type_combo, "Market Type")
        self._clear_combo(self._symbol_combo, "Asset")
        self._clear_combo(self._timeframe_combo, "OHLCV / Timeframe")
        self._timeframe_combo.setStyleSheet("")

        if not self._datasets:
            hint = self.NO_DATASETS_MESSAGE
            if self._catalog_error:
                hint = f"{self._catalog_error}\n{hint}"
            self._hint_label.setText(f"{hint}\nRoot: {self._historical_root}")
            return

        exchanges = _unique_sorted(option.market.exchange for option in self._datasets)
        selected_exchange = selected_key[0] if selected_key is not None else None
        self._set_string_combo_items(
            self._exchange_combo,
            placeholder="Exchange",
            values=exchanges,
            selected=selected_exchange,
        )
        if selected_exchange not in exchanges:
            self._set_catalog_hint()
            return

        self._populate_market_types(selected_exchange, selected_key=selected_key)

    def _populate_market_types(self, exchange: str, *, selected_key: MarketKey | None = None) -> None:
        market_types = _unique_sorted(
            option.market.market_type
            for option in self._datasets
            if option.market.exchange == exchange
        )
        selected_market_type = selected_key[1] if selected_key is not None else None
        self._set_string_combo_items(
            self._market_type_combo,
            placeholder="Market Type",
            values=market_types,
            selected=selected_market_type,
        )
        self._clear_combo(self._symbol_combo, "Asset")
        self._clear_combo(self._timeframe_combo, "OHLCV / Timeframe")
        self._timeframe_combo.setStyleSheet("")
        if selected_market_type in market_types:
            self._populate_symbols(exchange, selected_market_type, selected_key=selected_key)
        else:
            self._set_catalog_hint()

    def _populate_symbols(
        self,
        exchange: str,
        market_type: str,
        *,
        selected_key: MarketKey | None = None,
    ) -> None:
        symbols = _unique_sorted(
            option.market.symbol
            for option in self._datasets
            if option.market.exchange == exchange and option.market.market_type == market_type
        )
        selected_symbol = selected_key[2] if selected_key is not None else None
        self._set_string_combo_items(
            self._symbol_combo,
            placeholder="Asset",
            values=symbols,
            selected=selected_symbol,
        )
        self._clear_combo(self._timeframe_combo, "OHLCV / Timeframe")
        self._timeframe_combo.setStyleSheet("")
        if selected_symbol in symbols:
            self._populate_timeframes(exchange, market_type, selected_symbol, selected_key=selected_key)
        else:
            self._set_catalog_hint()

    def _populate_timeframes(
        self,
        exchange: str,
        market_type: str,
        symbol: str,
        *,
        selected_key: MarketKey | None = None,
    ) -> None:
        options = [
            option
            for option in self._datasets
            if (
                option.market.exchange == exchange
                and option.market.market_type == market_type
                and option.market.symbol == symbol
            )
        ]
        options.sort(key=lambda option: option.market.timeframe.lower())

        self._clear_combo(self._timeframe_combo, "OHLCV / Timeframe")
        selected_timeframe = selected_key[3] if selected_key is not None else None
        selected_idx = 0
        for option in options:
            self._timeframe_combo.addItem(_timeframe_label(option), option)
            idx = self._timeframe_combo.count() - 1
            if not option.loadable:
                self._style_invalid_timeframe_item(idx)
            if option.market.timeframe == selected_timeframe:
                selected_idx = idx
        self._timeframe_combo.setEnabled(bool(options))
        self._timeframe_combo.setCurrentIndex(selected_idx)
        self._apply_selected_timeframe_style()
        self._set_catalog_hint()

    def _clear_combo(self, combo: QComboBox, placeholder: str) -> None:
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(placeholder, None)
        combo.setCurrentIndex(0)
        combo.setEnabled(False)
        combo.blockSignals(False)

    def _set_string_combo_items(
        self,
        combo: QComboBox,
        *,
        placeholder: str,
        values: list[str],
        selected: str | None,
    ) -> None:
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(placeholder, None)
        selected_idx = 0
        for value in values:
            combo.addItem(value, value)
            if value == selected:
                selected_idx = combo.count() - 1
        combo.setEnabled(bool(values))
        combo.setCurrentIndex(selected_idx)
        combo.blockSignals(False)

    def _style_invalid_timeframe_item(self, index: int) -> None:
        font = QFont(self._timeframe_combo.font())
        font.setBold(True)
        self._timeframe_combo.setItemData(index, font, Qt.ItemDataRole.FontRole)
        self._timeframe_combo.setItemData(
            index,
            QBrush(QColor("#b00020")),
            Qt.ItemDataRole.ForegroundRole,
        )

    def _on_exchange_changed(self) -> None:
        if self._updating:
            return
        exchange = _current_string(self._exchange_combo)
        self._updating = True
        try:
            self._clear_combo(self._market_type_combo, "Market Type")
            self._clear_combo(self._symbol_combo, "Asset")
            self._clear_combo(self._timeframe_combo, "OHLCV / Timeframe")
            if exchange:
                self._populate_market_types(exchange)
        finally:
            self._updating = False
        self._emit_current_dataset()

    def _on_market_type_changed(self) -> None:
        if self._updating:
            return
        exchange = _current_string(self._exchange_combo)
        market_type = _current_string(self._market_type_combo)
        self._updating = True
        try:
            self._clear_combo(self._symbol_combo, "Asset")
            self._clear_combo(self._timeframe_combo, "OHLCV / Timeframe")
            if exchange and market_type:
                self._populate_symbols(exchange, market_type)
        finally:
            self._updating = False
        self._emit_current_dataset()

    def _on_symbol_changed(self) -> None:
        if self._updating:
            return
        exchange = _current_string(self._exchange_combo)
        market_type = _current_string(self._market_type_combo)
        symbol = _current_string(self._symbol_combo)
        self._updating = True
        try:
            self._clear_combo(self._timeframe_combo, "OHLCV / Timeframe")
            if exchange and market_type and symbol:
                self._populate_timeframes(exchange, market_type, symbol)
        finally:
            self._updating = False
        self._emit_current_dataset()

    def _discover_datasets(self) -> list[DatasetSelectorOption]:
        self._catalog_error = ""
        list_catalog = getattr(self._core, "list_historical_ohlcv_dataset_loadabilities", None)
        if callable(list_catalog):
            try:
                return _options_from_loadability_reports(list_catalog())
            except Exception as exc:
                self._catalog_error = f"Historical dataset catalog is unavailable: {exc!r}"
                return []

        list_loadable_catalog = getattr(self._core, "list_loadable_historical_ohlcv_datasets", None)
        if callable(list_loadable_catalog):
            try:
                return _options_from_loadability_reports(list_loadable_catalog())
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
                            datasets.append(_option_from_loadability(loadability))
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
        return {
            "dataset_id": _DatasetIdLike(exchange, market_type, symbol, timeframe),
            "loadable": False,
            "validation_status": "unknown",
            "reason": "Core loadability report is unavailable.",
            "csv_path": "",
            "metadata_path": "",
        }

    def _emit_current_dataset(self) -> None:
        if self._updating:
            return
        option = self.current_option()
        self._preview_ohlcv_button.setEnabled(option is not None)
        self._apply_selected_timeframe_style()
        self._set_selection_hint(option)
        self.dataset_changed.emit(option.market if option is not None else None)

    def _apply_selected_timeframe_style(self) -> None:
        option = self.current_option()
        if option is not None and not option.loadable:
            self._timeframe_combo.setStyleSheet(INVALID_SELECTION_STYLE)
        else:
            self._timeframe_combo.setStyleSheet("")

    def _set_catalog_hint(self) -> None:
        total = len(self._datasets)
        loadable = sum(1 for option in self._datasets if option.loadable)
        self._hint_label.setText(
            f"Found {total} OHLCV dataset(s), {loadable} loadable. Root: {self._historical_root}"
        )

    def _set_selection_hint(self, option: DatasetSelectorOption | None) -> None:
        if not self._datasets:
            return
        if option is None:
            self._set_catalog_hint()
            return
        status = _status_label(option.validation_status)
        if option.loadable:
            self._hint_label.setText(
                f"Selected OHLCV: {_dataset_label(option)}. Status: {status}. "
                f"Root: {self._historical_root}"
            )
            return
        reason = option.reason or "This OHLCV dataset is not loadable for Data Manager actions."
        self._hint_label.setText(
            f"Selected OHLCV: {_dataset_label(option)}. Status: {status}. "
            f"Preview only: {reason}"
        )


@dataclass(frozen=True)
class _DatasetIdLike:
    exchange: str
    market_type: str
    symbol: str
    timeframe: str


def _options_from_loadability_reports(reports: Iterable[object]) -> list[DatasetSelectorOption]:
    options: list[DatasetSelectorOption] = []
    for report in reports:
        try:
            options.append(_option_from_loadability(report))
        except ValueError:
            continue
    return _deduplicate_options(options)


def _option_from_loadability(loadability: object) -> DatasetSelectorOption:
    dataset_id = _loadability_dataset_id(loadability)
    if dataset_id is None:
        raise ValueError("loadability report is missing dataset_id")
    market = canonicalize(
        getattr(dataset_id, "exchange", ""),
        getattr(dataset_id, "market_type", ""),
        getattr(dataset_id, "symbol", ""),
        getattr(dataset_id, "timeframe", ""),
    )
    return DatasetSelectorOption(
        market=market,
        loadable=_loadability_is_loadable(loadability),
        validation_status=_loadability_validation_status(loadability),
        reason=_loadability_reason(loadability),
        csv_path=_loadability_csv_path(loadability),
        metadata_path=_loadability_metadata_path(loadability),
    )


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
    return (
        f"{market.exchange} / {market.market_type} / {market.symbol} / "
        f"{market.timeframe} - {_status_label(option.validation_status)}"
    )


def _timeframe_label(option: DatasetSelectorOption) -> str:
    return f"{option.market.timeframe} - {_status_label(option.validation_status)}"


def _status_label(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized == "ok":
        return "OK"
    if normalized == "not_validated":
        return "Not validated"
    if not normalized:
        return "Unknown"
    return normalized.replace("_", " ").title()


def _unique_sorted(values: Iterable[str]) -> list[str]:
    return sorted({str(value) for value in values if str(value).strip()}, key=str.lower)


def _current_string(combo: QComboBox) -> str:
    value = combo.currentData()
    return str(value or "").strip()


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


def _loadability_csv_path(loadability: object) -> str:
    if isinstance(loadability, Mapping):
        value = loadability.get("csv_path")
    else:
        value = getattr(loadability, "csv_path", "")
    return str(value or "").strip()


def _loadability_metadata_path(loadability: object) -> str:
    if isinstance(loadability, Mapping):
        value = loadability.get("metadata_path")
    else:
        value = getattr(loadability, "metadata_path", "")
    return str(value or "").strip()
