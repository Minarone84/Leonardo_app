# leonardo/core/registry_keys.py

# ---- Services (long-lived objects) ----
SVC_GUI_WINDOW_MANAGER = "services.gui.window_manager"

# ---- Runtime state (facts about "now") ----
RT_WINDOWS = "runtime.gui.windows"              # dict[str, dict] window metadata
RT_REALTIME_ACTIVE = "runtime.realtime.active"  # bool

# (future)
RT_TRADES = "runtime.trades"
RT_CONNECTIONS = "runtime.connections"
RT_SERVICES = "runtime.services"
RT_USER = "runtime.user"
