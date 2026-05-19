from __future__ import annotations

from typing import Any, Dict

from PySide6.QtWidgets import QMessageBox


class HistoricalChartPanelMessagesMixin:
    """Panel-owned helper methods extracted from HistoricalChartPanel.

    This mixin has no durable state of its own. It operates on the
    HistoricalChartPanel instance that owns the chart-local study session.
    """

    def _build_save_success_message(self, payload: Dict[str, Any]) -> str:
        params = payload.get("params", {}) or {}
        lines = [
            f"{str(payload.get('tool_type', '')).strip().capitalize()} {payload.get('tool_title', '')} was saved successfully.",
            "",
            f"Exchange: {payload.get('exchange', '')}",
            f"Market type: {payload.get('market_type', '')}",
            f"Asset: {payload.get('symbol', '')}",
            f"Timeframe: {payload.get('timeframe', '')}",
            "",
            "Parameters / metadata:",
        ]

        if params:
            for key in sorted(params.keys()):
                lines.append(f"  - {key}: {params[key]}")
        else:
            lines.append("  - none")

        lines.extend(
            [
                "",
                "Saved to:",
                str(payload.get("saved_path", "")),
            ]
        )
        return "\n".join(lines)

    def _build_save_error_message(self, payload: Dict[str, Any]) -> str:
        params = payload.get("params", {}) or {}
        lines = [
            f"{str(payload.get('tool_type', '')).strip().capitalize()} {payload.get('tool_title', '')} was not saved.",
            "",
            f"Exchange: {payload.get('exchange', '')}",
            f"Market type: {payload.get('market_type', '')}",
            f"Asset: {payload.get('symbol', '')}",
            f"Timeframe: {payload.get('timeframe', '')}",
            "",
            "Parameters / metadata:",
        ]

        if params:
            for key in sorted(params.keys()):
                lines.append(f"  - {key}: {params[key]}")
        else:
            lines.append("  - none")

        saved_path = str(payload.get("saved_path", "")).strip()
        if saved_path:
            lines.extend(
                [
                    "",
                    "Target path:",
                    saved_path,
                ]
            )

        error_text = str(payload.get("error", "")).strip()
        if error_text:
            lines.extend(
                [
                    "",
                    "Reason:",
                    error_text,
                ]
            )

        return "\n".join(lines)

    def _on_financial_tools_save_succeeded(self, payload: dict) -> None:
        QMessageBox.information(
            self,
            "Financial Tool Saved",
            self._build_save_success_message(payload),
        )

    def _on_financial_tools_save_failed(self, payload: dict) -> None:
        QMessageBox.critical(
            self,
            "Financial Tool Save Failed",
            self._build_save_error_message(payload),
        )

