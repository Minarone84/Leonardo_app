Leonardo CORE Summary (v0.1 skeleton)
Scope

CORE provides the foundational runtime infrastructure for Leonardo:

Async-first lifecycle orchestration (startup → run → shutdown)

Layered configuration (defaults + TOML config + env overrides)

Structured logging (JSON-friendly) with correlation context

Audit/Event stream (product-facing events) with pluggable sinks

Centralized error routing (exceptions → logs + audit events)

Global registry / AppContext for runtime state, services, and task supervision

This layer is designed to support future services (websockets, REST APIs, exchange connectors, persistence, GUI bridge) without coupling those services to each other.

Package layout (CORE-related)

leonardo/core/app.py — App host, lifecycle orchestration

leonardo/core/config.py — Layered typed config loader

leonardo/core/logging.py — Structured logging + contextvars

leonardo/core/audit.py — Audit event model + sinks

leonardo/core/errors.py — ErrorRouter (central exception routing)

leonardo/core/context.py — AppContext + TaskManager

leonardo/core/services/base.py — Service protocol

leonardo/core/services/heartbeat.py — Example service proving lifecycle

Core lifecycle
Entry point

python -m leonardo runs leonardo/__main__.py

This calls asyncio.run(LeonardoApp.run_main())

Boot sequence (LeonardoApp.run_main)

load_config() builds a typed AppConfig

LeonardoApp(config) wires:

structured logging

audit sinks

error router

task manager

app context (registry)

await app.run() starts the runtime loop

Startup (LeonardoApp._startup)

Emits lifecycle audit/log events: startup begin, startup complete

Registers services (currently only HeartbeatService)

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

Global registry: AppContext
What it is

AppContext is a runtime coordination surface and registry. It exists to:

provide consistent access to cross-cutting concerns (config/log/audit/errors)

register and access services

centralize task creation/cancellation

keep a small “runtime state” dict for coarse app-level flags

What it is not

It is intentionally not a “god object”. It should not contain:

trading logic

exchange/domain models

GUI state/models

analytics state

large mutable business objects

Contents

config: typed config object (AppConfig)

logger: configured logger

audit: audit sink (composite)

error_router: centralized error routing

tasks: TaskManager (supervised background tasks)

services: dict registry {name: service_instance}

runtime_state: dict for coarse flags (keep small)

Service registry API

register_service(name, svc)
Ensures unique name; raises if already registered.

get_service(name, type)
Fetches a service and asserts its type at runtime.

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

attaches done_callback:

ignores CancelledError

routes other exceptions to ErrorRouter.capture(...)

if critical=True, emits a lifecycle:fatal audit event (policy can later escalate to shutdown)

cancel_all(timeout_s)

cancels all non-finished tasks

waits up to timeout_s for them to exit

emits an audit error if tasks remain pending after timeout

Guidance for future services

All background loops (websocket readers, polling loops, schedulers) should be started using:

ctx.tasks.create("service_name.loop", coro, critical=..., where="service")

…not raw asyncio.create_task, unless there is a very specific reason.

Configuration: layered + typed (core/config.py)
Layer order (last wins)

Defaults (_defaults_dict())

TOML config file (~/.leonardo/config.toml by default)

Env overrides (LEONARDO__...)

Env override format

Prefix: LEONARDO__

Nested keys split by __

Example: LEONARDO__logging__level=DEBUG

Keys are normalized to lowercase to behave consistently on Windows.

Current schema (v0.1)

profile: str

logging.level: str

logging.json: bool

audit.enabled: bool

audit.file_enabled: bool

audit.file_path: str (default ./runs/audit.jsonl)

audit.memory_max_events: int

runtime.shutdown_timeout_s: float

Notes

Config dataclasses are frozen (immutable). Any “modify config” behavior later should be handled by creating a new config instance and writing to a file (future).

Structured logging (core/logging.py)
What we do

stdlib logging configured once at startup

JSON formatter emits one JSON object per log line

Context variables (async-safe correlation)

run_id: unique per run

component: e.g. core (later gui, engine, etc.)

correlation_id: reserved for request/job/user-action correlation later

These are implemented using contextvars, which behaves correctly with asyncio task switching.

Structured fields

Use log(logger, level, msg, **fields) which writes:

msg and metadata into fields payload in JSON output

Audit/event log (core/audit.py)
Why audit exists

Audit/events are product-facing: they are meant for:

GUI display (“what happened?”)

user-facing action history

error feeds

later: compliance/traceability for trading suggestions/actions

This is separate from developer logs.

Event model

AuditEvent fields:

ts (UTC ISO)

event_type (e.g. lifecycle, error, service, heartbeat)

severity (debug/info/warn/error/fatal)

message (human-readable)

fields (structured payload)

Sinks

InMemoryAuditSink (ring buffer)

bounded list of recent events (GUI can snapshot/poll)

JsonlAuditSink

append-only file output (JSON Lines)

CompositeAuditSink

fan-out to multiple sinks, fail-soft per sink

Centralized error handling (core/errors.py)
ErrorRouter responsibilities

ErrorRouter.capture(exc, where=..., fatal=..., **fields):

emits structured log line (exception captured)

logs traceback

emits an audit event:

event_type="error"

severity="fatal" if fatal else "error"

includes where, fatal, and metadata

How it’s used

Service start failures are treated as fatal and abort startup.

Background task exceptions are routed via TaskManager callbacks.

Service contract (core/services/base.py)

A service is any object implementing:

name: str

async start(ctx)

async stop(ctx)

Services are started/stopped by the app host; they should:

register tasks through ctx.tasks

emit audit events for lifecycle and notable state transitions

Example service: Heartbeat

HeartbeatService demonstrates:

service start/stop hooks

task creation via TaskManager

audit + structured logging emission

cooperative shutdown using _running flag + task cancellation by app

It is purely a proof-of-lifecycle and should be replaced/augmented by real services (websocket feeds, exchange connectors, etc.).

Design rules for future services (websockets/API/connectors)

No raw orphan tasks: use ctx.tasks.create(...).

Errors go to ErrorRouter: do not swallow exceptions silently.

Emit audit for lifecycle + major events:

connected/disconnected

authentication success/failure

subscription changes

fatal vs recoverable errors

Keep AppContext lean: register services and small runtime flags only.

Shutdown discipline:

stop() should request graceful stop

app host will enforce cancellation + timeout

Optional future: CLI smoke test

We may later add an optional CLI smoke test that spawns python -m leonardo in a subprocess and verifies start/stop behavior. This is deferred until CI/boot complexity increases.

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


context.py
├─ AppContext(config, logger, audit, error_router, tasks)
│  ├─ services: dict[name → service instance]
│  ├─ runtime_state: dict[str → Any] (keep small)
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
   │  └─ ctx = AppContext(config, logger, audit, error_router, tasks)
   ├─ run_main()  [classmethod]
   │  ├─ config = load_config()
   │  ├─ app = LeonardoApp(config)
   │  └─ await app.run()
   ├─ run()
   │  ├─ await _startup()
   │  ├─ audit.emit("app running") + log("app running")
   │  ├─ while True: await sleep(0.25)  (skeleton “keep alive” loop)
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