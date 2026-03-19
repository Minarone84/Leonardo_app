Leonardo  
DESIGN — Historical Chart v2

Version: v2  
Date: 2026-03-19  
Scope: Historical Data Visualization Workspace (Embedded + Floating, OHLC + Volume, detachable panels, financial tools, async-safe persistence)

Reference:

DESIGN_historical_chart_v2

---

## 1. Purpose

Historical Chart v2 evolves the historical visualization system from a single top-level chart window model into a managed historical workspace.

The system is designed to allow:

- loading historical datasets from local canonical storage
- displaying up to 4 historical chart sessions inside `HistoricalDataManagerWindow`
- detachable chart panels that can float as top-level windows
- docking floating chart windows back into the historical workspace
- preservation of chart session state while changing shell/container
- async-safe Core/GUI separation
- applying indicators and oscillators to historical charts
- saving configured financial tools for later reuse and analysis

The historical chart remains primarily a visualization and research interface.

It is **not** yet:

- a strategy engine
- a backtesting runtime
- a trade execution interface

However, v2 now includes a first financial-tools workflow for historical research and chart annotation.

The system remains intentionally separated from:

- strategy execution
- deterministic backtesting pipelines
- live order routing

These systems may integrate later.

---

## 2. Architectural Principles

### 2.1 Separation of Concerns

The historical system now has four distinct layers.

### Historical Chart Session

Owns the live chart session state:

- selected dataset identity
- chart workspace
- controller
- viewport
- local chart controls
- chart-local financial tool entrypoint

This is represented by:

`HistoricalChartPanel`

### Historical Workspace Management

Owns chart placement and layout inside `HistoricalDataManagerWindow`.

Responsibilities:

- create embedded chart sessions
- manage up to 4 embedded chart panels
- relayout workspace automatically
- detach chart panels into floating windows
- receive docked-back chart panels

This is represented by:

`HistoricalWorkspaceWidget`

### Floating Shell Window

Owns only top-level window responsibilities for a detached chart session.

Responsibilities:

- host one `HistoricalChartPanel`
- behave as a real top-level GUI window
- allow docking back into `HistoricalDataManagerWindow`

This is represented by:

`HistoricalChartWindow`

### Financial Tool Management

Owns the user-facing workflow for selecting, configuring, reviewing, and saving financial tools for the current historical dataset.

Responsibilities:

- choose tool type: indicator / oscillator / construct
- choose specific tool from spec registry
- dynamically render parameter form
- review save intent before persistence
- warn if the same saved artifact already exists
- list saved instances for the current dataset and tool family

This is represented by:

`FinancialToolManagerWindow`

### Design rule

The chart content must be reusable independently of the shell window.

This is what allows a chart to move between:

- embedded mode
- floating mode

without recreating the dataset session.

Financial-tool management must also remain distinct from chart rendering and storage.  
The tool manager collects user intent.  
The controller computes and persists.  
The panel/workspace renders.

---

### 2.2 Async Discipline

The GUI must never block.

Rules:

- All IO runs in the Core thread
- GUI requests Core operations using `CoreBridge.submit()`
- GUI never awaits coroutines directly
- Future callbacks must never mutate Qt widgets directly
- All UI mutations must occur on the Qt GUI thread

`HistoricalChartController` continues to enforce this rule by marshalling Core results back into the GUI thread through Qt signals.

This prevents thread-affinity violations such as:

`QObject::setParent: Cannot set parent, new parent is in a different thread`

---

### 2.3 Shell-Agnostic Chart Sessions

A historical chart session must not depend on being a top-level window.

The same chart session should be able to exist in:

- `HistoricalDataManagerWindow` workspace
- a floating top-level `HistoricalChartWindow`

This rule is central to v2.

It enables:

- future multi-monitor workflows
- detachable chart layouts
- dock/undock behavior without reloading the chart from scratch

---

### 2.4 Dataset Identity First

Historical chart state and derived financial-tool artifacts are keyed by canonical dataset identity:

- exchange
- market type
- symbol
- timeframe

This identity is normalized through the shared naming layer and path-building layer before persistence.

Display/UI formatting may differ from filesystem identity, but persistence always uses canonical dataset identity.

---

## 3. Implemented Components (Current Status)

### 3.1 HistoricalDataManagerWindow

`HistoricalDataManagerWindow` is now the control center for historical charts.

Responsibilities:

- host the historical workspace
- expose New Chart entrypoint
- manage creation of embedded historical chart sessions
- remain the parent manager window for historical work

Current GUI scope:

- menu bar
- status bar
- central managed workspace
- up to 4 embedded historical charts

---

### 3.2 HistoricalChartSelectionDialog

The chart selection dialog is the dataset selection entrypoint used by `File → New Chart`.

Selection flow is enforced in order:

- Exchange
- Market Type
- Asset
- Timeframe

Data sources are discovered from canonical folder structure under:

`data/historical/`

Selection rules:

- exchange list from first-level folders
- market type from folders inside selected exchange
- asset from folders inside selected market type
- timeframe from folders inside selected asset
- Load Data enabled only when all selections are valid
- candles file must exist inside `ohlcv` folder

The dialog does not create chart content directly.

It returns the selected dataset identity to the manager workflow.

---

### 3.3 HistoricalWorkspaceWidget

`HistoricalWorkspaceWidget` manages embedded historical charts inside `HistoricalDataManagerWindow`.

Responsibilities:

- create embedded `HistoricalChartPanel` instances
- store active embedded panels
- relayout panels automatically
- support max 4 embedded charts
- handle detach requests
- handle close requests
- accept docked-back existing panels

Current layout policy:

- 1 chart → full workspace
- 2 charts → split 1x2
- 3 charts → 2x2 with one empty slot
- 4 charts → full 2x2

This layout is deterministic.

No free-floating child widgets or arbitrary overlap are used inside the manager workspace.

---

### 3.4 HistoricalChartPanel

`HistoricalChartPanel` is the reusable chart-content unit.

It is the core v2 chart session object.

Responsibilities:

- host `ChartWorkspaceWidget`
- host `HistoricalChartController`
- expose local chart status area
- expose local chart actions:
  - Float
  - Close
  - Anchor Zoom
  - Financial Tools
- maintain dataset identity for UI display
- forward financial tool actions into the controller
- show financial tool save success/error dialogs

It is shell-agnostic and can be:

- embedded inside `HistoricalWorkspaceWidget`
- hosted inside `HistoricalChartWindow`

---

### 3.5 HistoricalChartWindow

`HistoricalChartWindow` is now a floating shell window.

Responsibilities:

- host one `HistoricalChartPanel`
- expose a Dock Back action
- operate as a top-level detachable chart window
- preserve chart session when panel is reparented into it

This window is no longer the sole chart implementation.

It is now a wrapper around an existing chart session.

---

### 3.6 HistoricalChartController

`HistoricalChartController` remains the GUI-thread controller for historical chart data loading.

Responsibilities:

- request dataset opening
- request windowed slices
- ignore stale responses
- convert slice payloads into GUI chart data
- update chart workspace on the GUI thread
- preserve async safety
- apply indicators/oscillators to the current resident chart slice
- save configured indicators/oscillators to canonical derived CSV storage using the full historical dataset
- emit success/failure signals for financial-tool persistence

The controller is owned by `HistoricalChartPanel`.

It is not tied conceptually to a top-level chart window.

---

### 3.7 ChartWorkspaceWidget

`ChartWorkspaceWidget` remains the shared reusable chart surface used by:

- realtime chart
- historical chart

Responsibilities:

- hold `ChartModel`
- hold `ChartViewport`
- host chart panes
- render price and volume
- support anchor zoom behavior
- accept overlay series from indicators
- accept oscillator series in dedicated oscillator panes

v2 does not replace the workspace.

It reuses it through `HistoricalChartPanel`.

---

### 3.8 FinancialToolManagerWindow

`FinancialToolManagerWindow` is the first chart-adjacent financial-tool workflow for historical research.

Responsibilities:

- select tool category:
  - Indicator
  - Oscillator
  - Construct
- select specific tool from registered specs
- display dynamic parameter form
- show current dataset context
- list saved instances for the selected dataset and tool family
- confirm save intent before persistence
- warn when a saved artifact already exists
- emit:
  - `apply_requested`
  - `save_requested`

Important rule:

This window does **not** compute indicators or save files itself.

It only gathers user intent and emits structured requests.

---

## 4. Windowing Model

### 4.1 Embedded Mode

Historical charts are first created as embedded chart sessions inside `HistoricalDataManagerWindow`.

This is now the default workflow.

Creation flow:

`File → New Chart`
↓  
`HistoricalChartSelectionDialog`
↓  
`HistoricalWorkspaceWidget.add_chart(...)`
↓  
Embedded `HistoricalChartPanel`

---

### 4.2 Floating Mode

An embedded chart can be detached into a top-level window.

Detach flow:

Embedded `HistoricalChartPanel`
↓  
Float action
↓  
`HistoricalWorkspaceWidget` removes panel
↓  
`WindowManager` creates `HistoricalChartWindow`
↓  
same `HistoricalChartPanel` is reparented into floating shell

Important rule:

The chart session is moved, not recreated.

Therefore the same session state is preserved:

- dataset
- viewport
- current resident window
- controller
- chart contents
- applied financial tools already rendered in the session

---

### 4.3 Dock Back Mode

A floating chart can be docked back into `HistoricalDataManagerWindow`.

Dock back flow:

`HistoricalChartWindow`
↓  
Dock Back action
↓  
`WindowManager` takes panel from floating shell
↓  
`HistoricalWorkspaceWidget.add_existing_panel(...)`
↓  
same `HistoricalChartPanel` reinserted into workspace
↓  
floating window closes

Again, the same session is preserved.

---

### 4.4 Window Registration

Top-level windows and dialogs are registered in runtime state through the global state store so they appear in the Windows Inspector.

Tracked examples include:

- `MainWindow`
- `HistoricalDataManagerWindow`
- `HistoricalChartSelectionDialog`
- each floating `HistoricalChartWindow`
- `FinancialToolManagerWindow`
- `WindowsInspectorWindow`
- `HistoricalDownloadWindow`
- `SignalsWindow`

Embedded `HistoricalChartPanel` instances are not treated as top-level windows.

They are workspace children, not windows.

---

## 5. Layout Policy

`HistoricalWorkspaceWidget` uses a deterministic grid policy.

### 5.1 One Chart

The first embedded chart occupies the entire workspace.

### 5.2 Two Charts

Two charts split the workspace in half:

- left
- right

### 5.3 Three Charts

Three charts use a 2x2 layout with one empty slot.

### 5.4 Four Charts

Four charts use the full 2x2 layout.

### 5.5 Embedded Chart Close

Embedded chart panels can be removed directly using a local Close action.

On close:

- panel is removed from workspace
- layout recomputes automatically
- panel widget is deleted

---

## 6. Dataset Service and Canonical Storage

Historical data continues to be served through:

`HistoricalDatasetService`

Responsibilities:

- dataset discovery
- CSV reading
- slice generation
- validation
- optional caching

Canonical candles dataset path format:

```text
data/historical/
    {exchange}/
        {market_type}/
            {symbol}/
                {timeframe}/
                    ohlcv/
                        candles.csv