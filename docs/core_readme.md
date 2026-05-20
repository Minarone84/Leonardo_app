# Leonardo Core Architecture (Current State)

Version: v3.7  
Date: 2026-05-18

## Overview

The Leonardo Core layer is responsible for:

- data access
- dataset structure
- historical slicing
- financial computation
- artifact persistence
- runtime lifecycle and state management

It is completely independent from the GUI.

The Core is designed to support:

- large historical datasets
- partial data loading through resident slices
- deterministic computation
- reproducible financial-tool outputs
- observable and structured runtime behavior

The Core must never depend on GUI state, chart layout, or renderer behavior.

---

## Core Runtime Layer

The Core includes a runtime management layer responsible for tracking the operational state of the application.

This runtime layer is separate from:

- dataset access
- financial computation
- persistence

It provides a structured and observable runtime surface.

### Runtime state model

Runtime tracks:

- application lifecycle state
- lifecycle-managed services and their lifecycle
- active background tasks
- historical download tasks and cancellation state through TaskManager/audit
- open windows through GUI bridge state
- realtime activation state
- connection runtime state
- session runtime identity

### Connection runtime state

Connection runtime state represents the current operational truth of external feeds and communication channels.

It includes:

- connection identity
- connection kind
- lifecycle status
- last error

Important rules:

- connection lifecycle is tracked at the feed/orchestration level
- adapters remain transport-only
- adapters are not runtime entities
- GUI does not own connection lifecycle

### Runtime truth vs audit truth

Core enforces:

- runtime state = current truth
- audit = historical truth

These must remain separate.

### Single-writer rule

All runtime state mutation is owned by:

`StateStore`

Responsibilities:

- owns runtime state mutation
- guarantees controlled transitions
- emits audit events for meaningful changes

---

## Task Lifecycle Tracking

Background tasks are managed by:

`TaskManager`

Tasks are registered and tracked through lifecycle stages such as:

- started
- completed
- failed
- cancelled

Runtime task state contains only active tasks.

Completed, failed, and cancelled tasks are:

- removed from runtime state
- preserved only in audit history

This prevents runtime state from becoming a historical accumulation layer.

---


## Historical Download Task Boundary

Historical OHLCV downloads are Core-supervised background work.

Ownership chain:

```text
GUI intent
→ CoreBridge
→ TaskManager
→ HistoricalDownloader
→ BaseExchange capability contract
→ concrete exchange adapter
→ CsvOHLCVStore / HistoricalDatasetValidator
→ audit events
```

Core owns:

- preflight/range planning;
- task submission and cancellation routing;
- downloader execution;
- page-limit resolution and adapter-max clamping;
- validation invocation and validation audit emission;
- structured audit event history.

Exchange adapters own venue-specific capability truth, including:

- supported markets;
- supported timeframes;
- market aliases;
- API interval mapping;
- historical request limits;
- oldest available OHLCV timestamp discovery when supported.

The GUI may display capabilities and request work, but it must not own historical execution, exchange-specific values, adapter limits, or cancellation truth.

---

## Application and Service Lifecycle

The Core tracks:

### Application lifecycle

- starting
- running
- stopping
- stopped
- failed

### Lifecycle-managed services

- registered
- starting
- running
- stopping
- stopped
- failed

Lifecycle transitions:

- are reflected in runtime state
- emit structured audit events

### Service registration model

Services are registered explicitly through `AppContext`.

Two categories exist:

#### Lifecycle-managed services

These participate in startup and shutdown and appear in runtime lifecycle tracking.

#### Capability providers

These are long-lived service objects available by lookup but not tracked as lifecycle-managed runtime entities.

Example:

- `HistoricalDatasetService`

### Important rule

Service registration is:

- explicit
- separated from runtime state storage
- not owned by GUI

---

## Registry Compatibility Layer

A legacy registry remains as a compatibility layer.

Constraints:

- service objects must not be stored as ad hoc registry payloads
- service lookup should be explicit through `AppContext`
- registry should not be extended as a general service container

Runtime truth belongs to `StateStore`.  
Service lookup belongs to explicit context ownership.

---

## Core Responsibilities

The Core layer is responsible for:

- loading historical datasets
- managing dataset identity
- slicing large datasets efficiently
- computing financial tools
- persisting derived artifacts
- exposing clean interfaces to controllers

The Core is **not** responsible for:

- rendering
- pane management
- chart layout
- user interaction
- chart-local style
- pane-level visual policy

---

## Dataset Model

Canonical dataset structure:

Historical storage is rooted at `Path(config.runtime.data_dir) / "historical"` for configured Core/GUI flows. With the default runtime data directory, the shape is:

`data/historical/{exchange}/{market_type}/{symbol}/{timeframe}/ohlcv/candles.csv`

Example:

`data/historical/bybit/linear/BTCUSDT/1h/ohlcv/candles.csv`

Each persisted OHLCV CSV now has an adjacent metadata sidecar:

`data/historical/bybit/linear/BTCUSDT/1h/ohlcv/candles.meta.json`

The CSV remains the tabular value truth. The `.meta.json` sidecar carries artifact identity, market identity, file references, timestamp range, shape, column metadata, lineage, fingerprint, and quality metadata.

Analysis databases are folder-backed artifacts stored in:

`data/historical/{exchange}/{market_type}/{symbol}/{timeframe}/analysis_databases/{database_id}/`

with:

- `manifest.json` — analysis-database identity, recipe, user description, source artifacts, selected columns, metadata, and materialization state;
- `dataframe.csv` — materialized analysis-ready dataframe when built.

`database_id` is the folder-backed persistence identity. A user-facing rename changes `display_name` in `manifest.json`; it must not move the folder or recompute `database_id`.

### Dataset identity

A dataset is uniquely defined by:

- exchange
- market_type
- symbol
- timeframe

This identity is used across:

- loading
- slicing
- computation
- persistence

---

## Slice System

Large datasets are not held entirely in chart memory.

Instead, Core provides resident slices.

### Definitions

**Dataset**  
Full canonical dataset on disk.

**Slice**  
Subset of the dataset loaded into memory.

**Viewport**  
Visible global-index region managed by the chart layer.

**Slice payload**  
A returned slice containing:

- request-scoped identity such as `tab_id` and `request_id`
- dataset identity
- resident OHLCV payload (`ts_ms`, `open`, `high`, `low`, `close`, `volume`) or equivalent candle payload
- `base_index`
- `has_more_left`
- `has_more_right`
- resident first/last timestamp metadata

### Core indexing invariant

`global_index = base_index + local_index`

The Core guarantees:

- consistent indexing across slices
- deterministic slice boundaries
- safe navigation at dataset edges

### Slice loading boundary

The controller requests slices based on:

- center timestamp
- chart navigation needs

The Core returns:

- centered resident slice
- metadata for further navigation

The Core does **not**:

- track viewport
- trigger refills
- manage pan/zoom behavior

That remains downstream.

### Slice cache vs request identity

Core may cache reusable slice-body semantics for the same dataset window.

Important rules:

- cache reuse is allowed for dataset-window body data
- request-scoped envelope identity such as `request_id` and `tab_id` must be refreshed per call
- cache hits must not return stale request identity from an older chart request

This keeps slice caching compatible with downstream stale-request protection without moving chart-session ownership into Core.

### Dataset cache invalidation

`HistoricalDatasetService` owns in-memory OHLCV dataset caches and slice caches. When `candles.csv` is rewritten by historical ingestion or a user requests a historical-data refresh, invalidation must happen through explicit Core/data APIs:

```python
invalidate_dataset_cache(dataset_id)
invalidate_all_dataset_caches()
```

Invalidating one dataset removes its loaded column store and any slice-cache entries for that dataset while preserving other datasets. The downloader calls the dataset invalidation boundary after an OHLCV rewrite so later chart opens, timeline reads, full-dataframe reads, and slice requests do not serve stale data.

---

## Financial Tool System

The Core computes financial tools in three families:

- indicators
- oscillators
- constructs

Each tool defines:

- input requirements
- parameters
- computation logic
- runtime outputs

### Computation model

Financial tools operate on normalized dataframe truth derived from canonical OHLCV input plus any explicitly resolved auxiliary columns.

They may produce:

- one output series
- multiple output series
- non-renderable utility outputs
- analysis-only outputs

The Core is multi-output aware.

Examples:

- SMA → one output
- BB → multiple outputs
- HCK → mixed renderable and non-renderable outputs
- constructs → one or many outputs depending on family semantics

The Core does **not**:

- assign panes
- assign chart studies
- manage chart layout
- decide final visual behavior

It returns runtime outputs plus metadata.

### Financial-tool execution context

Financial-tool execution requests now carry explicit execution context.

The current environments are:

- `historical`
- `realtime`

`historical` is the default. The context is supplied by the caller/controller and is validated by the family bridge against tool-contract support before runtime dispatch.

Execution context is not analytical identity. It must not be inserted into tool params, canonical output naming, saved artifact filenames, chart render keys, or study identity. It exists so runtimes that genuinely need environment-aware behavior can branch without moving computation semantics into GUI or renderer layers.

---

## Apply vs Save (Validated Contract)

This is a critical Core contract.

### Apply

Apply is a chart-session operation, but computation may still run on the **full canonical dataset**.

Validated behavior:

- controller may compute against the full dataset
- historical chart apply passes `ToolExecutionContext(environment="historical")`
- resulting runtime outputs are trimmed downstream to the active resident slice before rendering
- apply does not persist artifacts
- apply remains chart-session scoped

### Save

Save is a full-dataset persistence operation.

Validated behavior:

- computation runs on the full canonical dataset
- historical chart save passes `ToolExecutionContext(environment="historical")`
- full-dataset result is persisted unchanged
- save is independent of current viewport or resident slice

### Important distinction

Apply and Save do **not** differ by “slice compute vs full compute”.

They differ by **render scope vs persistence scope**:

- Apply → full compute, historical execution context, resident-local render payload
- Save → full compute, historical execution context, full persisted output

This distinction must remain explicit.

---

## Construct Source Alignment

When constructs consume saved artifacts or auxiliary sources, Core-side/controller-side integration must preserve deterministic alignment.

Valid alignment requires shared keys such as:

- `ts_ms`
- `time`

Equal row count alone is not valid alignment proof.

Positional artifact injection is not considered deterministic-safe alignment.

This rule protects construct reproducibility and prevents silent misalignment.

---

## Full-Dataset Integrity Before Compute

Before computation on full historical data, the active dataframe contract must preserve:

- required OHLCV columns
- numeric OHLCV values or explicit rejection of malformed rows
- monotonic timestamp ordering
- duplicate timestamp rejection
- stable canonical timeline semantics

This is especially important for:

- derivatives
- angle-based constructs
- trap-area accumulation
- window-based transforms
- oscillator warm-up semantics

Computation must remain deterministic and timeline-consistent.

---

## Artifact Persistence

Derived artifacts are stored alongside canonical data.

Typical subfolders include:

- `ohlcv`
- `indicators`
- `oscillators`
- `constructs`
- `artifact_recipes`
- `artifact_recipe_collections`
- `analysis_databases`

Example shape:

`data/historical/{exchange}/{market_type}/{symbol}/{timeframe}/...`

This is the default configured root shape. Callers that run with a non-default `runtime.data_dir` must resolve the same partition layout under that configured data directory.

### CSV-backed artifact contract

For normal CSV-backed artifacts, Leonardo persists a pair:

```text
<stem>.csv
<stem>.meta.json
```

The CSV is the tabular value truth. The `.meta.json` sidecar is the artifact identity, metadata, lineage, and quality truth.

This applies to:

- `ohlcv/candles.csv` → `ohlcv/candles.meta.json`;
- `indicators/<instance_key>.csv` → `indicators/<instance_key>.meta.json`;
- `oscillators/<instance_key>.csv` → `oscillators/<instance_key>.meta.json`;
- `constructs/<instance_key>.csv` → `constructs/<instance_key>.meta.json`.

Analysis Databases are the exception because they are folder-backed artifacts:

```text
analysis_databases/{database_id}/
    manifest.json
    dataframe.csv
```

`manifest.json` is the metadata sidecar equivalent for `dataframe.csv`.

Artifact recipes and recipe collections are JSON-backed recovery/reproducibility artifacts:

```text
artifact_recipes/{recipe_id}.json
artifact_recipe_collections/{collection_id}.json
```

A recipe stores a reproducible full-dataset financial-tool calculation intent. A collection embeds ordered recipe snapshots and optional dependency/source-database metadata so a pack remains reproducible even if individual recipe JSON files are later changed or deleted. These JSON files are not CSV value artifacts and are not `.meta.json` sidecars.

### Analysis Database store semantics

`AnalysisDatabaseStore` owns durable Analysis Database semantics:

- validates user-facing display names, including rejecting empty names, whitespace, and path separators;
- rejects duplicate visible `display_name` values inside the same market/timeframe partition during draft creation and rename;
- preserves immutable `database_id` and folder identity during user-facing rename, build, and rebuild;
- deletes the whole `analysis_databases/{database_id}/` folder for delete operations;
- materializes an existing database from its saved `manifest.json` recipe by writing/replacing `dataframe.csv` and updating materialization metadata;
- preserves `database_id`, folder, display name, feature sources, feature columns, and recipe hash during normal build/rebuild;
- does not run duplicate visible-name validation during materialization/rebuild, because those operations target an existing database identity rather than creating or renaming a database.

`AnalysisDatabaseComponentEditor` owns explicit component-edit orchestration for existing Analysis Databases. It may add, remove, or replace feature components only when called by an explicit component-edit workflow. A component edit changes the saved manifest recipe, resets materialization to draft, removes stale `dataframe.csv` when present, and requires a later build. It must not be confused with rebuild.

GUI code may collect a new database name and checked artifact columns for `Database seed creator`, or one checked database for `Database Builder`, but it must call data-layer APIs for durable mutation. GUI code must not manually rewrite `manifest.json`, move folders, delete database files, materialize dataframes outside the store boundary, or add/remove/replace Analysis Database artifact components during build/rebuild.

### Artifact recipe and recovery orchestration semantics

Artifact recovery is intentionally split into narrow data-layer responsibilities:

- `ArtifactRecipeStore` owns durable single-recipe JSON persistence.
- `ArtifactRecipeCollectionStore` owns durable ordered collection JSON persistence and dependency metadata.
- `ArtifactRecoveryPlanner` owns read-only recovery classification for expected recipe outputs. It inspects CSV/sidecar/source availability and reports recovery status without calculating or writing artifacts.
- `ArtifactRecoveryRegenerator` owns recovery orchestration for planner-actionable recipes only. It delegates execution to `ArtifactRecipeExecutor` and does not calculate directly.
- `ArtifactRecipeExecutor` owns recipe execution order/reporting and delegates full-dataset computation/saves to `ArtifactCalculationService`.
- `ArtifactRecoveryDatabaseRebuilder` gates linked Analysis Database materialization after clean recovery and delegates dataframe rebuilding to `AnalysisDatabaseStore`.

No recovery layer may manually write CSV artifacts, rewrite `.meta.json` sidecars, repair Analysis Database manifests, or duplicate calculation/materialization semantics owned by another layer.

### Artifact identity fields

Every artifact metadata document carries:

- `unique_id` — opaque immutable identifier for the saved artifact object;
- `artifact_id` — deterministic local artifact id inside the market/timeframe partition;
- `artifact_uid` — globally scoped deterministic id including artifact family and market identity.

For example:

```text
ohlcv:bybit:linear:BTCUSDT:30m:ohlcv__candles
oscillator:bybit:linear:BTCUSDT:30m:oscillator__rsi__rsi_default_period_14
```

### Metadata contents

Artifact sidecars include, where applicable:

- market identity (`exchange`, `market_type`, `symbol`, `timeframe`);
- CSV and metadata relative paths;
- first/last `ts_ms`;
- first/last display timestamps in UTC and `Europe/Rome`;
- row count, column count, and column names;
- per-column roles, renderability, and analysis usability;
- tool metadata from `ToolContract`, `ft_naming.py`, and `ft_specs.py`;
- params and bindings with explicit/inferred/unknown status;
- lineage created/updated timestamps;
- file fingerprint metadata;
- timeline quality flags.

### Restore-only metadata backfill

The metadata backfill layer is a maintenance tool used only to restore missing or unreadable `.meta.json` sidecars from existing CSV files. It must not be treated as the normal save path, must not rewrite CSV data, and must not silently refresh valid metadata.

### Persistence rules

Core guarantees:

- deterministic outputs for the same inputs
- stable file structure
- deterministic naming
- reproducible saved artifacts
- adjacent metadata sidecars for newly saved OHLCV and derived CSV artifacts

Core does **not**:

- handle overwrite confirmation
- present dialogs
- own user-facing save decisions

Those remain downstream.

---

## Controller Interaction Boundary

The Core is accessed via controllers such as `HistoricalChartController`.

Controller responsibilities include:

- requesting resident slices
- priming canonical timeline/session truth from Core historical-data surfaces
- obtaining full-dataset dataframe truth for apply/save
- invoking compute
- handling apply vs save
- translating Core output into downstream chart payloads

The Core itself provides:

- dataset metadata
- canonical timeline/dataframe or equivalent historical-data surfaces
- resident slices
- computation
- persistence surfaces

### HistoricalDatasetService boundary rule

For historical chart sessions, `HistoricalDatasetService` is the intended Core-side boundary for:

- dataset metadata
- canonical timeline (`ts_ms`)
- resident slice retrieval
- full-dataset dataframe access or equivalent loaded columns
- dataset catalog listing for GUI selection (`list_dataset_exchanges`, `list_dataset_market_types`, `list_dataset_symbols`, `list_dataset_timeframes`, `list_dataset_ids`)
- dataset existence checks (`has_dataset`, `dataset_exists`)
- dataset-cache invalidation (`invalidate_dataset_cache`, `invalidate_all_dataset_caches`)

Compatibility probing or private service-store reach-through may still exist downstream during transition, but it is not the intended permanent Core → controller contract.

Important rule:

The Core must not know about render surfaces, panes, style state, or chart studies.

---

## Error Handling

The Core reports structured errors for:

- dataset failures
- file failures
- alignment failures
- computation failures
- persistence failures

The GUI decides how to present those errors.

The Core must remain presentation-agnostic.

---

## Architectural Principles

The Core enforces:

- determinism
- reproducibility
- explicit dataset identity
- separation from GUI
- explicit runtime state tracking
- strict separation of runtime state and audit history
- full-dataset compute truth independent from chart rendering
- execution context remains separate from tool params, naming, persistence identity, and renderer behavior
- deterministic source alignment

---

## Key Rules

- Core must never depend on GUI
- Core must not know about panes or rendering
- Core must not manage chart-local state
- computation must be deterministic
- apply and save must remain distinct by scope
- slice indexing must remain consistent
- runtime state must be mutated only through `StateStore`
- audit must reflect meaningful runtime transitions
- service registration must be explicit
- registry must not store service objects as a general pattern
- cached slice body and request-scoped slice identity must remain separate concerns
- dataset cache invalidation must remain Core/data-owned and must not be implemented by GUI filesystem reach-through
- controller-facing historical dataset interfaces should be explicit and public
- historical download page limits must resolve through adapter capability and be clamped to adapter maximum
- exchange-specific market/timeframe/alias/interval/limit truth must stay in the exchange adapter/capability layer
- non-renderable outputs remain valid runtime outputs
- render truth must stay downstream of Core compute truth
- financial-tool execution environment must be caller-supplied context, not hidden naming or renderer state
- CSV-backed persisted artifacts must keep value data in CSV and identity/metadata/lineage in adjacent `.meta.json` sidecars
- artifact recovery planning must remain read-only
- artifact regeneration must delegate execution to `ArtifactRecipeExecutor`
- linked Analysis Database rebuilds must delegate materialization to `AnalysisDatabaseStore`
- Analysis Database build/rebuild must remain manifest-driven and must not add/remove/replace components
- explicit Analysis Database component edits must remain separate from build/rebuild

---

## GUI Visibility Layer (Non-Intrusive)

Recent GUI visibility improvements do not change Core semantics.

The system now provides a complete observability surface:

- Core → authoritative runtime + audit
- GUI → structured visualization of that truth

Important guarantees:

- Core runtime state model remains unchanged
- `StateStore` remains the single source of runtime truth
- audit remains append-only historical truth
- no orchestration or lifecycle logic moved into GUI
- GUI consumes runtime state via CoreBridge and snapshot polling

This improves visibility only. It does not alter Core ownership.

---

## Summary

The Leonardo Core provides:

- scalable dataset access
- efficient slice-based loading
- deterministic financial computation
- structured artifact persistence with CSV + `.meta.json` metadata sidecars
- artifact recipe / collection persistence for reproducible full-dataset calculations
- read-only artifact recovery planning, delegated artifact regeneration, explicit Analysis Database component editing, and store-owned linked Analysis Database rebuilds
- observable runtime lifecycle and state
- explicit distinction between compute truth and render truth
- Core-supervised historical OHLCV download planning, execution, cancellation, validation, and audit emission

It is:

- independent
- reusable
- predictable
- traceable

The Core is the foundation.

If this layer breaks, everything above it becomes expensive nonsense.
---

## Refactor Baseline — 2026-04-20
This baseline records the Core-side changes made during the refactor sequence.

### Core → GUI dependency removal

`core/market_data/bybit_feed.py` must not import GUI classes. The feed boundary uses neutral callbacks:

```python
run_bybit_chart_feed(
    emit_snapshot=...,
    emit_patch=...,
    state=...,
    market=...,
    symbol=...,
    timeframe=...,
)
```

`CoreBridge` may pass Qt signal emitters from the GUI side, but the Core feed must not know that `CoreBridge` exists.

### HistoricalDatasetService public boundary

`HistoricalDatasetService` now exposes the explicit controller-facing APIs:

```python
get_timeline_ts_ms(dataset_id: DatasetId) -> list[int]
get_dataset_columns(dataset_id: DatasetId) -> dict[str, list]
get_full_dataframe(dataset_id: DatasetId) -> pandas.DataFrame
list_dataset_exchanges() -> list[str]
list_dataset_market_types(exchange: str) -> list[str]
list_dataset_symbols(exchange: str, market_type: str) -> list[str]
list_dataset_timeframes(exchange: str, market_type: str, symbol: str) -> list[str]
list_dataset_ids() -> list[DatasetId]
has_dataset(dataset_id: DatasetId) -> bool
dataset_exists(dataset_id: DatasetId) -> bool
invalidate_dataset_cache(dataset_id: DatasetId) -> bool
invalidate_all_dataset_caches() -> int
```

Downstream controller code should call these APIs directly. Private reach-through into service internals such as `_datasets` is not part of the production contract.

### Frozen boundary rules

- Core remains independent from GUI.
- Feed lifecycle is tracked at feed/orchestration level.
- Adapters remain transport-only.
- `StateStore` remains the runtime-state writer.
- Dataset-service APIs expose timeline/full-dataframe truth; viewport, panes, and renderers never access dataset storage directly.
