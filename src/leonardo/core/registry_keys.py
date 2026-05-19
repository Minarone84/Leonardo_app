# leonardo/core/registry_keys.py

"""Canonical key names used by the transitional core registry/runtime surface.

This module centralizes the symbolic names that still cross the compatibility
boundary between explicit service lookup and runtime-state storage. During the
phase-3 runtime expansion, these constants continue to reduce ad hoc string
usage while the registry compatibility layer remains constrained to explicit
runtime payload storage and compatibility access.
"""

# ---- Services / capability providers (long-lived objects) ----
SVC_GUI_WINDOW_MANAGER = "services.gui.window_manager"
SVC_HISTORICAL_DATASET = "svc.historical.dataset"  # Historical data read access

# ---- Runtime state (facts about "now") ----
RT_APP = "rt_app"                      # dict application lifecycle snapshot
RT_SERVICES = "rt_services"            # dict[str, dict] service lifecycle map
RT_TASKS = "rt_tasks"                  # dict[str, dict] active task runtime map
RT_WINDOWS = "runtime.gui.windows"     # dict[str, dict] window metadata
RT_REALTIME_ACTIVE = "runtime.realtime.active"  # bool
RT_CONNECTIONS = "runtime.connections"  # dict[str, dict] connection runtime map
RT_SESSION = "runtime.session"          # dict current session runtime snapshot

# ---- Future runtime roots ----
RT_TRADES = "runtime.trades"
