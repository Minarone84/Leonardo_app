Leonardo
DESIGN — Historical Chart v2

Version: v2
Date: 2026-03-15
Scope: Historical Data Visualization Workspace (Embedded + Floating, OHLC + Volume, detachable panels, async)

Reference:

DESIGN_historical_chart_v2

1. Purpose

Historical Chart v2 evolves the historical visualization system from a single top-level chart window model into a managed historical workspace.

The system is designed to allow:

• loading historical datasets from local canonical storage
• displaying up to 4 historical chart sessions inside HistoricalDataManagerWindow
• detachable chart panels that can float as top-level windows
• docking floating chart windows back into the historical workspace
• preservation of chart session state while changing shell/container
• async-safe Core/GUI separation

The historical chart remains a visualization and research interface.

It is not an analysis engine.

The system remains intentionally separated from:

• backtesting
• indicators computation
• signal generation
• strategy execution
• deterministic analysis pipelines

These systems may integrate later.

2. Architectural Principles

2.1 Separation of Concerns

The historical system now has three distinct layers.

Historical Chart Session

Owns the live chart session state:

• selected dataset identity
• chart workspace
• controller
• viewport
• local chart controls

This is represented by:

HistoricalChartPanel

Historical Workspace Management

Owns chart placement and layout inside HistoricalDataManagerWindow.

Responsibilities:

• create embedded chart sessions
• manage up to 4 embedded chart panels
• relayout workspace automatically
• detach chart panels into floating windows
• receive docked-back chart panels

This is represented by:

HistoricalWorkspaceWidget

Floating Shell Window

Owns only top-level window responsibilities for a detached chart session.

Responsibilities:

• host one HistoricalChartPanel
• behave as a real top-level GUI window
• allow docking back into HistoricalDataManagerWindow

This is represented by:

HistoricalChartWindow

Design rule:

The chart content must be reusable independently of the shell window.

This is what allows a chart to move between:

• embedded mode
• floating mode

without recreating the dataset session.

2.2 Async Discipline

The GUI must never block.

Rules:

• All IO runs in the Core thread
• GUI requests Core operations using CoreBridge.submit()
• GUI never awaits coroutines directly
• Future callbacks must never mutate Qt widgets directly
• All UI mutations must occur on the Qt GUI thread

HistoricalChartController continues to enforce this rule by marshalling Core results back into the GUI thread through Qt signals.

This prevents thread-affinity violations such as:

QObject::setParent: Cannot set parent, new parent is in a different thread

2.3 Shell-Agnostic Chart Sessions

A historical chart session must not depend on being a top-level window.

The same chart session should be able to exist in:

• HistoricalDataManagerWindow workspace
• a floating top-level HistoricalChartWindow

This rule is central to v2.

It enables:

• future multi-monitor workflows
• detachable chart layouts
• dock/undock behavior without reloading the chart from scratch

3. Implemented Components (Current Status)

3.1 HistoricalDataManagerWindow

HistoricalDataManagerWindow is now the control center for historical charts.

Responsibilities:

• host the historical workspace
• expose New Chart entrypoint
• manage creation of embedded historical chart sessions
• remain the parent manager window for historical work

Current GUI scope:

• menu bar
• status bar
• central managed workspace
• up to 4 embedded historical charts

3.2 HistoricalChartSelectionDialog

The chart selection dialog is the dataset selection entrypoint used by File → New Chart.

Selection flow is enforced in order:

• Exchange
• Market Type
• Asset
• Timeframe

Data sources are discovered from canonical folder structure under:

data/historical/

Selection rules:

• exchange list from first-level folders
• market type from folders inside selected exchange
• asset from folders inside selected market type
• timeframe from folders inside selected asset
• Load Data enabled only when all selections are valid
• candles file must exist inside ohlcv folder

The dialog does not create chart content directly.

It returns the selected dataset identity to the manager workflow.

3.3 HistoricalWorkspaceWidget

HistoricalWorkspaceWidget manages embedded historical charts inside HistoricalDataManagerWindow.

Responsibilities:

• create embedded HistoricalChartPanel instances
• store active embedded panels
• relayout panels automatically
• support max 4 embedded charts
• handle detach requests
• handle close requests
• accept docked-back existing panels

Current layout policy:

• 1 chart → full workspace
• 2 charts → split 1x2
• 3 charts → 2x2 with one empty slot
• 4 charts → full 2x2

This layout is deterministic.

No free-floating child widgets or arbitrary overlap are used inside the manager workspace.

3.4 HistoricalChartPanel

HistoricalChartPanel is the reusable chart-content unit.

It is the core v2 chart session object.

Responsibilities:

• host ChartWorkspaceWidget
• host HistoricalChartController
• expose local chart status area
• expose local chart actions:
  • Float
  • Close
  • Anchor Zoom
• maintain dataset identity for UI display

It is shell-agnostic and can be:

• embedded inside HistoricalWorkspaceWidget
• hosted inside HistoricalChartWindow

3.5 HistoricalChartWindow

HistoricalChartWindow is now a floating shell window.

Responsibilities:

• host one HistoricalChartPanel
• expose a Dock Back action
• operate as a top-level detachable chart window
• preserve chart session when panel is reparented into it

This window is no longer the sole chart implementation.

It is now a wrapper around an existing chart session.

3.6 HistoricalChartController

HistoricalChartController remains the GUI-thread controller for historical chart data loading.

Responsibilities:

• request dataset opening
• request windowed slices
• ignore stale responses
• convert slice payloads into GUI chart data
• update chart workspace on the GUI thread
• preserve async safety

The controller is now owned by HistoricalChartPanel instead of being tied conceptually to a top-level chart window.

3.7 ChartWorkspaceWidget

ChartWorkspaceWidget remains the shared reusable chart surface used by:

• realtime chart
• historical chart

Responsibilities:

• hold ChartModel
• hold ChartViewport
• host chart panes
• render price and volume
• support anchor zoom behavior

v2 does not replace the workspace.

It reuses it through HistoricalChartPanel.

4. Windowing Model

4.1 Embedded Mode

Historical charts are first created as embedded chart sessions inside HistoricalDataManagerWindow.

This is now the default workflow.

Creation flow:

File → New Chart
    ↓
HistoricalChartSelectionDialog
    ↓
HistoricalWorkspaceWidget.add_chart(...)
    ↓
Embedded HistoricalChartPanel

4.2 Floating Mode

An embedded chart can be detached into a top-level window.

Detach flow:

Embedded HistoricalChartPanel
    ↓
Float action
    ↓
HistoricalWorkspaceWidget removes panel
    ↓
WindowManager creates HistoricalChartWindow
    ↓
same HistoricalChartPanel is reparented into floating shell

Important rule:

The chart session is moved, not recreated.

Therefore the same session state is preserved:

• dataset
• viewport
• current resident window
• controller
• chart contents

4.3 Dock Back Mode

A floating chart can be docked back into HistoricalDataManagerWindow.

Dock back flow:

HistoricalChartWindow
    ↓
Dock Back action
    ↓
WindowManager takes panel from floating shell
    ↓
HistoricalWorkspaceWidget.add_existing_panel(...)
    ↓
same HistoricalChartPanel reinserted into workspace
    ↓
floating window closes

Again, the same session is preserved.

4.4 Window Registration

Top-level windows and dialogs are registered in runtime state through the global state store so they appear in the Windows Inspector.

Tracked examples include:

• MainWindow
• HistoricalDataManagerWindow
• HistoricalChartSelectionDialog
• each floating HistoricalChartWindow
• WindowsInspectorWindow
• HistoricalDownloadWindow
• SignalsWindow

Embedded HistoricalChartPanel instances are not treated as top-level windows.

They are workspace children, not windows.

5. Layout Policy

HistoricalWorkspaceWidget uses a deterministic grid policy.

5.1 One Chart

The first embedded chart occupies the entire workspace.

5.2 Two Charts

Two charts split the workspace in half:

• left
• right

5.3 Three Charts

Three charts use a 2x2 layout with one empty slot.

5.4 Four Charts

Four charts use the full 2x2 layout.

5.5 Embedded Chart Close

Embedded chart panels can be removed directly using a local Close action.

On close:

• panel is removed from workspace
• layout recomputes automatically
• panel widget is deleted

6. Dataset Service

Historical data continues to be served through:

HistoricalDatasetService

Responsibilities:

• dataset discovery
• CSV reading
• slice generation
• validation
• optional caching

Canonical dataset path format:

data/historical/
    {exchange}/
        {market_type}/
            {symbol}/
                {timeframe}/
                    ohlcv/
                        candles.csv

CSV remains the canonical storage format.

7. Core ↔ GUI Communication

All historical dataset operations use CoreBridge.

Pattern:

future = CoreBridge.submit(coro)
future.add_done_callback(...)

Important rule:

Callbacks must never modify Qt widgets directly.

Required safe pattern:

Core thread callback
        ↓
Qt Signal
        ↓
GUI thread slot
        ↓
workspace update

This rule remains unchanged from v1.

8. Current Rendering Features

Historical Chart v2 currently renders:

• OHLC candles
• Volume histogram

Current chart-local controls:

• Float
• Close (embedded mode)
• Dock Back (floating mode)
• Anchor Zoom

Indicators and oscillators remain outside current historical visualization scope.

9. Chart Identity Model

Each chart session is identified by selected dataset fields:

• exchange
• market_type
• symbol
• timeframe

Display identity uses:

Historical Chart: Exchange_market_type_symbol_timeframe

Important display rule:

The exchange first letter is capitalized for UI display only.

Examples:

• Historical Chart: Bybit_linear_BTCUSDT_1h
• Historical Chart: Binance_spot_ETHUSDT_15m

Filesystem identity remains unchanged and lower-level dataset loading still uses canonical raw folder values.

10. State Machine (v2)

Each historical chart session conceptually follows:

NEW
OPENING_DATASET
READY
LOADING_SLICE
DISPLAYING
FLOATING
EMBEDDED
ERROR
CLOSED

Typical transitions:

NEW → OPENING_DATASET → READY → LOADING_SLICE → DISPLAYING
DISPLAYING → FLOATING
FLOATING → EMBEDDED
DISPLAYING → CLOSED
* → ERROR

Notes:

• FLOATING and EMBEDDED are shell/container states
• dataset/controller state survives shell changes

11. Caching Strategy

Slice caching remains service-side.

Cache key:

(dataset_id, slice_range_signature)

Cache type:

LRU

Shared across chart sessions.

12. Concurrency Model

Core side:

• single asyncio event loop
• multiple concurrent slice requests allowed
• dataset service handles caching and slicing

GUI side:

• single Qt thread
• all widget mutations occur here
• each chart session has independent viewport/controller state

Shell changes such as float/dock are GUI-thread reparenting operations.

13. Error Handling

Errors must never crash the GUI.

Examples:

• missing dataset
• missing candles.csv
• CSV parse failure
• invalid dataset path
• attempt to exceed 4 embedded charts
• dock back requested while HDMW unavailable
• dock back requested while workspace already full

Expected behavior:

• show user-safe messages when appropriate
• preserve existing sessions whenever possible
• never mutate Qt widgets from Core thread callbacks

14. Non-Goals (v2)

The following remain out of scope for v2:

• indicators computation
• oscillator computation
• strategy execution
• backtesting
• trade simulation
• live merge into historical chart
• arbitrary drag-and-drop docking system
• freeform MDI/subwindow overlap layouts

v2 focuses on:

• stable historical workspace
• detachable chart sessions
• preserved session state across shell changes

15. Role in Leonardo Architecture

Historical Chart v2 is now a workspace-oriented chart system.

It provides:

• reusable historical chart session object
• deterministic workspace manager
• detachable floating chart shell
• consistent dataset identity model
• preserved async-safe controller model

This architecture now supports:

• single-window historical research workflows
• multi-chart side-by-side comparison
• multi-monitor chart workflows through floating windows
• future expansion into richer chart-management actions

16. Summary of v2 Changes vs v1

v1 centered the system on a top-level HistoricalChartWindow.

v2 introduces a layered chart architecture:

• HistoricalChartPanel = reusable chart session
• HistoricalWorkspaceWidget = embedded chart manager
• HistoricalChartWindow = floating shell only
• HistoricalDataManagerWindow = workspace host

Major functional additions in v2:

• embedded historical charts inside HDMW
• automatic 1/2/3/4 chart layout management
• detachable charts via Float
• dock-back flow for floating charts
• per-chart close action in embedded mode
• chart identity reflected in window/status titles
• multiple floating chart windows tracked independently in runtime state

This establishes the first real historical chart workspace model for Leonardo.