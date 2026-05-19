"""Controller-private helpers for Leonardo historical chart sessions.

The public GUI import surface remains ``leonardo.gui.historical_chart_controller``.
This package only splits controller-owned implementation details so the QObject
facade stays small without moving responsibilities to panel, workspace, or
renderers.
"""
