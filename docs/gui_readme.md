Leonardo GUI Architecture (Current State)

Overview

The Leonardo GUI provides the visualization layer for both historical and real-time charting.

It is built around a modular chart engine capable of rendering large datasets using resident slices and a global index model.

The GUI now supports two chart deployment models:

• Embedded historical chart panels managed by a workspace window  
• Independent top-level chart windows (floating historical charts and future realtime charts)

Both models use the same underlying chart engine.

The GUI architecture separates four concerns:

• chart session (data + viewport + rendering)  
• workspace management (layout of multiple charts)  
• shell window (top-level OS window behavior)  
• financial tool workflow (selection, configuration, apply/save review, persistence feedback)

This separation allows charts to move between embedded and floating states without losing session state, while also allowing financial tools to be configured and persisted without coupling the GUI directly to compute/storage internals.


Historical Workspace Model

Historical charts are primarily managed inside a dedicated window:

HistoricalDataManagerWindow

This window hosts a workspace capable of managing up to four simultaneous historical charts.

Each chart is implemented as a reusable component called:

HistoricalChartPanel

The panel contains:

• chart workspace  
• chart controller  
• dataset identity  
• local chart actions  
• financial tool entrypoint  

Panels can exist in two modes:

Embedded Mode  
Floating Mode


Embedded Mode

When created from:

File → New Chart

a chart is inserted into the historical workspace.

HistoricalWorkspaceWidget manages layout automatically.

Layout policy:

1 chart → full workspace  
2 charts → split left/right  
3 charts → 2x2 grid with one empty slot  
4 charts → full 2x2 grid

Charts can be removed using a Close action on the chart panel.


Floating Mode

An embedded chart can be detached from the workspace.

Flow:

HistoricalChartPanel  
→ Float action  
→ panel removed from workspace  
→ panel reparented into a new HistoricalChartWindow

The floating window becomes a standard top-level GUI window.

The chart session remains unchanged.


Dock Back

Floating charts can return to the workspace.

The dock action is performed from the same panel button used for floating.

Flow:

HistoricalChartPanel  
→ Float button becomes Dock while floating  
→ Dock action  
→ WindowManager retrieves chart panel  
→ panel reinserted into HistoricalWorkspaceWidget

The floating window closes automatically.

The same chart session continues running.

The panel action is state-sensitive:

• embedded panel → button text = Float  
• floating panel → button text = Dock


Window Manager

WindowManager is responsible for managing all top-level windows.

Tracked windows include:

MainWindow  
HistoricalDataManagerWindow  
HistoricalChartWindow (floating)  
RealtimeChartWindow (future)  
WindowsInspectorWindow  
HistoricalDownloadWindow  
SignalsWindow  
FinancialToolManagerWindow

The manager is responsible for:

• window creation  
• window lifetime  
• window registration in runtime state  
• floating chart lifecycle  

Embedded chart panels are not windows and are therefore not tracked by the Window Manager.


Chart Session Architecture

A chart session is represented by:

HistoricalChartPanel

The panel owns:

• ChartWorkspaceWidget  
• HistoricalChartController  
• dataset identity  
• chart status bar  
• financial tool button  

The panel can exist inside different shells:

Embedded inside HistoricalWorkspaceWidget  
Floating inside HistoricalChartWindow

The panel itself is shell-agnostic.


Chart Workspace Architecture

ChartWorkspaceWidget is the main chart container used by both historical and future realtime charts.

It owns:

ChartModel  
ChartViewport  
Crosshair  
Pane stack (via vertical splitter)

Structure:

ChartWorkspaceWidget  
    PricePane  
    VolumePane (optional)  
    OscillatorPane(s)

All panes share the same viewport and crosshair.

The workspace now also exposes explicit helpers for financial tools:

• apply overlay series  
• remove overlay series  
• apply oscillator series  
• remove oscillator series  
• clear overlays / oscillators / financial tools

This allows the historical controller to treat the workspace as the chart-facing application target for indicator and oscillator outputs.


Shared State Objects

ChartViewport

ChartViewport(QObject)

Controls the horizontal slot-based viewport.

State:

_data_total      number of real candles in dataset  
_future_pad      empty slots to the right  
_total           data_total + future_pad  

_visible         number of visible slots  
_start           first visible slot  
_end             start + visible  

Features:

• slot-based discrete X axis  
• pan left / right  
• zoom anchored at mouse  
• future padding  
• optional anchor zoom mode  

All panes share the same viewport.


Crosshair

Crosshair(QObject)

Shared crosshair state across panes.

State:

index           global dataset index  
hover_on_price  controls chart horizontal line  

Signals:

changed  
cleared  

Behavior:

• vertical line shown on all panes  
• price pane horizontal line follows mouse Y  
• volume / oscillator panes show value-based horizontal lines  


Chart Model

ChartModel stores GUI-side data series.

candles  
volume  
overlays      price indicators  
oscillators   oscillator series  
trades        future feature  

For historical mode the model also stores:

resident_base_index

This represents the dataset index of the first resident candle.

This allows translation between:

global dataset index  
resident slice index  


Historical Chart Engine

Historical charts use a resident slice model.

Large datasets are not loaded entirely into memory.

Instead the chart loads partial slices around the visible region.


Dataset vs Slice

FULL DATASET  
|----------------------------------------------------------|

RESIDENT SLICE  
                 |---------------------------|

VIEWPORT  
                      |-----------|


Definitions

Dataset  
Entire historical dataset stored on disk.

Resident slice  
Portion currently loaded in memory.

Viewport  
Visible portion of the dataset.


Global Index Model

The chart engine uses dataset-global indexing.

global_index = resident_base_index + local_index

Rendering surfaces translate:

viewport global index  
→ resident local index  
→ candle / series value  

This allows the chart to behave as if the full dataset were loaded.


Historical Controller

HistoricalChartController manages dataset interaction with the core layer.

Responsibilities:

• open dataset  
• request slices  
• apply slices to workspace  
• trigger refills when navigating near slice edges  
• apply indicator overlays to the current resident historical slice  
• apply oscillator panes to the current resident historical slice  
• save configured indicators/oscillators using the full canonical candles dataset  
• emit success/failure save signals back to the panel UI

The controller preserves viewport continuity across resident slice updates.

Refill targeting follows the actual viewport center rather than snapping back to the current resident slice.

When the requested refill center falls just outside the current resident slice, timestamp resolution may be extrapolated from resident timeframe spacing so refills can continue to follow historical navigation smoothly.

Important financial-tool rule:

Apply and Save intentionally use different data scopes.

• Apply → current resident slice already loaded in memory  
• Save → full canonical historical dataset on disk

This keeps chart interaction fast while keeping persisted analysis artifacts complete.


Slice Metadata

Each slice payload provides:

base_index  
has_more_left  
has_more_right  

Controller state tracks:

resident_base_index  
resident_size  
dataset_count  


Refill on Pan

When the viewport approaches slice boundaries the controller requests a new slice.

Example logic:

if left_margin <= threshold  
    refill-left  

if right_margin <= threshold  
    refill-right  

The refill is centered around the current viewport center.

Viewport position is preserved.

Future-pad space on the right does not participate in historical refill targeting.


Rendering System

Rendering is performed by specialized surfaces.


Price Chart

ChartRenderSurface

Draws:

• candlesticks  
• grid  
• price axis  
• time axis  
• realtime price tag  
• crosshair  
• overlay indicators supplied through ChartModel overlays  

Supports:

• pan (drag)  
• zoom (mouse wheel)  
• optional free Y scaling when anchor zoom disabled  
• manual Y zoom and free Y pan when anchor zoom is disabled  

Non-anchored vertical navigation is intentionally free:

• vertical pan direction follows drag direction  
• vertical pan is not clamped to the resident candle envelope  
• candles can be panned fully out of view vertically  


Volume Pane

VolumeRenderSurface

Draws:

• volume bars  
• volume legend tag  
• crosshair index line  
• horizontal value line  


Oscillator Pane

OscillatorRenderSurface

Draws:

• oscillator polyline  
• oscillator legend tag  
• crosshair index line  
• horizontal value line  

Oscillator panes are created dynamically when oscillator series are applied through the workspace.


Pane System

Each pane consists of:

Pane  
 ├─ RenderSurface  
 └─ Overlay  

Overlay displays:

• pane title  
• values at crosshair index  

Pane types:

PricePane  
VolumePane  
OscillatorPane  


Interaction Model


Crosshair

The crosshair vertical line is shared across all panes.

Index is computed using discrete slot mapping.

index = viewport.index_from_x(...)


Zoom

Mouse wheel zoom adjusts visible slot range.

viewport.zoom_in_at(...)  
viewport.zoom_out_at(...)

Zoom is anchored to the slot under the mouse cursor.


Anchor Zoom Mode

Anchor zoom modifies how zoom and scaling behave.

When anchor zoom is ON:

• Y axis auto-scales to visible candles  
• wheel zoom keeps the latest candle aligned when the viewport is at the right edge  
• historical exploration away from the right edge is preserved  
• enabling anchor mode does not teleport the viewport to the latest window  

When anchor zoom is OFF:

• right axis drag → Y zoom  
• shift + drag → Y pan  
• plot-area vertical drag → Y pan  
• future padding accessible  
• vertical range is controlled manually  
• vertical pan is unrestricted by resident candle bounds  


Important Behavior

Enabling anchor zoom does not teleport the viewport.

The current historical position is preserved when the mode is toggled.

Latest alignment is only maintained when the viewport is already positioned at the latest candle.

If the user is exploring older historical data away from the latest edge, anchor-mode zoom preserves that historical position instead of snapping to the latest window.


Financial Tool Workflow

Historical chart panels now expose a local action:

Financial Tools

This opens:

FinancialToolManagerWindow

for the currently selected chart dataset.

The Financial Tool Manager is a GUI-side configuration workflow only.  
It does not compute tools directly and does not persist files directly.

It is responsible for:

• selecting tool family:
  • Indicator
  • Oscillator
  • Construct
• selecting a specific tool
• rendering dynamic parameter editors from spec metadata
• showing current dataset context:
  • Exchange
  • Market type
  • Asset
  • Timeframe
• showing saved instances for the current dataset/tool family
• confirming save intent before persistence
• warning when the same saved artifact already exists
• emitting apply/save intent into the panel/controller chain

Current apply/save flow:

Apply  
→ manager builds payload  
→ panel forwards payload  
→ controller computes on resident slice  
→ workspace renders result immediately  
→ nothing is persisted

Save  
→ manager builds payload  
→ manager confirms save intent  
→ if artifact already exists, manager shows overwrite warning  
→ panel forwards payload  
→ controller loads full candles dataset  
→ controller computes full result  
→ controller persists derived CSV  
→ panel shows success/error dialog  
→ manager refreshes saved-instance list


Save Review Confirmation

Before save proceeds, the manager shows a review dialog summarizing:

• Exchange  
• Market type  
• Asset  
• Timeframe  
• Tool type  
• Tool  
• Parameters / metadata  

The user must confirm before save continues.


Overwrite Warning

If the same artifact already exists, the manager shows a stronger warning dialog instead of the normal save confirmation.

The overwrite dialog explicitly states that the indicator / oscillator / construct already exists for the selected dataset, then shows the usual summary, then asks whether the user wants to proceed anyway.

Only explicit confirmation allows overwrite.


Save Success / Failure Feedback

Save result dialogs are shown by HistoricalChartPanel after the controller emits a real outcome.

On success:

• a confirmation dialog states what was saved  
• shows dataset identity  
• shows parameters / metadata  
• shows the saved file path  

On failure:

• an error dialog states what was not saved  
• shows dataset identity  
• shows parameters / metadata  
• shows reason/error text  
• shows target path when available  

This keeps the manager as an intent-collection UI and keeps save-result truth anchored in the controller.


Saved Financial Tool Instances

Derived historical financial tools are persisted as CSV artifacts partitioned by canonical dataset identity.

Canonical candles location:

data/historical/{exchange}/{market_type}/{symbol}/{timeframe}/ohlcv/candles.csv

Derived artifacts are stored beside it in sibling folders:

• indicators  
• oscillators  
• constructs

Example paths:

data/historical/bybit/linear/BTCUSDT/1h/indicators/  
data/historical/bybit/linear/BTCUSDT/1h/oscillators/

Each configured tool instance is saved as its own CSV artifact.

Examples:

• sma__period-20.csv  
• bb__period-20__std-2.0.csv  
• rsi__period-14.csv

The Financial Tool Manager reads these folders to populate the Saved Instances list for the currently selected dataset and tool.


Dependency Overview

HistoricalDataManagerWindow  
 └─ HistoricalWorkspaceWidget  
     ├─ HistoricalChartPanel  
     │   ├─ HistoricalChartController  
     │   ├─ FinancialToolManagerWindow  
     │   └─ ChartWorkspaceWidget  
     │       ├─ ChartModel  
     │       ├─ ChartViewport  
     │       ├─ Crosshair  
     │       └─ QSplitter  
     │           ├─ PricePane  
     │           │   └─ ChartRenderSurface  
     │           ├─ VolumePane  
     │           │   └─ VolumeRenderSurface  
     │           └─ OscillatorPane  
     │               └─ OscillatorRenderSurface  


Architectural Principles

The chart engine is designed around the following invariants:

• global dataset indexing  
• resident slice rendering  
• viewport continuity  
• pane independence  
• shell-agnostic chart sessions  
• GUI/controller separation for persistence outcomes  
• canonical dataset identity for saved financial tool artifacts  


Key Rule

All rendering and overlays must respect:

global_index = resident_base_index + local_index

Breaking this invariant will cause incorrect rendering during slice refills.

Additional key rule:

Financial tool Apply and Save must not be treated as the same operation.

• Apply is chart-local and resident-slice based  
• Save is canonical and full-dataset based  


Summary

The Leonardo GUI chart system now provides:

• scalable historical dataset visualization  
• reusable chart session architecture  
• deterministic workspace layout for up to 4 charts  
• detachable floating chart windows  
• dock-back capability for floating charts using the same panel control  
• modular pane architecture  
• discrete slot-based viewport  
• crosshair synchronization  
• viewport-centered resident slice refill behavior  
• free non-anchored vertical navigation  
• chart-local Financial Tool Manager  
• indicator/oscillator application to historical charts  
• canonical derived CSV persistence for saved financial tools  
• save review confirmation  
• overwrite warning for existing artifacts  
• success/error save dialogs  
• saved financial-tool instance listing  

The architecture now supports both:

• multi-chart workspace workflows  
• multi-monitor floating chart workflows  
• historical chart-based financial tool exploration and persistence