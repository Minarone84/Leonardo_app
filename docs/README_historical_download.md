🧠 Leonardo — Historical Download Subsystem (Updated)

Date: 02/26/2026
Updated: 2026-05-18
Scope: Connection + Historical Data Layer
Status: Functional, stable, integrated with Core runtime and exchange capability ownership

1. Purpose of This Document

This README documents the historical data download subsystem.

It covers:

• Folder structure
• Core orchestration
• Exchange adapter responsibilities
• Pagination model
• Candle integrity rules
• Audit integration
• Runtime integration
• Exchange capability ownership
• Preflight and confirmation flow
• Multi-timeframe task monitoring
• Validation and cancellation behavior
• Current limitations
• Dependency diagram

This document focuses on the connection and historical ingestion layer, now aligned with the Core runtime system.

------------------------------------------------------------
CORE RUNTIME INTEGRATION (PHASE 1)
------------------------------------------------------------

The historical download subsystem operates within the Core runtime layer.

This means:

• all downloads run as background tasks managed by TaskManager
• task lifecycle is tracked in runtime state
• errors are routed through the centralized error system
• all meaningful events emit structured audit entries

Runtime Behavior

When a download is started:

• a background task is created via Core
• the task is tracked in runtime state
• progress and completion are emitted via audit events

The GUI does not manage execution directly.

Instead:

• GUI triggers the request
• Core executes and supervises
• GUI observes via audit

Audit as Communication Layer

Audit events are now part of the global runtime system.

They are:

• structured
• append-only
• decoupled from GUI

Used for:

• progress updates
• completion notifications
• failure reporting

This replaces tight coupling between GUI and downloader state.

Architectural Boundary

The subsystem respects the global separation:

GUI:
• input
• validation
• display

Core:
• execution
• state tracking
• error handling
• audit emission

Current accepted Download Manager baseline

The Historical Download Manager now supports:

• metadata-aware local OHLCV inspection
• Core-owned preflight and range discovery before download
• readable Confirm OHLCV Download plans
• multi-timeframe selection and sequential batch execution
• OHLCV Download Task monitor dialog
• progress, retry, stalled, validation, cancellation, and final recap display
• Stop/Cancel requests routed through Core/TaskManager
• authoritative batch completion payloads

The GUI displays this state. It does not become the execution owner.

Exchange capability ownership rule

Exchange-specific truth belongs to the selected exchange adapter/capability layer.

This includes:

• supported markets
• supported timeframes
• aliases
• API interval mappings
• request limits
• historical range discovery behavior

The GUI must ask CoreBridge/capability callbacks for supported values and display the result. It must not hardcode Bybit market or timeframe truth.

------------------------------------------------------------
2. Historical Storage Architecture
------------------------------------------------------------

Historical data is stored using a partitioned directory model to avoid oversized folders and to support scalable growth.

Folder Structure

data/
└── historical/
  └── {exchange}/
    └── {market_type}/
      └── {symbol}/
        └── {timeframe}/
          ├── ohlcv/
          │ ├── candles.csv
          │ └── candles.meta.json
          ├── indicators/
          │ ├── <instance_key>.csv
          │ └── <instance_key>.meta.json
          ├── oscillators/
          │ ├── <instance_key>.csv
          │ └── <instance_key>.meta.json
          ├── constructs/
          │ ├── <instance_key>.csv
          │ └── <instance_key>.meta.json
          ├── analysis_databases/
          │ └── {database_id}/
          │     ├── manifest.json
          │     └── dataframe.csv
          ├── trade_signal/
          └── signal_elaboration/

Design Rationale

• Prevent flat large directories
• Allow independent timeframe storage
• Prepare for computed artifacts
• Keep raw OHLCV isolated
• Enable deterministic paths

Currently active:

• ohlcv/candles.csv
• ohlcv/candles.meta.json
• derived artifact CSV + .meta.json sidecars for indicators, oscillators, and constructs
• artifact recipe JSON files under `artifact_recipes/`
• ordered artifact recipe collection JSON files under `artifact_recipe_collections/`
• Analysis Database manifests and materialized dataframes

Analysis Database folder lifecycle is owned by the historical data layer. `AnalysisDatabaseStore` owns database pathing, manifest persistence, visible-name validation for draft creation and rename, duplicate visible-name rejection for create/rename, rename/delete operations, and manifest-driven materialization/rebuild. Build/rebuild targets the selected existing `database_id`, preserves the same folder/display name/feature recipe, rewrites `dataframe.csv`, and updates materialization metadata. Explicit add/remove/replace component edits are separate component-editor operations that intentionally change the manifest recipe and reset materialization before a later build. GUI code must not manually rewrite `manifest.json`, move/remove database folders, or add/remove/replace database components during build/rebuild.

Artifact recipe lifecycle is separate from saved artifact value storage. `ArtifactRecipeStore` owns reusable single-recipe JSON files, while `ArtifactRecipeCollectionStore` owns ordered collection JSON files with embedded recipe snapshots and optional dependency/source-database metadata. Recovery services may inspect these files to plan or request regeneration, but CSV artifact writing remains owned by the calculation/persistence path and Analysis Database materialization remains store-owned.

------------------------------------------------------------
3. Core Historical Downloader
------------------------------------------------------------

File:

leonardo/data/historical/downloader.py

Responsibility

The HistoricalDownloader orchestrates:

• input canonicalization
• path resolution from the injected historical root
• exchange paging
• idempotent merge
• atomic persistence
• post-write `HistoricalDatasetService` cache invalidation
• audit emission
• background task execution (via Core runtime)

3.1 Preflight and planning

Before a confirmed download starts, the downloader can build a Core-owned preflight plan.

The plan includes:

• local CSV and metadata state
• local first/last timestamps and row count
• exchange oldest and youngest known timestamps when discoverable
• planned start/end range
• expected bars
• expected pages
• effective page limit
• update-latest vs new-download mode
• whether the dataset is already up to date

The GUI may display this plan, but it must not build or reinterpret the range locally.

3.2 Paging Strategy (Backward Cursor Model)

Historical paging remains Core/data-owned.

The downloader pages backwards using an `end_ms` cursor:

```text
fetch page ending at cursor_end
merge idempotently
write atomically
move cursor_end to oldest_page_timestamp - 1
```

This keeps full-history and update-latest flows deterministic and restart-safe.

3.3 Page-limit resolution

The request limit is resolved by the downloader and clamped through the exchange adapter.

Rules:

• GUI `Limit = 0` means adapter/default limit.
• If the adapter publishes `max_historical_ohlcv_limit(market)`, that value becomes the default for an omitted user limit.
• Explicit user limits are clamped to the adapter maximum.
• If an adapter does not publish a max, the downloader keeps a conservative fallback.

For Bybit, the adapter-owned maximum is `1000`, so default historical pages are 1000 candles and explicit larger user values are still clamped to 1000.

3.4 Infinite Loop Guards

The downloader enforces backwards cursor movement. If a page does not move the cursor backwards, execution fails instead of looping forever.

3.5 Last Candle Handling (Critical Logic)

When no explicit range is supplied, the newest still-forming candle is dropped if the adapter marks it as not closed. This prevents partial candle corruption in canonical historical files.

3.6 Server Time Synchronization

The Bybit adapter owns server-time access and newest/oldest range discovery behavior. Core consumes those adapter capabilities for planning; the GUI does not infer server time or venue history boundaries.

3.7 Validation

After completion, the historical validation layer checks the saved CSV. Validation is neutral and works from canonical timeframe grammar rather than a Bybit-specific allow-list.

Fixed-duration timeframe validation supports canonical minute/hour/day/week units. Month candles are variable-length, so exact fixed-delta validation is not applied to `1M`.

------------------------------------------------------------
4. Exchange Adapter — Bybit
------------------------------------------------------------

Bybit-specific truth lives in the Bybit adapter/capability layer.

The adapter owns:

• app-facing canonical markets: `spot`, `linear`, `inverse`, `options`
• Bybit API market alias mapping, including `options` → `option`
• supported Bybit timeframes
• timeframe aliases such as `60m` → `1h`
• Bybit API interval mapping
• historical kline page limit
• server-time access
• oldest available OHLCV timestamp discovery
• REST and websocket transport details

The data naming layer keeps the neutral app identity. It does not convert app market names into Bybit API categories. The downloader passes canonical identity to the adapter, and the adapter performs the venue-specific conversion.

------------------------------------------------------------
5. CSV Storage Layer
------------------------------------------------------------

OHLCV data remains stored as a clean CSV value artifact:

• `ohlcv/candles.csv`

The canonical OHLCV header remains:

• `ts_ms`, `open`, `high`, `low`, `close`, `volume`

Every standard OHLCV CSV write also creates or updates an adjacent metadata sidecar:

• `ohlcv/candles.meta.json`

The CSV remains the value/data truth. The sidecar is the identity, metadata, lineage, fingerprint, and quality truth.

The sidecar includes:

• `unique_id`
• `artifact_id = ohlcv__candles`
• globally scoped `artifact_uid`
• market identity
• CSV and metadata relative paths
• first/last `ts_ms`
• UTC and `Europe/Rome` display timestamps
• row/column counts and column metadata
• lineage, fingerprint, and timeline-quality metadata

------------------------------------------------------------
6. Naming Layer
------------------------------------------------------------

Market identity remains canonicalized by the data naming layer:

• exchange
• market_type
• symbol
• timeframe

CSV metadata sidecars use the deterministic same-stem policy:

```text
<stem>.csv
<stem>.meta.json
```

Analysis Databases use the folder-backed exception:

```text
analysis_databases/{database_id}/manifest.json
analysis_databases/{database_id}/dataframe.csv
```

The folder name is the immutable `database_id`. User-facing rename updates `display_name` in `manifest.json` without moving the folder. Deleting an Analysis Database removes the whole `analysis_databases/{database_id}/` folder. Build/rebuild materializes the existing saved manifest recipe for that same `database_id`, rewrites `dataframe.csv`, and updates materialization metadata without creating another database or replacing artifact components. Explicit component editing may change `feature_sources` and `feature_columns`, but it is a separate recipe-editing workflow, not rebuild.

Artifact recipe and collection JSON paths are deterministic partition-local records, not data value artifacts:

```text
artifact_recipes/{recipe_id}.json
artifact_recipe_collections/{collection_id}.json
```

Recipe recovery follows strict ownership: the planner inspects, the regenerator delegates recipe execution, and the database rebuilder delegates materialization to `AnalysisDatabaseStore`.

------------------------------------------------------------
7. GUI — Historical Download Window
------------------------------------------------------------
Responsibilities

• collect user input
• validate canonical fields before submission
• display exchange-supported markets and timeframes provided by CoreBridge/capability callbacks
• request Core-owned preflight plans
• show the Confirm OHLCV Download dialog
• submit confirmed single-timeframe or multi-timeframe jobs
• observe audit events
• display progress, validation, cancellation, and final recap state
• request cancellation through CoreBridge

Updated Interaction Model

The GUI:

• asks the active capability surface for supported market/timeframe values
• resolves the active historical root as `Path(ctx.config.runtime.data_dir) / "historical"` and passes it into downloader preflight and execution paths
• submits preflight and confirmed download requests to Core
• does NOT execute downloads
• does NOT own exchange parameters
• does NOT manage async execution directly

Core:

• builds plans
• executes downloads via TaskManager
• tracks task lifecycle
• routes cancellation
• emits audit events

GUI observes via:

CoreBridge.try_get_audit_snapshot()

Async Safety

The task monitor dialog is a display surface. The Stop button requests Core cancellation and then waits for a terminal audit event such as `download cancelled` or `download batch cancelled`.

------------------------------------------------------------
8. Audit Integration
------------------------------------------------------------

All lifecycle events emit structured events:

event_type = "historical_download"

Events include:

• download started
• download plan ready
• download progress
• download retrying
• download stalled
• download completed
• download validated
• download cancelled
• download failed
• download batch started
• download batch item started
• download batch item completed
• download batch progress
• download batch completed
• download batch cancelled
• download batch failed

Audit is now part of the global runtime observability system, not just a local feature.

------------------------------------------------------------
9. Dependency Diagram
------------------------------------------------------------

GUI (HistoricalDownloadWindow)
  │
  ├── capability display requests
  │       └──▶ CoreBridge → exchange adapter/capability surface
  │
  ├── preflight request
  │       └──▶ CoreBridge → HistoricalDownloader.preflight_batch(...)
  │                         └──▶ BybitExchange range/limit capabilities
  │
  ├── confirmed download request
  │       └──▶ CoreBridge → TaskManager (Core Runtime)
  │                         └──▶ HistoricalDownloader
  │                               └──▶ BybitExchange (REST adapter)
  │                                     └──▶ GET /v5/market/kline
  │
  └── cancellation request
            └──▶ CoreBridge → TaskManager cancel task

HistoricalDownloader
  │
  ├──▶ CsvOHLCVStore
  │       ├──▶ {configured historical root}/{...}/ohlcv/candles.csv
  │       └──▶ {configured historical root}/{...}/ohlcv/candles.meta.json
  │
  ├──▶ HistoricalDatasetValidator
  │
  └──▶ ctx.audit.emit(...)
              └──▶ GUI polling via CoreBridge

------------------------------------------------------------
10. Problems Solved
------------------------------------------------------------

The current subsystem solves:

• local metadata inspection before download
• update-latest planning for existing files
• full-history preflight/range discovery for new files
• multi-timeframe sequential batch downloads
• readable user confirmation before execution
• GUI progress without GUI execution ownership
• task monitor final recap and batch validation summary
• Stop/Cancel routing through Core/TaskManager
• Bybit market/timeframe/alias/limit ownership in the adapter
• adapter-default page limits with adapter-max clamping
• dataset-service cache invalidation after OHLCV writes so chart sessions do not reopen stale in-memory candles
• neutral validation for supported fixed timeframe grammar

------------------------------------------------------------
11. Current System State
------------------------------------------------------------

The subsystem now:

• downloads full historical data correctly
• handles pagination deterministically
• avoids partial candle corruption
• stores partitioned CSV datasets
• writes OHLCV metadata sidecars beside canonical candle CSVs
• invalidates any loaded `HistoricalDatasetService` cache for the rewritten dataset
• supports preflight plans and readable confirmation before execution
• supports multi-timeframe batch downloads
• displays task-monitor progress and final recap state
• validates completed datasets and reports validation state in the recap
• routes Stop/Cancel through Core/TaskManager
• resolves default page limit from the adapter when GUI Limit is `0`
• clamps explicit page limits to the adapter maximum
• keeps Bybit market/timeframe/alias/interval/limit truth in the Bybit adapter
• coexists with partition-local artifact recipe and recipe collection records used by Data Manager recovery workflows
• supports Analysis Database manifest-driven build/rebuild and separate explicit component edits
• is async-safe and GUI-safe
• is integrated with Core runtime state and audit
• is extensible to additional exchanges

------------------------------------------------------------
12. Not Yet Implemented / Current Limitations
------------------------------------------------------------

Current known limitations:

• only Bybit has a concrete exchange adapter in the current implementation
• exchange discovery is still effectively single-exchange until a registry/provider layer is introduced
• the GUI may expose a broad numeric limit field, but Core still clamps execution to the selected adapter maximum
• no full multi-exchange connection/rate-limit framework is implemented yet
• websocket/realtime lifecycle remains a separate feed/orchestration concern from historical ingestion

------------------------------------------------------------
13. Architectural Summary
------------------------------------------------------------

This implementation moves Leonardo from:

Prototype that fetches limited candles

to

Deterministic historical ingestion subsystem with integrity guarantees
integrated into a structured runtime system

The foundation for:

• backtesting
• indicator calculation
• simulation engine
• historical chart rendering

is now in place.

🍺 Final verdict

Now this doc:

reflects real execution flow
respects Core runtime ownership
keeps ingestion logic untouched
removes hidden coupling assumptions

And most importantly:
👉 future-you won’t have to guess how downloads actually run anymore
---

## 14. Refactor Baseline — 2026-04-20
The historical download subsystem remains focused on ingestion. The refactor sequence clarified the boundaries around adjacent historical-data access and realtime feed ownership.

### Dataset-service boundary

Historical chart sessions should consume loaded historical datasets through `HistoricalDatasetService` public APIs:

```python
get_timeline_ts_ms(dataset_id)
get_dataset_columns(dataset_id)
get_full_dataframe(dataset_id)
get_slice(request)
list_dataset_exchanges()
list_dataset_market_types(exchange)
list_dataset_symbols(exchange, market_type)
list_dataset_timeframes(exchange, market_type, symbol)
has_dataset(dataset_id)
dataset_exists(dataset_id)
invalidate_dataset_cache(dataset_id)
invalidate_all_dataset_caches()
```

The chart controller should not read private service cache internals.

Historical download completion may invalidate the relevant dataset-service cache, but it must not force chart-layer reload semantics. Active chart refresh behavior remains downstream of the historical chart/controller workflow.

### Connection/feed boundary

Realtime Bybit chart feed orchestration no longer requires Core feed code to import GUI bridge classes. Feed code receives neutral emit callbacks and runtime state ownership remains in Core.

### Unchanged ingestion rules

The downloader still owns:

- historical REST pagination;
- candle integrity checks;
- idempotent merge;
- atomic persistence;
- adjacent OHLCV metadata sidecar writing;
- structured audit emission.

GUI still submits and observes. Core still executes and supervises.
