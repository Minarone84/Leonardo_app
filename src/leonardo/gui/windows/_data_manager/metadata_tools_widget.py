from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGridLayout, QGroupBox, QLabel, QPlainTextEdit, QPushButton, QSizePolicy, QWidget

from leonardo.data.historical.artifact_metadata_backfill import (
    ArtifactMetadataBackfill,
    ArtifactMetadataBackfillItem,
    ArtifactMetadataBackfillReport,
)
from leonardo.data.naming import MarketId
from leonardo.gui.windows._data_manager.button_rack import make_button_rack


class MetadataToolsWidget(QGroupBox):
    """Explicit restore-only metadata maintenance for one selected dataset.

    The widget delegates restore semantics to ArtifactMetadataBackfill. It does
    not scan CSV contents itself, rewrite CSV values, refresh valid sidecars, or
    participate in normal save flows.
    """

    status_message = Signal(str)
    restore_finished = Signal(object)  # ArtifactMetadataBackfillReport

    def __init__(self, *, historical_root: Path, parent: Optional[QWidget] = None) -> None:
        super().__init__("Data Checks / Metadata Tools", parent)
        self._historical_root = Path(historical_root)
        self._market: Optional[MarketId] = None

        root = QGridLayout(self)
        root.setContentsMargins(10, 14, 10, 10)
        root.setSpacing(8)
        root.setColumnStretch(0, 1)
        root.setColumnStretch(1, 0)
        root.setRowStretch(1, 1)

        self._summary = QLabel(
            "Select a dataset to check and restore missing or unreadable CSV metadata sidecars.",
            self,
        )
        self._summary.setWordWrap(True)
        root.addWidget(self._summary, 0, 0)

        self._report = QPlainTextEdit(self)
        self._report.setReadOnly(True)
        self._report.setPlaceholderText("Run metadata restore to see scanned, restored, skipped, and failed counts.")
        self._report.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._increase_report_font()
        root.addWidget(self._report, 1, 0, 1, 2)

        self._restore_button = QPushButton("Check / Restore Missing or Corrupt Metadata", self)
        self._restore_button.setEnabled(False)
        self._restore_button.clicked.connect(self._restore_selected_dataset_metadata)
        root.addLayout(make_button_rack(self._restore_button), 0, 1)

    def _increase_report_font(self) -> None:
        font = self._report.font()
        point_size = font.pointSize()
        if point_size > 0:
            font.setPointSize(point_size + 1)
        else:
            point_size_f = font.pointSizeF()
            if point_size_f > 0:
                font.setPointSizeF(point_size_f + 1.0)
            else:
                font.setPointSize(10)
        self._report.setFont(font)

    def set_market(self, market: Optional[MarketId]) -> None:
        self._market = market
        self._refresh_state()

    def _refresh_state(self) -> None:
        if self._market is None:
            self._summary.setText(
                "Select a dataset to check and restore missing or unreadable CSV metadata sidecars."
            )
            self._restore_button.setEnabled(False)
            self._report.clear()
            return

        self._summary.setText(
            "Selected dataset: "
            f"{self._market.exchange} / {self._market.market_type} / {self._market.symbol} / {self._market.timeframe}\n"
            "This action restores missing or unreadable .meta.json sidecars only. "
            "Valid sidecars are skipped, and CSV values are not rewritten."
        )
        self._restore_button.setEnabled(True)

    def _restore_selected_dataset_metadata(self) -> None:
        market = self._market
        if market is None:
            self.status_message.emit("Select a dataset before running metadata restore")
            return

        self._restore_button.setEnabled(False)
        try:
            report = ArtifactMetadataBackfill(historical_root=self._historical_root).backfill_market(
                market,
                restore_corrupt=True,
            )
        except Exception as exc:
            self._report.setPlainText(f"Metadata restore failed before report creation:\n{exc!r}")
            self.status_message.emit("Metadata restore failed")
            return
        finally:
            self._restore_button.setEnabled(True)

        self._report.setPlainText(self._format_report(report))
        self.restore_finished.emit(report)
        restored = report.created_count + report.restored_corrupt_count
        if report.failed_count:
            self.status_message.emit(
                f"Metadata restore finished with {report.failed_count} failure(s); {restored} sidecar(s) restored"
            )
        else:
            self.status_message.emit(
                f"Metadata restore complete: {restored} sidecar(s) restored; "
                f"{report.skipped_existing_count} valid sidecar(s) skipped"
            )

    def _format_report(self, report: ArtifactMetadataBackfillReport) -> str:
        lines = [
            "Metadata restore report",
            "",
            f"Scanned CSVs: {report.scanned_csv_count}",
            f"Created missing sidecars: {report.created_count}",
            f"Restored unreadable sidecars: {report.restored_corrupt_count}",
            f"Skipped valid sidecars: {report.skipped_existing_count}",
            f"Failed: {report.failed_count}",
            "",
            "Policy: valid metadata was skipped; CSV values were not rewritten.",
        ]

        restored_items = [item for item in report.items if item.status in {"created", "restored_corrupt"}]
        if restored_items:
            lines.extend(["", "Restored sidecars:"])
            lines.extend(self._format_item(item) for item in restored_items)

        failed_items = [item for item in report.items if item.status == "failed"]
        if failed_items:
            lines.extend(["", "Failures:"])
            lines.extend(self._format_item(item) for item in failed_items)

        warnings = report.warnings
        if warnings:
            lines.extend(["", "Warnings:"])
            lines.extend(f"- {warning}" for warning in warnings)

        return "\n".join(lines)

    def _format_item(self, item: ArtifactMetadataBackfillItem) -> str:
        csv_path = self._display_path(item.csv_path)
        metadata_path = self._display_path(item.metadata_path)
        detail = f" — {item.detail}" if item.detail else ""
        return f"- {item.status}: {csv_path} -> {metadata_path}{detail}"

    def _display_path(self, path: Path) -> str:
        candidate = Path(path)
        try:
            return candidate.resolve().relative_to(self._historical_root.resolve()).as_posix()
        except Exception:
            return str(candidate)
