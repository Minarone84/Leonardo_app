# Leonardo — Historical Chart Architecture (Current State)

Version: v4.6
Date: 2026-05-22

Scope: historical chart sessions, chart-space ownership, viewport/camera behavior, autoscale/manual-y behavior, resident slicing, study projection, pane contracts, and renderer execution.

---

## 1. Purpose

This document defines the current architecture of the Leonardo historical chart stack.

It exists to make one thing explicit:

**historical chart behavior must emerge from a strict ownership chain, not from shared responsibility across layers.**

The historical chart system must support:

- canonical OHLC truth
- large datasets through resident slices
- pan/zoom over a stable chart environment
- workspace-owned price-pane autoscale and manual-y behavior
- chart-local studies and styling
- pane-managed oscillator behavior
- detachable chart sessions
- renderer execution without semantic ownership
- runtime POI/Potential Trade notebook annotations without study ownership

This document is intentionally chart-specific.

It does **not** replace:

- the GUI runtime/system architecture document
- the Financial Tools system design
- the construct naming/behavior policy
- the Core dataset/runtime architecture

Those documents remain authoritative for their own layers.

---

## 2. Architectural Objective

The historical chart stack enforces this ownership chain:

`Core dataset truth → controller/session truth → panel chart-local study truth → workspace pane/layout contracts → pane handoff → renderer execution`

The target is strict separation, not convenience coupling.

That means:

- the dataset is not owned by the viewport
- the viewport is not owned by the renderer
- studies do not own pane layout
- renderers do not own durable visual policy
- panning and zooming do not redefine dataset truth
- style and policy do not trigger recomputation

The chart must behave like a stable environment.
The camera moves across it. The studies live on it. The renderer draws it.

---

## 3. Historical Chart Session Boundary

A historical chart session is represented by `HistoricalChartPanel`.

It is the shell-agnostic chart-session unit used in both:

- embedded historical grid mode
- floating chart-window mode

The panel owns:

- `HistoricalChartController`
- `ChartWorkspaceWidget`
- `ChartStudyRegistry`
- chart-local study lifecycle
- chart-local study style state
- chart-local oscillator visual policy seeding
- chart-local grouped marker-spacing controls for event-style studies such as `peaks_troughs`
- chart-local segmented visual derivation for historical conditional studies such as HCK
- dataset identity for the open chart session

The panel does **not** own:

- Core dataset storage
- persistence semantics
- runtime/service lifecycle
- pane layout policy
- renderer semantics

Dataset discovery before chart creation is not panel or workspace ownership; the selection UI must consume CoreBridge/HistoricalDatasetService catalog surfaces before a chart session is opened.

---

## 4. Layer Responsibilities

| Layer | Owns | Must not own |
|---|---|---|
| Core | dataset access, slice retrieval, compute, persistence, runtime state | viewport, pane layout, renderer behavior |
| HistoricalChartController | chart-session data truth, canonical timeline, resident slice truth, full-study truth, resident-local study projection | pane layout, renderer grouping, chart-local style semantics |
| HistoricalChartPanel | chart-local study lifecycle, chart-local study identity, chart-local style persistence, chart-local oscillator policy seeding, chart-local segmented visual derivation for historical conditional studies | full dataset truth, slice retrieval policy, pane ownership |
| ChartWorkspaceWidget | pane lifecycle, pane ordering, pane contracts, study-to-pane mapping, explicit payload push into panes, price-pane autoscale/manual-y contract, chart-space domain policy | full-study truth, computation, semantic rendering |
| PricePane / OscillatorPane / VolumePane | narrow handoff boundary into render surfaces | durable state ownership, pane grouping policy |
| Render surfaces | draw resident-local payloads and apply immediate gesture write-back where allowed | compute, pane discovery, semantic defaults, durable chart truth |

---

## 5. Canonical Historical Truth Model

The historical chart pipeline uses two different but connected truths:

### 5.1 Dataset truth

Canonical dataset truth is the full historical dataset represented by:

- dataset identity
- Core-backed dataset catalog/existence surfaces used before chart opening
- canonical timeline
- full OHLCV dataframe
- full financial-tool outputs

This truth remains upstream of rendering.

### 5.2 Resident truth

The GUI does **not** render the full dataset directly.
It renders a resident slice.

Controller/session truth therefore includes:

- canonical dataset identity
- canonical timeline (`ts_ms` ordered, strictly increasing)
- full cached dataframe for apply/save operations
- resident slice base index
- resident candle payload
- left/right availability flags
- full-dataset study truth
- resident-local projected study payloads
- non-renderable analysis-usable full-dataset outputs retained as temporary construct-source truth

This is the historical chart-session truth.

---

## 6. Chart Space vs Dataset Space

The historical chart uses a fixed chart-space domain.
This is critical.

### 6.1 Dataset space

Dataset space is the canonical candle index range:

`0 .. dataset_count - 1`

Only those indices correspond to real candles.

### 6.2 Chart space

Chart space is the environment over which the viewport camera moves.

For historical sessions, workspace defines a fixed padded chart domain:

- left domain padding: `1000`
- right domain padding: `1000`

So the historical chart environment is:

`[-1000, dataset_count + 1000)`

Important meaning:

- padded slots are legal camera space
- padded slots are **not** dataset truth
- padded slots must not cause the viewport to redefine candle ownership
- padded slots are display/navigation affordances only

### 6.3 Why this exists

This prevents the chart from collapsing into a moving right-edge policy where panning or zoom behavior silently changes the environment itself.

The dataset remains the same.
The chart environment remains the same.
Only the camera changes.

---

## 7. Global Indices vs Resident-Local Arrays

Historical navigation and rendering intentionally use different coordinate scopes.

### Global / chart-space coordinates

The viewport uses global x-axis coordinates over chart space.

Those coordinates may point to:

- real dataset candles
- left padded space
- right padded space

### Resident-local arrays

Render surfaces consume only resident-local arrays.

That means:

- candles stored in `ChartModel` are the current resident slice only
- overlay and oscillator render values pushed into the chart are resident-local only
- renderers do not reinterpret full-dataset indexing on their own

### Alignment bridge

`resident_base_index` maps resident-local arrays back onto the chart-session x-axis.

This is a visualization alignment helper only.
It is not a second ownership layer.

---

## 8. ChartViewport Contract

`ChartViewport` owns the shared horizontal camera.

It does **not** own:

- dataset truth
- refill policy
- resident-slice ownership
- pane layout
- render semantics

### 8.1 Viewport responsibilities

The viewport owns:

- current visible horizontal window
- min/max visible bars
- current crosshair index
- domain clamping over fixed chart space
- horizontal zoom behavior inside the supplied chart-space domain
- x-index ↔ pixel mapping
- a pan-only notification path for explicit user horizontal pan gestures

### 8.2 Fixed-domain behavior

The viewport camera moves over the chart-space domain supplied by workspace.

For historical charts that means:

- negative starts are legal
- right padded starts are legal
- chart-space padding is explicit
- camera boundaries are stable while the session is open

### 8.3 Autoscale / zoom rule

User-facing Autoscale belongs to the workspace-owned price-pane vertical fit contract, not to viewport ownership.

The viewport may still expose legacy compatibility entry points that use older "anchor zoom" naming, but that naming is not the architectural source of autoscale semantics.

Horizontal zoom must never:

- redefine domain padding
- redefine chart-space boundaries
- reintroduce a synthetic right-edge ownership path
- change who owns resident truth

### 8.4 Initial load rule

On initial historical load, the viewport may align the latest real candle to the right data edge.

That is an initial camera placement rule.
It is **not** a permanent rule saying the chart must always be forced back to the youngest bar.

---

## 9. HistoricalChartController Contract

`HistoricalChartController` is the compute/render boundary and the owner of historical chart-session data truth.

### 9.1 Controller owns

- dataset open flow
- GUI-thread marshalling of asynchronous dataset-open and slice results
- stale dataset-open generation/request guards
- canonical timeline priming
- resident slice requests
- resident slice application
- full-dataset financial-tool computation
- full-study truth storage
- resident-local study projection
- renderable filtering
- apply vs save distinction
- refill policy

### 9.2 Controller does not own

- pane creation/removal
- oscillator pane layout
- chart-local style persistence
- renderer grouping
- pane view state

### 9.3 Compute/render boundary

Computation may run on the full canonical dataset.
Rendering must receive resident-local outputs only.

That means:

- full-study truth remains controller-owned
- render payloads are trimmed/projected before entering the chart layer
- non-renderable outputs must never become chart series
- non-renderable `analysis_usable` outputs may remain full-dataset source truth for later construct chaining
- chart-renderable payloads with no renderable outputs must fail unless `accepts_empty_render_output=True`


### 9.3.1 UTC dependency preparation

`universal_trend_classifier` is computed on the full historical dataframe, but it depends on confirmed Peaks & Troughs event columns. For historical apply/save, the controller must resolve these dependencies before runtime dispatch:

- derive the directional trend pair from UTC params: `peak_fractal_{trend_fractal_window}` and `trough_fractal_{trend_fractal_window}`, with legacy `fractal_window` as the directional fallback;
- derive the horizontal range pair from UTC params: `peak_fractal_{range_fractal_window}` and `trough_fractal_{range_fractal_window}`;
- honor advanced explicit overrides only for their own purpose (`trend_peak_column` / `trend_trough_column`, `range_peak_column` / `range_trough_column`);
- load the saved `peaks_troughs` artifact for the same market partition;
- merge all unique required columns by `ts_ms` or `time` only;
- reject missing artifacts, missing columns, duplicate join keys, or unsafe alignment.

Trend and range dependency intents are separate even when they are satisfied from the same saved artifact. The controller may load the saved artifact once and deduplicate columns as an optimization, but it must not collapse the analytical intent back into a single `fractal_window` dependency.

This dependency preparation does not change the compute/render contract. Full UTC output remains controller-owned full-study truth, and resident-local projection remains the only payload sent downstream. The renderer remains execution-only. Historical UTC range replay is sequential: bars are processed in order and confirmed range swings are fed only at their knowable confirmation bar so active ranges can continue/break through later bars in the same way a future realtime path would. Invalid OHLC/source rows remain hard continuity breaks: historical UTC must split directional trend detection by contiguous valid-data segments so uptrend/downtrend intervals never bridge NaN or malformed candle/source gaps.

Saved dependency lookup uses the active historical storage root derived from runtime config, `Path(ctx.config.runtime.data_dir) / "historical"`, rather than the default root fallback.

### 9.4 Refill ownership

Viewport movement is only an input signal.
The controller alone decides whether refill is needed.

The controller compares:

- current camera interest window
- current resident coverage window
- left/right availability flags

and decides whether a new slice request is required.

### 9.5 Padded-camera normalization

Because the viewport can move into padded chart space, the controller must normalize the current camera back into a dataset-interest window.

Rules:

- overlapping regions are clipped into canonical dataset coordinates
- camera fully inside left padding maps to the first edge-adjacent dataset window
- camera fully inside right padding maps to the latest edge-adjacent dataset window

This keeps refill policy grounded in real data without letting the viewport redefine dataset truth.

### 9.6 Stale-slice guard

A returned slice may only become resident truth if it still covers the current camera-interest window.

If the user moved meanwhile and the returned payload is stale:

- the controller discards that payload
- resident truth is not overwritten by stale coverage
- refill policy is re-evaluated against the current camera

This prevents the historical chart from “vanishing” after pan/zoom races.

Dataset-open callbacks use the same stale-result principle: a late result from an older open request must not mutate the currently active chart session.

### 9.7 Current historical resident policy

Current controller policy for historical charts:

- default visible bars: `500`
- max visible bars: `2000`
- resident target bars: `5000`
- refill threshold: `250`

The larger resident target is an optimization to reduce how often horizontal navigation triggers a full resident refresh and study reprojection cycle.

### 9.8 Dataset cache invalidation boundary

The Core dataset service may cache loaded OHLCV columns and slice bodies, but cache invalidation is Core/data-owned. The GUI may request invalidation through CoreBridge, and the downloader may invalidate after rewriting `candles.csv`, but chart layers must not clear private service internals or reload files directly.

---

## 10. ChartModel Contract

`ChartModel` is the GUI-side container for the currently resident chart payload.

### 10.1 Canonical model rules

- OHLC is the canonical base chart layer
- volume is an auxiliary base layer
- overlays and oscillators are derived render state
- trades are auxiliary annotations

Studies do not replace the OHLC layer.
They sit on top of it.

### 10.2 In-place mutation rule

Base OHLC and base volume lists are mutated in place.

This keeps bound render surfaces attached to the same base payload references instead of treating list rebinding as a shadow ownership path.

### 10.3 Resident alignment rule

`resident_base_index` maps resident-local positions into the chart-session x-axis.

It is:

- chart-local
- alignment-only
- not a dataset owner

### 10.4 Change batching rule

The model supports batched changed-signal emission.

This exists so a resident-slice update or multi-study reapply can become one coherent refresh instead of a repaint storm.

---

## 11. HistoricalChartPanel Contract

The panel owns chart-local study truth, not compute truth.

### 11.1 Panel responsibilities

The panel owns:

- chart-local study registry
- chart-local study lifecycle
- chart-local study identity
- chart-local style persistence
- default-style persistence into study state
- style-module ownership
- oscillator visual policy seeding
- translation from controller projections into chart-local study ids
- chart-local render-key namespacing for duplicate same-config studies

### 11.2 Duplicate-study rule

Controller projection identity and panel chart-local study identity are different.

One controller projection may legitimately fan out to multiple chart-local study instances when the same study configuration is applied more than once.

The panel preserves that distinction by:

- translating controller projections back onto chart-local study ids
- resolving final chart-local style per study instance
- namespacing renderer-facing render keys per study instance before workspace reapply

### 11.3 Slice-refresh rule

When a new historical slice is applied:

1. controller applies new resident candles first
2. panel pulls the controller’s current projected study payloads
3. panel resolves the final chart-local render state once
4. panel hands the final resident-local styled payloads to workspace
5. workspace reapplies them without recomputation

The panel must not do a second redundant style-reapply pass after that.

### 11.4 Style rule

Style changes are visual-only.
They must not trigger recomputation.

The panel reuses already rendered/projected data and rebuilds only chart-local visual payload.

For historical conditional studies such as HCK, that visual payload may be a segmented renderer-facing expansion of the logical study outputs. That segmented derivation remains panel/resolver-owned and must not be moved into workspace or renderer ownership.

---

### 11.5 Notebook Runtime Annotation Boundary

Historical Notebook POI and Potential Trade markers are chart annotations, not studies.

Durable notebook truth lives in `HistoricalNotebookStore`. A Workspace Snapshot may reference that notebook through `notebook_ref`, but it must not embed notebook content in the snapshot payload.

When notebook overlays are enabled, `HistoricalDataManagerWindow` derives runtime marker payloads from notebook POI rows and eligible Potential Trades rows, then sends them to matching active `HistoricalChartPanel` instances through narrow notebook-marker APIs. The chart layer receives already-derived annotation payloads.

Notebook POI and Potential Trade markers must not:

- enter `ChartStudyRegistry`;
- create `ChartStudyInstance` objects;
- become financial-tool outputs;
- alter controller full-study truth;
- be saved as Study Setup content;
- redefine pane/layout ownership.

Potential Trade markers are derived only from rows with explicit `Long` or `Short` direction. Long markers render as green upward arrows below the bar; Short markers render as red downward arrows above the bar. POI/PT marker offsets are notebook annotation settings, not study style and not renderer semantic ownership.

Renderer participation remains execution-only: it draws the explicit marker payload it is given and must not infer notebook semantics or own notebook persistence.

---

## 12. ChartWorkspaceWidget Contract

`ChartWorkspaceWidget` owns pane/layout behavior and chart-space policy.

### 12.1 Workspace owns

- `ChartModel`
- `ChartViewport`
- shared `Crosshair`
- pane stack
- pane registry and ordering
- study-to-pane mapping
- managed overlay grouping
- pane view state
- pane-local visual policy state
- explicit render payload push into panes
- fixed historical domain padding
- price-pane autoscale/manual-y contract
- viewport-dependent pane contract refresh

### 12.2 Workspace does not own

- full-dataset truth
- compute semantics
- saved artifact semantics
- study naming rules
- renderer-side semantic interpretation

### 12.3 Historical domain policy

Historical chart-space padding is set by workspace, not by viewport anchor logic and not by renderers.

Current workspace historical policy:

- left pad: `1000`
- right pad: `1000`

Realtime/snapshot flows use zero domain padding unless a dedicated realtime policy says otherwise.


### 12.4 Compact workspace layout policy

The historical workspace may reduce visual margins, grid spacing, splitter handle width, and renderer plot padding to maximize room for actual chart data. This is a presentation/layout concern and must not redefine chart-space domain behavior.

Current compact-layout rules:

- inter-pane and embedded-grid spacing should stay compact;
- pane separation should be provided by subtle pane/splitter borders rather than large gaps;
- price, volume, and oscillator surfaces may reduce internal plot padding as long as right-axis labels and time labels remain readable;
- view-mode UI belongs to the historical workspace/window shell, not to chart-session compute/render ownership;
- `Scroll 4` / `Fit 8` remain shell visualization modes and must preserve chart-session identity.

The fixed historical domain padding remains `1000 / 1000`. That padding is chart-space/navigation behavior and must not be treated as cosmetic whitespace.

### 12.5 Pane contract ownership

Workspace owns durable pane view state and explicit pane contracts.

Examples:

- price-pane y-range / autoscale contract
- oscillator pane y-range contract
- overlay projection payload
- oscillator pane visual policy payload
- pane-local gesture write-back target mapping

### 12.6 Price-pane vertical contract

User-facing Autoscale is a workspace-owned price-pane vertical-fit contract.

Rules:

- Autoscale ON resolves the current price-pane y-range from the visible x-window
- that y-range must include visible OHLC and visible, renderable price-pane overlays
- marker-style overlays must reserve enough visual headroom for marker size and marker offset, not only the raw anchor price
- hidden overlays must not influence autoscale
- horizontal pan and horizontal zoom remain allowed
- manual vertical pan/zoom are suppressed while Autoscale owns the range
- Autoscale OFF hands the price-pane y-range back to user-owned manual control
- re-enabling Autoscale immediately recomputes the y-range from the current visible x-window

### 12.7 Batched reapply rule

Workspace must reapply resident-slice/projected-study updates as a batch.

That means:

- model changes are grouped
- pane refreshes are deferred until the batch ends
- labels, pane contracts, sizes, and price refresh are flushed coherently
- workspace does not perform per-study full refresh churn when one coherent batch is enough

This is the key performance contract for historical navigation with multiple studies.

---

## 13. Pane Contract

Panes are handoff boundaries.
They are not second durable state owners.

### 13.1 PricePane

PricePane receives:

- shared viewport
- shared crosshair
- explicit resident OHLC slice
- explicit price-pane view state including the workspace-owned y-range / autoscale contract
- explicit overlay series payload
- explicit overlay fill payload
- explicit managed overlay-row projection for the overlay card

It must not discover study grouping by peeking into workspace internals.

### 13.2 OscillatorPane

Each managed oscillator study owns one pane in the current phase.

The pane receives:

- shared viewport
- shared crosshair
- explicit resident-local series list
- pane-owned visual policy
- shared pane view state
- resident base index alignment

### 13.3 Shared view-state rule

Pane view-state mappings are preserved as shared mutable mappings owned upstream by workspace.

Renderers may write immediate gesture keys into that same mapping, but panes must not fork a pane-local copy.

---

## 14. Renderer Contract

Renderers are execution surfaces only.

Renderers may expose public cache invalidation methods for static-scene repaint correctness, but callers must enter through workspace/pane contracts. The panel must not mutate renderer private cache fields.

Render surfaces consume explicit pane-owned contracts and repaint only from those handoffs and crosshair changes. They must not subscribe directly to viewport camera signals or act as secondary refresh coordinators.

### 14.1 Renderers must consume

- resident-local candles or series values
- explicit pane-owned y-range or pane policy
- explicit overlay/fill payloads
- shared viewport/crosshair camera state
- pane-owned gesture write-back mapping where allowed

### 14.2 Renderers must not own

- full-study truth
- pane membership discovery
- semantic defaults
- full-dataset indexing repair
- synthetic vertical fallback truth
- chart-space padding policy

### 14.3 Vertical contract rule

Price and oscillator vertical interpretation is owned upstream.

Renderers may apply immediate drag/zoom write-back into pane-owned state, but they must not invent durable vertical truth when an explicit pane-owned y-range contract is missing.

### 14.4 Gap honesty rule

Renderers must keep invalid regions visually honest.
They must not bridge NaN gaps or warm-up gaps with fabricated continuity.

For historical segmented conditional studies such as HCK:

- segmented bullish/bearish payloads must be derived upstream of the renderer
- crossover continuity must be achieved by explicit payload construction upstream
- the renderer must execute that explicit segmented payload only
- the renderer must not infer fast-vs-slow semantics or invent crossover ownership on its own

---

## 15. Historical Study Pipeline

### 15.1 Apply

Financial-tool apply works like this:

`full dataset compute → controller renderable filtering → controller resident-local projection → panel chart-local identity/style resolution → workspace pane application → renderer draw`

Important rules:

- compute may be full-dataset
- render payload is resident-local only
- non-renderable outputs stay out of the chart
- style remains downstream of computation
- when a study requires historical segmented conditional rendering, that segmented renderer-facing payload is resolved upstream before workspace/pane handoff

### 15.2 Resident-slice refresh

When the historical resident window changes:

- controller rebuilds resident-local projections from stored full-study truth
- panel maps those projections onto chart-local study ids and resolves final chart-local styled payloads once
- workspace reapplies those payloads as one batch
- renderers draw the new resident-local payload

No recomputation is required just because the resident window moved.

### 15.3 Save

Save remains a full-dataset persistence operation and is independent from the current resident window.

Historical chart save paths use the active configured historical root, and chart-opened `FinancialToolsManagerWindow` instances receive that root from the panel.

---

## 16. Historical Pan and Zoom Behavior

Historical pan/zoom follows these rules:

### 16.1 Pan

Pan moves the shared horizontal camera across fixed chart space.
It does not:

- alter dataset truth
- truncate candles
- mutate study ownership
- redefine chart-space boundaries

### 16.2 Horizontal zoom

Horizontal zoom changes the visible window size.
It does not:

- change who owns the chart domain
- change resident-study truth
- promote the viewport into a data owner

### 16.3 Autoscale ON

When Autoscale is ON:

- workspace owns the price-pane vertical range
- the current visible x-window must keep all visible price-pane OHLC and visible, renderable overlays vertically in frame
- marker-style overlays such as `peaks_troughs` must remain visually in frame even when their rendered triangle position is offset above/below the anchor price
- manual vertical pan/zoom are suppressed because workspace is actively resolving the y-range
- horizontal pan and horizontal zoom remain allowed

### 16.4 Autoscale OFF

When Autoscale is OFF:

- manual y-range becomes user-owned
- manual vertical pan/zoom are allowed
- horizontal pan and horizontal zoom remain allowed
- re-enabling Autoscale immediately recomputes the price-pane y-range from the current visible x-window

### 16.5 Studies on chart space

Studies are projected onto the same chart-session x-axis as OHLC truth.
They live **on** chart space.
They do not redefine chart space.

### 16.6 Refill

Refill is controller-owned.
The viewport never requests its own resident truth directly.

### 16.7 Pan Anchor

Pan Anchor is a Historical Data Manager shell-level coordination mode, not a viewport ownership change.

When Pan Anchor is enabled, a user horizontal pan in one active historical chart causes the other eligible charts in the same Historical Data Manager to recenter around the source chart's current center timestamp.

Rules:

- Pan Anchor is off by default;
- synchronization is horizontal-only;
- synchronization is triggered by explicit user horizontal pan gestures, not generic viewport changes;
- synchronization is timestamp-center based, not raw pixel-delta or raw bar-index based;
- target charts keep their own visible width, zoom, autoscale/manual-y state, and vertical range;
- embedded charts and detached charts still tracked by the same Historical Data Manager are eligible;
- charts in other Historical Data Manager windows are not targeted;
- programmatic timestamp navigation, notebook Go actions, Potential Trade/POI Go actions, initial chart load, and Workspace Snapshot restore must not become pan-sync sources;
- Historical Data Manager owns reentry protection so programmatic target recentering does not create sync loops;
- target recentering must use the existing panel/controller timestamp-centering path, with the controller preserving nearest-timestamp lookup, resident refill, and stale-slice protection.

---

## 17. Historical Rendering Performance Rules

The historical chart must treat panning as primarily a camera operation over already resident truth.

Current performance rules are:

- keep a larger resident window (`5000` bars target)
- batch model change emission
- batch workspace multi-study application
- avoid synchronous repaint forcing in workspace refresh paths
- avoid pane-level second ownership of refresh orchestration
- resolve final styled projected payload once per slice refresh
- keep initial apply on the same final-styled single-handoff path where possible
- let renderers repaint from explicit resident-local payloads

The intent is not “never refresh.”
The intent is:

- do not recompute when only camera movement happened
- do not restyle the same resident payload twice for one slice change
- do not fan one coherent resident update into many visible redraw passes

---

## 18. Historical vs Realtime Distinction

The historical chart engine and the realtime chart engine share major pieces, but the ownership contract is not identical.

### Historical

- fixed padded chart-space domain
- resident slicing is active
- controller owns refill policy
- controller stores full-study truth and resident projections

### Realtime

- chart grows from appended live candles
- zero padding by default
- GUI must not smuggle retention policy into the viewport/model path
- append/update behavior must preserve OHLC ownership

The shared engine remains valid because ownership stays explicit.

---

## 19. Non-Negotiable Rules

- OHLC is the canonical base chart layer.
- Volume is auxiliary, not the price foundation.
- The viewport is a camera, not a data owner.
- Historical chart space is fixed and padded by workspace.
- User-facing Autoscale is a workspace-owned price-pane vertical contract; legacy anchor-zoom naming, if retained for compatibility, must not redefine ownership.
- Hidden overlays must not influence price-pane autoscale.
- Marker-style overlays must contribute any required visual headroom to price-pane autoscale.
- Controller owns resident truth and refill policy.
- Controller normalizes padded camera space back into dataset-interest windows.
- Stale slices must not overwrite current resident truth.
- Panel owns chart-local study lifecycle, chart-local study identity, and chart-local style truth.
- One controller projection may legitimately fan out to multiple chart-local study instances.
- Workspace owns panes, pane contracts, price-pane vertical behavior, and chart-space policy.
- Panes are handoff boundaries only.
- Renderers draw; they do not define semantics.
- Studies live on chart space; they do not redefine it.
- Style does not trigger compute.
- Save is full-dataset persistence, not render-scoped behavior.
- Pan Anchor is a shell-level horizontal synchronization mode and must not move viewport, controller, renderer, or dataset ownership.
- No shared responsibility may be introduced as a convenience shortcut.

---

## 20. Relationship to Other Design Documents

This document is the historical-chart architecture source of truth.

Other documents remain authoritative for their own concerns:

- `gui_readme.md` → broader GUI/runtime architecture
- `DESIGN_financial_tools.md` → tool families, specs, naming, apply/save semantics
- `construct_readme.md` / construct policy doc → construct naming and runtime behavior
- `core_readme.md` → Core dataset/runtime architecture

This file should not drift back into a Financial Tools document.

---

## 21. Validation Basis

This version also records the compact historical workspace layout update: chart-area margins, embedded grid gaps, splitter handle width, and renderer plot padding may be reduced to maximize data area, while fixed historical chart-space domain padding remains unchanged. View-mode controls are shell-level UI exposed through the historical workspace/window menu, not chart-session semantic ownership. Historical Notebook POI/PT markers are documented as runtime annotations outside the study system and outside financial-tool output truth. Pan Anchor is documented as shell-level horizontal timestamp synchronization rather than viewport or renderer ownership.
M1–M6 hardening validated the current implementation with static checks, targeted regression tests, GUI release checks, and full uploaded test validation.


This document reflects the current validated implementation across the historical chart stack, including:

- fixed chart-space domain padding for historical sessions
- workspace-owned price-pane autoscale/manual-y contract
- controller-owned resident truth and stale-slice rejection
- controller-owned full-study truth and resident-local projection
- panel-owned chart-local duplicate-study identity and chart-local style resolution on projected payloads
- workspace-owned batched pane reapply and pane contract refresh
- pane-owned explicit render handoff
- execution-only renderers
- model-side change batching for coherent refresh
- shell-level Pan Anchor synchronization through timestamp-centering without synchronizing zoom or vertical state

Validation status for this phase:

- static/structural validation was completed against the latest chart files
- targeted behavioral validation was completed with stub-based checks where possible
- live Qt event-loop runtime validation was not executed inside the container because `PySide6` was unavailable there

That limitation does not change the ownership contract defined in this document.

---

## 22. Summary

The Leonardo historical chart is now defined as a stable chart environment with a moving horizontal camera, a workspace-owned price-pane autoscale/manual-y contract, controller-owned resident truth, panel-owned chart-local study lifecycle and identity, workspace-owned pane contracts, runtime POI/PT notebook annotations, optional Pan Anchor horizontal synchronization, and execution-only renderers. The current price-pane study set includes ordinary line overlays, segmented conditional overlays such as HCK, and marker-style event overlays such as `peaks_troughs`; notebook POI/PT markers remain outside the study system.

In plain terms:

- the dataset stays upstream
- the controller decides what resident truth is current
- the panel decides which chart-local studies exist and how they should look
- the workspace decides how panes, price-pane vertical behavior, and pane contracts are organized
- the renderer just draws what it is given

That is the current historical-chart architecture.
---

## 17. Refactored Implementation Baseline — 2026-04-20
The historical chart architecture is now implemented through public façades plus private/internal packages.

### 17.1 Stable public files

These files remain the import-facing API:

```text
gui/historical_chart_controller.py
gui/windows/historical_chart_panel.py
gui/chart/workspace.py
gui/chart/chart_render.py
gui/chart/series_render.py
gui/chart/panes/__init__.py
```

### 17.2 Physical split

```text
gui/historical_chart/               # controller-owned internals
gui/windows/_historical_chart_panel/ # panel-owned internals
gui/chart/_workspace/               # workspace-owned internals
gui/chart/panes/                    # pane package
gui/chart/rendering/                # renderer-owned drawing helpers
```

### 17.3 Frozen contract areas

The following contracts are considered baseline after the refactor:

- viewport owns only the horizontal camera;
- workspace owns chart-space domain policy and price-pane Autoscale/manual-y state;
- controller owns refill policy and resident slice truth;
- panel owns chart-local study identity, style state, and projection fanout;
- panes preserve shared mutable view-state mappings instead of forking copies;
- renderers consume explicit resident-local payloads and do not discover pane membership;
- `HistoricalDatasetService` exposes public timeline/columns/full-dataframe access;
- Core feed tasks do not import GUI bridge classes.

### 17.4 Live smoke-test checklist

After integration, the minimum chart smoke test is:

1. open historical chart;
2. pan left and right across resident data;
3. zoom horizontally in and out;
4. toggle Autoscale on/off;
5. manually adjust price y-range with Autoscale off;
6. re-enable Autoscale and confirm immediate recompute;
7. apply overlay indicator;
8. apply oscillator;
9. open style dialog and change style without recomputation;
10. pan far enough to trigger resident slice refresh;
11. confirm projected studies reapply once, stay styled, and do not lose pane state;
12. remove study;
13. float/dock and confirm state survives.
