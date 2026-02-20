# Leonardo — Roadmap

Version: v0.1  
Status: Living document (expected to change)  

## Purpose
Leonardo is a Python-first application whose main goal is to act as an advisor for financial trades.  
It is designed to be modular, auditable, and resilient, with a strong emphasis on data correctness, risk controls, and explainable (“white-box”) analytics.

---

## 1) CORE
**Purpose:** Application foundation: lifecycle, configuration, state, reliability.

**Responsibilities:**
- Runtime lifecycle: startup/shutdown hooks, background task coordination
- Global registry / runtime state (high-level): active sessions, running services, open UI contexts
- Configuration + environment management (profiles, feature flags)
- Folder tree checks + bootstrap validation
- Centralized error handling, crash reporting, safe recovery
- Structured logging + audit trail plumbing (what happened, when, why)

---

## 2) ENGINE / ORCHESTRATION
**Purpose:** The “nervous system” coordinating GUI, data, connections, and analytics while enforcing boundaries.

**Responsibilities:**
- Event bus / pub-sub (e.g., `DATA_UPDATED`, `STREAM_STATUS`, `SIGNAL_READY`, `TRADE_PROPOSED`)
- Task scheduling: async jobs, queues, throttling, priorities
- Pipeline execution: data → features → signals → risk checks → outputs
- Dependency boundary enforcement (who can call what)
- Concurrency model: thread/async separation, cancellation, timeouts

---

## 3) GUI
**Purpose:** User interaction and visualization. No trading logic inside.

**Responsibilities:**
- Charting: historical + real-time, overlays, indicators, multi-pane layouts
- Trade workflow views: suggestions, rationale panel, trade management windows
- Dashboards: watchlists, exposure, performance, risk summary, system health
- UX persistence: layouts, preferences, workspaces
- Notifications: alerts, warnings (stale feed, breached limits), toasts

---

## 4) CONNECTION
**Purpose:** External IO: streams + APIs + credentials + resilience.

**Responsibilities:**
- Websocket manager: reconnect/backoff, heartbeats, stale-stream detection
- API clients: data vendors, broker endpoints, auth flows
- Rate limiting, retry policies, circuit breakers
- Credential handling integration (delegated to Security/Policy rules)
- Connection health metrics surfaced to GUI/observability

---

## 5) DATA MANAGEMENT
**Purpose:** Single source of truth for datasets used for plotting and calculations.

**Responsibilities:**
- Storage layer: DB/files, caching strategy, retention rules
- Normalization: symbols, timeframes, timezone alignment, corporate actions
- Retrieval APIs for GUI + analytics (fast, consistent)
- Data quality checks: gaps, duplicates, outliers, stale data detection
- Dataset versioning metadata (enables reproducible backtests/advice)

---

## 6) FINANCIAL TOOLS
**Purpose:** Deterministic analytics toolbox (“white-box” indicators + risk math).

**Responsibilities:**
- Indicators/oscillators + custom indicator framework (explainable components)
- Feature engineering primitives (rolling stats, transforms, normalization)
- Signal primitives (filters, regimes, triggers)
- Risk math (vol, corr, drawdown, stress/scenario utilities)
- Performance analytics (returns, expectancy, risk-adjusted metrics)
- Numerical utilities (optimized paths optionally in C/Cython where justified)

---

## 7) BACKTESTING + SIMULATION
**Purpose:** Research and validation layer to prevent unverified strategies from driving advice.

**Responsibilities:**
- Backtest engine: portfolio simulation, order fill logic
- Transaction costs + slippage models
- Walk-forward testing, time-based splits, leakage checks
- Experiment tracking: parameters, dataset version, results, reproducibility stamp
- Reporting: equity curve, drawdowns, exposures, per-trade analytics

---

## 8) USER POLICY
**Purpose:** Who can do what + guardrails for safe operation.

**Responsibilities:**
- Authentication/session management (local-first, multi-user-ready)
- Authorization/roles (viewer/analyst/admin)
- Risk profiles and constraints (allowed instruments, max exposure/leverage)
- Governance: disclaimers, auditability rules, “advisor not executor” switches
- Privacy rules: what gets stored, retention windows, export/delete policies

---

## 9) SECURITY
**Purpose:** Protect secrets, users, and integrity of decisions.

**Responsibilities:**
- Secrets management: encryption at rest, OS keychain/vault integration
- Credential lifecycle: rotation, token refresh, revocation
- Secure config handling (no credentials in logs, no plaintext dumps)
- Integrity checks: signed config (optional), tamper-evident audit logs (optional)
- Hardening defaults: least privilege, secure storage locations

---

## 10) OBSERVABILITY
**Purpose:** Know what Leonardo is doing (and failing at) with minimal guesswork.

**Responsibilities:**
- Structured logs + correlation IDs (trace a recommendation end-to-end)
- Metrics: feed latency, dropped messages, compute timing, error rates
- Health checks: service status, heartbeat dashboard
- Diagnostics bundle export (debugging without guesswork)
- Alert rules for critical failures (stale data, failed reconnect loops, etc.)

---

## 11) INSTALLER + DEPENDENCIES
**Purpose:** Reproducible installs, reliable updates, easy diagnostics.

**Responsibilities:**
- Packaging/versioning/release pipeline
- Dependency pinning + environment reproduction
- Installers / startup scripts / OS integration
- Update strategy: migrations for DB/config/data
- “Doctor” command: validate system requirements and runtime dependencies

---

## Cross-cutting principles
- **Boundary rule:** GUI ↔ Engine ↔ (Data/Connections/Tools/Backtesting). Avoid shortcut dependencies.
- **Auditability:** every recommendation/trade proposal has a reproducible fingerprint (data version + params + tool versions).
- **Failure-first design:** streams drop, APIs rate-limit, data gaps happen—assume it and codify behavior.
- **Security hygiene:** secrets never touch logs; storage defaults to encrypted where feasible.

---

## V1 Milestones (initial target)
1. **Project skeleton + CORE registry**
   - Standard folder layout, config loading, logging/audit plumbing, folder checks
2. **CONNECTION minimal**
   - One data source, stable websocket/retry policy, basic health indicators
3. **DATA MANAGEMENT minimal**
   - Store/retrieve OHLCV for a small universe, caching, basic quality checks
4. **FINANCIAL TOOLS minimal**
   - A small indicator set + signal primitives, unit tests
5. **BACKTESTING baseline**
   - Simple backtester with costs/slippage placeholders + results report
6. **GUI baseline**
   - Plot historical + basic real-time chart, show a strategy signal + explanation
7. **USER POLICY baseline**
   - Local auth (if needed), permissions stubs, risk profile constraints
8. **OBSERVABILITY baseline**
   - Health dashboard + diagnostics export
9. **Installer baseline**
   - Reproducible environment + “doctor” command

---

## Change log
- v0.1: Initial roadmap with CORE/GUI/CONNECTION/FINANCIAL TOOLS/DATA MANAGEMENT/USER POLICY/INSTALLER plus ENGINE, BACKTESTING, SECURITY, OBSERVABILITY.
