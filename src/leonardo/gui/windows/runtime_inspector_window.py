from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QMainWindow,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from leonardo.core.context import AppContext
from leonardo.gui.core_bridge import CoreBridge


class RuntimeInspectorWindow(QMainWindow):
    """Display a centralized runtime visibility surface for Leonardo.

    This window is a read-only diagnostic view over the authoritative Core
    runtime state. It does not own lifecycle, orchestration, or state mutation.

    Data sources:
        - StateStore runtime snapshots fetched through the Core loop
        - CoreBridge audit snapshot for recent historical events

    Architectural rules preserved:
        - runtime truth remains in Core / StateStore
        - audit remains historical truth
        - GUI only polls and renders snapshots
    """

    def __init__(self, *, ctx: AppContext, core_bridge: CoreBridge, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._core = core_bridge

        self.setWindowTitle("Leonardo — Runtime Inspector")
        self.resize(980, 640)

        self.statusBar().showMessage("Ready")

        root = QWidget(self)
        self.setCentralWidget(root)

        layout = QVBoxLayout(root)
        layout.setContentsMargins(10, 10, 10, 10)

        self._tabs = QTabWidget(self)
        layout.addWidget(self._tabs)

        self._runtime_table = self._build_table(["Field", "Value"])
        self._connections_table = self._build_table(["Connection", "Kind", "Status", "Last Error"])
        self._tasks_table = self._build_table(["Task", "Status", "Kind", "Details"])
        self._audit_table = self._build_table(["#", "Event Type", "Entity", "Message"])
        self._windows_table = self._build_table(["Name", "Type", "Open"])

        self._tabs.addTab(self._runtime_table, "Runtime")
        self._tabs.addTab(self._connections_table, "Connections")
        self._tabs.addTab(self._tasks_table, "Tasks")
        self._tabs.addTab(self._audit_table, "Audit")
        self._tabs.addTab(self._windows_table, "Windows")

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

        self.refresh()

    def _build_table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers), self)
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setStretchLastSection(True)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.verticalHeader().setVisible(False)
        return table

    def closeEvent(self, event) -> None:
        if self._timer.isActive():
            self._timer.stop()
        super().closeEvent(event)

    def refresh(self) -> None:
        """Fetch runtime snapshots on the Core loop, then render in the GUI."""

        async def _snap() -> Dict[str, Any]:
            state = self._ctx.state
            runtime_app = self._call_state("app_state")
            runtime_session = self._call_state("session_state")
            runtime_connections = self._call_state("connections_state", default={})
            runtime_tasks = self._call_state("tasks_state", default={})
            runtime_windows = self._call_state("windows_state", default={})
            realtime_active = self._call_state("is_realtime_active", default=False)

            return {
                "app": runtime_app,
                "session": runtime_session,
                "connections": runtime_connections,
                "tasks": runtime_tasks,
                "windows": runtime_windows,
                "realtime_active": bool(realtime_active),
            }

        try:
            fut = self._core.submit(_snap())
            snap = fut.result(timeout=0.2)
        except Exception:
            return

        audit = self._core.try_get_audit_snapshot() or {"count": 0, "events": []}

        self._render_runtime(snap)
        self._render_connections(snap.get("connections", {}))
        self._render_tasks(snap.get("tasks", {}))
        self._render_audit(audit)
        self._render_windows(snap.get("windows", {}))

        self.statusBar().showMessage(
            "Runtime visible | "
            f"connections: {self._row_count(snap.get('connections', {}))} | "
            f"tasks: {self._row_count(snap.get('tasks', {}))} | "
            f"windows: {self._row_count(snap.get('windows', {}))} | "
            f"audit events: {len(self._as_list(audit.get('events', [])))}"
        )

    def _call_state(self, name: str, default: Any = None) -> Any:
        method = getattr(self._ctx.state, name, None)
        if callable(method):
            try:
                return method()
            except Exception:
                return default
        return default

    def _render_runtime(self, snap: Dict[str, Any]) -> None:
        app = self._as_mapping(snap.get("app"))
        session = self._as_mapping(snap.get("session"))

        rows = [
            ("app_status", self._pick_value(app, "status", "state", fallback="")),
            ("realtime_active", "YES" if bool(snap.get("realtime_active")) else "NO"),
            ("session_id", self._pick_value(session, "session_id", "id", fallback="")),
            ("session_status", self._pick_value(session, "status", "state", fallback="")),
            ("connections_visible", str(self._row_count(snap.get("connections", {})))),
            ("active_tasks_visible", str(self._row_count(snap.get("tasks", {})))),
            ("tracked_windows_visible", str(self._row_count(snap.get("windows", {})))),
        ]
        rows = [(key, value if value != "" else "-" ) for key, value in rows]
        self._populate_table(self._runtime_table, rows)

    def _render_connections(self, connections: Any) -> None:
        rows_data = []
        for key, meta in self._iter_named_rows(connections):
            data = self._as_mapping(meta)
            rows_data.append(
                (
                    self._pick_value(data, "connection_id", "id", fallback=key or "-"),
                    self._pick_value(data, "kind", "connection_kind", fallback="-"),
                    self._pick_value(data, "status", "state", fallback="-"),
                    self._normalize_scalar(self._pick_value(data, "last_error", fallback="")) or "-",
                )
            )
        self._populate_table(self._connections_table, rows_data)

    def _render_tasks(self, tasks: Any) -> None:
        rows_data = []
        for key, meta in self._iter_named_rows(tasks):
            data = self._as_mapping(meta)
            rows_data.append(
                (
                    self._pick_value(data, "task_id", "id", fallback=key or "-"),
                    self._pick_value(data, "status", "state", fallback="active"),
                    self._pick_value(data, "kind", "task_kind", fallback="-"),
                    self._pick_value(data, "name", "label", "title", fallback="-"),
                )
            )
        self._populate_table(self._tasks_table, rows_data)

    def _render_audit(self, audit: Dict[str, Any]) -> None:
        events = self._as_list(audit.get("events", []))
        tail = events[-100:]
        rows_data = []
        for idx, event in enumerate(reversed(tail), start=1):
            data = self._as_mapping(event)
            rows_data.append(
                (
                    str(idx),
                    self._pick_value(data, "event_type", "type", fallback="-"),
                    self._pick_value(data, "entity_id", "entity", "source", fallback="-"),
                    self._pick_value(data, "message", "detail", "status", fallback="-"),
                )
            )
        self._populate_table(self._audit_table, rows_data)

    def _render_windows(self, windows: Any) -> None:
        rows_data = []
        for _, meta in self._iter_named_rows(windows):
            data = self._as_mapping(meta)
            rows_data.append(
                (
                    self._pick_value(data, "name", fallback="-"),
                    self._pick_value(data, "type", fallback="-"),
                    "YES" if bool(data.get("is_open", False)) else "NO",
                )
            )
        rows_data.sort(key=lambda row: row[0])
        self._populate_table(self._windows_table, rows_data, center_columns={2})

    def _populate_table(
        self,
        table: QTableWidget,
        rows: Iterable[Iterable[Any]],
        *,
        center_columns: Optional[set[int]] = None,
    ) -> None:
        materialized = [tuple(row) for row in rows]
        table.setRowCount(len(materialized))

        for r, row in enumerate(materialized):
            for c, value in enumerate(row):
                item = QTableWidgetItem(self._normalize_scalar(value) or "-")
                if center_columns and c in center_columns:
                    item.setTextAlignment(Qt.AlignCenter)
                table.setItem(r, c, item)

        if len(materialized) == 0:
            table.setRowCount(1)
            for c in range(table.columnCount()):
                item = QTableWidgetItem("-")
                if center_columns and c in center_columns:
                    item.setTextAlignment(Qt.AlignCenter)
                table.setItem(0, c, item)

    def _iter_named_rows(self, value: Any) -> Iterable[tuple[str, Any]]:
        mapping = self._as_mapping(value)
        if mapping:
            return sorted(((str(key), meta) for key, meta in mapping.items()), key=lambda item: item[0])

        values = self._as_list(value)
        return [("", meta) for meta in values]

    def _as_mapping(self, value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        return {}

    def _as_list(self, value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        return []

    def _pick_value(self, data: Dict[str, Any], *keys: str, fallback: str = "") -> str:
        for key in keys:
            if key in data:
                return self._normalize_scalar(data.get(key))
        return fallback

    def _normalize_scalar(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "YES" if value else "NO"
        if isinstance(value, (str, int, float)):
            return str(value)
        if isinstance(value, dict):
            parts = [f"{k}={self._normalize_scalar(v)}" for k, v in value.items()]
            return "; ".join(parts)
        if isinstance(value, (list, tuple, set)):
            parts = [self._normalize_scalar(v) for v in value]
            return ", ".join(part for part in parts if part)
        return repr(value)

    def _row_count(self, value: Any) -> int:
        mapping = self._as_mapping(value)
        if mapping:
            return len(mapping)
        return len(self._as_list(value))


class WindowsInspectorWindow(RuntimeInspectorWindow):
    """Backward-compatible alias for the Phase 5 runtime inspector."""

    pass
