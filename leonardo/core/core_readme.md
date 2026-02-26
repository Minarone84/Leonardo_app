Leonardo CORE Summary (v0.2 – runtime + GUI bridge + exchange scaffolding)
Scope

CORE provides the foundational runtime infrastructure for Leonardo:

Async-first lifecycle orchestration (startup → run → shutdown)

Layered configuration (defaults + TOML config + env overrides)

Structured logging (JSON-friendly) with correlation context

Audit/Event stream (product-facing events) with pluggable sinks

Centralized error routing (exceptions → logs + audit events)

Global registry / AppContext for runtime state, service lookup, and task supervision

New in this iteration (compared to the v0.1 skeleton):

State subsystem (core/state.py) used to record product-facing runtime state (e.g., window open/close, realtime active flag) that the GUI can query/poll.

Registry keys (core/registry_keys.py) defining stable identifiers for services exposed via ctx.registry (e.g., GUI WindowManager).

Market data feed task (core/market_data/bybit_feed.py) that streams chart snapshot/patch events into the GUI via the bridge.

Exchange connection scaffolding (connection/exchange/*) including a registry + adapter layout (Bybit adapter present), designed to support multiple exchanges cleanly.

This layer is explicitly designed to support additional services (websockets, REST APIs, exchange connectors, persistence, GUI bridge) without coupling those services tightly to each other.

Package layout (CORE-related + connected infra that CORE drives)
Core runtime

leonardo/core/app.py — App host, lifecycle orchestration

leonardo/core/config.py — Layered typed config loader

leonardo/core/logging.py — Structured logging + contextvars

leonardo/core/audit.py — Audit event model + sinks

leonardo/core/errors.py — ErrorRouter (central exception routing)

leonardo/core/context.py — AppContext + TaskManager + registry surface

leonardo/core/services/base.py — Service protocol

leonardo/core/services/heartbeat.py — Example service proving lifecycle

Runtime state + registry keys (new)

leonardo/core/state.py — App state surface (GUI-visible state: window tracking, realtime active flag, etc.)

leonardo/core/registry_keys.py — Stable registry keys (e.g., SVC_GUI_WINDOW_MANAGER)

Market data tasks (new)

leonardo/core/market_data/bybit_feed.py — Core-side async chart feed task (snapshot + realtime patches)

Exchange connection scaffolding (new but adjacent)

leonardo/connection/exchange/base.py — exchange interface contracts / base types

leonardo/connection/exchange/registry.py — exchange registry (discover + select adapters)

leonardo/connection/exchange/adapters/bybit.py — Bybit adapter implementation

Note: The connection/ package is not “CORE” strictly speaking, but CORE is what will orchestrate these connectors as services/tasks.

Core lifecycle
Entry point

python -m leonardo runs leonardo/__main__.py

This calls asyncio.run(...) on the app host main coroutine

Boot sequence (app host)

load_config() builds a typed AppConfig

LeonardoApp(config) wires:

structured logging

audit sinks

error router

task manager

app context (registry)

runtime state surface (ctx.state) (new)

await app.run() starts the runtime loop

Startup (LeonardoApp._startup)

Emits lifecycle audit/log events: startup begin, startup complete

Registers services (heartbeat as baseline; GUI services may be registered depending on bootstrap path)

Starts services in registration order:

calls service.start(ctx)

If a service fails to start:

routes error via ErrorRouter as fatal

attempts shutdown

re-raises (startup is considered failed)

Shutdown (LeonardoApp._shutdown)

Emits lifecycle audit/log events: shutdown begin, shutdown complete

Stops services in reverse order:

calls service.stop(ctx)

Cancels supervised tasks via TaskManager.cancel_all(timeout)

Closes audit sinks (flush/close file sink)

Global registry: AppContext (runtime coordination surface)
What it is

AppContext exists to:

provide consistent access to cross-cutting concerns (config/log/audit/errors)

register and access services

centralize task creation/cancellation

expose a small runtime state surface (ctx.state) for GUI/product-visible status (new)

What it is not

It is intentionally not a “god object”. It should not contain:

trading logic

exchange/domain models

GUI state/models (beyond coarse window/state tracking)

analytics state

large mutable business objects

Contents (conceptual)

config: typed config object (AppConfig)

logger: configured logger

audit: audit sink (composite)

error_router: centralized error routing

tasks: TaskManager (supervised background tasks)

registry: service registry (keyed, used by GUI for e.g. window manager)

state: runtime/product state façade (new)

Runtime state surface (core/state.py) — new
Why it exists

Some state is not “logs” and not “services”, but still must be queryable by the GUI:

whether realtime streaming is active

which GUI windows are open (for inspector tooling)

service-like status flags that are useful for operators/users

This state is updated by GUI actions (via CoreBridge submit calls) and read by diagnostic windows (polling snapshots).

Typical responsibilities

window tracking: window_open(...), window_close(...)

realtime flag: set_realtime_active(True/False), is_realtime_active()

snapshot APIs for tooling: windows_state() (used by WindowsInspectorWindow)

Task supervision: TaskManager
Problem it solves

In asyncio apps, “fire-and-forget” tasks are a common failure mode:

tasks crash silently

exceptions become “never retrieved” warnings

shutdown hangs due to orphan tasks

task duplication occurs on reinit

TaskManager centralizes task behavior.

Core behavior

create(name, coro, critical=False, where="task")

refuses to create a second running task with same name

spawns asyncio.create_task

attaches done callback:

ignores CancelledError

routes other exceptions to ErrorRouter.capture(...)

if critical=True, emits a lifecycle:fatal audit event (future policy can escalate to shutdown)

cancel_all(timeout_s)

cancels all non-finished tasks

waits up to timeout_s for them to exit

emits an audit error if tasks remain pending after timeout

Guidance for future services

All background loops (websocket readers, polling loops, schedulers, feeds) should be started using:

ctx.tasks.create("service_name.loop", coro, critical=..., where="service")

…not raw asyncio.create_task, unless there is a very specific reason.

Market data feed tasks (core/market_data/bybit_feed.py) — new

CORE now includes a first “real” async workload: a chart feed task.

Conceptually it:

requests an initial snapshot (historical candles)

streams patch updates (append/update of current candle)

routes updates to the GUI via the bridge signal layer (GUI is responsible for rendering and viewport behavior)

This is intentionally “feed-like” and will later be generalized behind exchange connector interfaces.

Exchange connection scaffolding (connection/exchange/*) — new

A dedicated package exists for exchange integration, structured as:

base.py: common protocols/types for exchanges

registry.py: register and resolve supported exchanges/adapters

adapters/: per-exchange implementations (Bybit present)

This keeps “how to talk to an exchange” separate from:

chart rendering

core orchestration

future strategy/backtesting layers

Configuration: layered + typed (core/config.py)
Layer order (last wins)

Defaults (_defaults_dict())

TOML config file (~/.leonardo/config.toml by default)

Env overrides (LEONARDO__...)

Env override format

Prefix: LEONARDO__

Nested keys split by __

Example: LEONARDO__logging__level=DEBUG

Keys normalized to lowercase (Windows-friendly)

Notes

Config dataclasses are frozen (immutable). Future “modify config” behavior should be done by creating a new config instance and writing it out.

Structured logging (core/logging.py)

stdlib logging configured once at startup

JSON formatter emits one JSON object per log line

Context variables (async-safe):

run_id (unique per run)

component (core, later gui/engine/etc.)

correlation_id (reserved)

Use log(logger, level, msg, **fields) to emit structured payloads.

Audit/event log (core/audit.py)

Audit/events are product-facing and meant for:

GUI display (“what happened?”)

user-facing action history

error feeds

later: traceability/compliance for trading suggestions/actions

Event model:

AuditEvent: ts, event_type, severity, message, fields

Sinks:

InMemoryAuditSink (ring buffer)

JsonlAuditSink (append-only JSONL)

CompositeAuditSink (fan-out, fail-soft)

Centralized error handling (core/errors.py)

ErrorRouter.capture(exc, where=..., fatal=..., **fields):

emits structured log line + traceback

emits audit event:

event_type="error"

severity="fatal" if fatal else "error"

includes where/fatal/metadata

Used by:

service start failures (fatal)

TaskManager callbacks (background task exceptions)

Service contract (core/services/base.py)

A service implements:

name: str

async start(ctx)

async stop(ctx)

Services should:

register tasks through ctx.tasks

emit audit events for lifecycle and notable state transitions

Example service: Heartbeat proves lifecycle wiring.

Optional future: CLI smoke test

We may later add an optional CLI smoke test that spawns python -m leonardo in a subprocess and verifies start/stop behavior. Deferred until CI/boot complexity increases.

##################################################################

DEPENDENCY DIAGRAM CORE

__main__.py
└─ main()
   ├─ asyncio.run(LeonardoApp.run_main())
   └─ handles KeyboardInterrupt
      └─ returns exit code 130


config.py
└─ load_config(config_path=None) ───────────────→ AppConfig
   ├─ _defaults_dict() ─────────────────────────→ base dict (defaults)
   ├─ if config_path is None
   │  └─ config_path = ~/.leonardo/config.toml
   ├─ _load_toml(config_path) ──────────────────→ file dict (or {})
   ├─ _deep_merge(defaults, file_dict) ─────────→ merged dict
   ├─ _apply_env_overrides(merged, "LEONARDO__")
   │  ├─ scans os.environ for keys starting with prefix (case-insensitive)
   │  ├─ splits suffix by "__" into path parts
   │  ├─ normalizes path parts to lowercase (Windows-friendly)
   │  └─ _deep_set(merged, path, parsed_value)
   └─ builds typed dataclasses
      ├─ LoggingConfig(**merged["logging"])
      ├─ AuditConfig(**merged["audit"])
      ├─ RuntimeConfig(**merged["runtime"])
      └─ AppConfig(profile=..., logging=..., audit=..., runtime=...)


logging.py
├─ configure_logging(level, json_mode) ─────────→ logger ("leonardo")
│  ├─ clears root handlers
│  ├─ sets root level
│  ├─ StreamHandler(stdout)
│  └─ sets formatter
│     ├─ JsonFormatter() (json_mode=True)
│     └─ plain text Formatter (json_mode=False)
├─ JsonFormatter.format(record) ────────────────→ JSON line
│  ├─ reads contextvars
│  │  ├─ run_id_var.get()
│  │  ├─ component_var.get()
│  │  └─ correlation_id_var.get()
│  ├─ includes record.exc_info traceback if present
│  └─ includes record.fields if extra={"fields": {...}} is provided
└─ log(logger, level, msg, **fields)
   └─ logger.log(level, msg, extra={"fields": fields})


audit.py
├─ make_event(event_type, severity, message, **fields) ─→ AuditEvent
│  └─ ts = utc_now_iso()
├─ InMemoryAuditSink(max_events)
│  ├─ emit(event)
│  │  ├─ appends event to list (locked)
│  │  └─ trims list to last max_events
│  └─ snapshot() ───────────────────────────────→ list[AuditEvent]
├─ JsonlAuditSink(path)
│  ├─ ensures parent dir exists
│  ├─ emit(event)
│  │  ├─ json.dumps(event.__dict__)
│  │  └─ append line + flush
│  └─ close()
│     └─ flush + close file handle
└─ CompositeAuditSink(*sinks)
   ├─ emit(event)
   │  └─ fan-out to each sink (fail-soft per sink)
   └─ close()
      └─ best-effort close for each sink


errors.py
└─ ErrorRouter(logger, audit_sink)
   └─ capture(exc, where, fatal=False, **fields)
      ├─ log(logger, ERROR, "exception captured", where=..., fatal=..., **fields)
      ├─ logger.exception("traceback", exc_info=exc)
      └─ audit.emit(make_event(
            event_type="error",
            severity="fatal" if fatal else "error",
            message=str(exc),
            where=where,
            fatal=fatal,
            **fields
         ))


registry_keys.py
└─ constants (stable string keys)
   └─ e.g. SVC_GUI_WINDOW_MANAGER  (used by GUI to fetch WindowManager via ctx.registry.get(...))


state.py
└─ AppState (owned by AppContext as ctx.state)
   ├─ window_open(id, title, where=...) ─────────→ records into state store + emits audit/log (policy-dependent)
   ├─ window_close(id, where=...) ───────────────→ updates state store
   ├─ windows_state() ───────────────────────────→ snapshot for WindowsInspectorWindow
   ├─ set_realtime_active(bool, where=...) ──────→ updates realtime flag
   └─ is_realtime_active() ──────────────────────→ bool


context.py
├─ AppContext(config, logger, audit, error_router, tasks, ...)
│  ├─ services: dict[name → service instance]              (existing)
│  ├─ registry: key-value service registry                 (NEW in practice; used by GUI via registry_keys)
│  ├─ state: AppState                                      (NEW: ctx.state used by GUI)
│  ├─ runtime_state: dict[str → Any] (keep small)          (may still exist)
│  ├─ register_service(name, svc)
│  │  └─ stores svc in services dict (raises if duplicate)
│  └─ get_service(name, expected_type) ─────────→ typed service instance
│     └─ runtime isinstance check (raises on mismatch)
└─ TaskManager(error_router, audit, logger)
   ├─ create(name, coro, critical=False, where="task")
   │  ├─ prevents duplicate running task names
   │  ├─ task = asyncio.create_task(coro, name=name)
   │  └─ task.add_done_callback(_done)
   │     ├─ if CancelledError → ignore (normal shutdown)
   │     └─ if Exception e
   │        ├─ asyncio.create_task(error_router.capture(e, where=f"{where}:{name}", fatal=critical))
   │        └─ if critical=True
   │           └─ asyncio.create_task(audit.emit(make_event("lifecycle","fatal","critical task failed", task=name)))
   └─ cancel_all(timeout_s)
      ├─ cancels all pending tasks
      ├─ waits up to timeout_s for completion
      └─ on timeout → audit.emit(make_event("lifecycle","error","shutdown timeout; tasks still pending", pending=N))


services/base.py
└─ Service Protocol (structural interface)
   ├─ name: str
   ├─ async start(ctx: AppContext)
   └─ async stop(ctx: AppContext)


services/heartbeat.py
└─ HeartbeatService(interval_s=1.0)
   ├─ start(ctx)
   │  ├─ sets _running=True
   │  ├─ audit.emit(make_event("service","info","heartbeat starting"))
   │  ├─ log(INFO, "heartbeat service start", interval_s=...)
   │  └─ ctx.tasks.create("heartbeat.loop", self._loop(ctx), critical=False, where="service")
   ├─ stop(ctx)
   │  ├─ sets _running=False
   │  ├─ audit.emit(make_event("service","info","heartbeat stopping"))
   │  └─ log(INFO, "heartbeat service stop")
   └─ _loop(ctx)  [runs as Task: heartbeat.loop]
      ├─ while _running:
      │  ├─ audit.emit(make_event("heartbeat","debug","tick", n=...))
      │  ├─ log(DEBUG, "heartbeat tick", n=...)
      │  └─ await asyncio.sleep(interval_s)
      └─ exits when _running=False or task cancelled by TaskManager.cancel_all()


market_data/bybit_feed.py
└─ run_bybit_chart_feed(bridge, market, symbol, timeframe, limit, testnet=False)
   ├─ fetch initial candles (snapshot)
   │  └─ emits bridge.chart_snapshot(snapshot)
   ├─ realtime loop (append/update patches)
   │  └─ emits bridge.chart_patch(patch)
   └─ cooperates with cancellation (task cancelled by GUI stop or TaskManager shutdown)


connection/exchange/registry.py
└─ ExchangeRegistry
   ├─ register(adapter)
   └─ get(name/market/...) ───────────────→ adapter instance


connection/exchange/base.py
└─ exchange adapter base contracts / common types


connection/exchange/adapters/bybit.py
└─ Bybit adapter implementation
   └─ used by: market_data/bybit_feed.py (directly today or via registry as it evolves)


app.py
└─ LeonardoApp(config: AppConfig)
   ├─ __init__
   │  ├─ sets contextvars: run_id_var, component_var
   │  ├─ logger = configure_logging(config.logging.level, config.logging.json)
   │  ├─ audit sinks
   │  │  ├─ InMemoryAuditSink(max_events=config.audit.memory_max_events)
   │  │  └─ optional JsonlAuditSink(Path(config.audit.file_path))
   │  ├─ audit = CompositeAuditSink(*sinks)
   │  ├─ error_router = ErrorRouter(logger, audit)
   │  ├─ tasks = TaskManager(error_router, audit, logger)
   │  └─ ctx = AppContext(config, logger, audit, error_router, tasks, ...)
   │     └─ ctx.state = AppState(...)                    (NEW)
   │     └─ ctx.registry = ... (keys from registry_keys) (NEW in practice)
   ├─ run_main()  [classmethod]
   │  ├─ config = load_config()
   │  ├─ app = LeonardoApp(config)
   │  └─ await app.run()
   ├─ run()
   │  ├─ await _startup()
   │  ├─ audit.emit("app running") + log("app running")
   │  ├─ while True: await sleep(0.25)
   │  └─ finally: await _shutdown(reason=...)
   ├─ _startup()
   │  ├─ audit/log "startup begin"
   │  ├─ _register_service(HeartbeatService(...))
   │  ├─ for each service in start_order:
   │  │  └─ await service.start(ctx)
   │  ├─ on exception:
   │  │  ├─ await error_router.capture(... fatal=True)
   │  │  ├─ await _shutdown(reason="startup_failure:<svc>")
   │  │  └─ raise
   │  └─ audit/log "startup complete"
   ├─ _shutdown(reason)
   │  ├─ audit/log "shutdown begin"
   │  ├─ stop services in reverse order:
   │  │  └─ await service.stop(ctx) (errors routed fatal=False)
   │  ├─ await tasks.cancel_all(timeout_s=config.runtime.shutdown_timeout_s)
   │  ├─ audit/log "shutdown complete"
   │  └─ await audit.close()
   └─ _register_service(svc)
      ├─ name = svc.name (or class name)
      ├─ ctx.register_service(name, svc)
      └─ start_order.append(name)       