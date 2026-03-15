Leonardo GUI Architecture (Current State)

Overview

The Leonardo GUI provides the visualization layer for both historical and real-time charting.

It is built around a modular chart engine capable of rendering large datasets using resident slices and a global index model.

The GUI now supports two chart deployment models:

• Embedded historical chart panels managed by a workspace window  
• Independent top-level chart windows (floating historical charts and future realtime charts)

Both models use the same underlying chart engine.

The GUI architecture separates three concerns:

• chart session (data + viewport + rendering)  
• workspace management (layout of multiple charts)  
• shell window (top-level OS window behavior)

This separation allows charts to move between embedded and floating states without losing session state.


Historical Workspace Model

Historical charts are primarily managed inside a dedicated window:

HistoricalDataManagerWindow

This window hosts a workspace capable of managing up to **four simultaneous historical charts**.

Each chart is implemented as a reusable component called:

HistoricalChartPanel

The panel contains:

• chart workspace  
• chart controller  
• dataset identity  
• local chart actions

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

Charts can be removed using a **Close** action on the chart panel.


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

Flow:

HistoricalChartWindow  
→ Dock Back action  
→ WindowManager retrieves chart panel  
→ panel reinserted into HistoricalWorkspaceWidget  

The floating window closes automatically.

The same chart session continues running.


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

The manager is responsible for:

• window creation  
• window lifetime  
• window registration in runtime state  
• floating chart lifecycle  

Embedded chart panels are **not** windows and are therefore not tracked by the Window Manager.


Chart Session Architecture

A chart session is represented by:

HistoricalChartPanel

The panel owns:

• ChartWorkspaceWidget  
• HistoricalChartController  
• dataset identity  
• chart status bar  

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
• anchor zoom mode  

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

Historical charts use a **resident slice model**.

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

Supports:

• pan (drag)  
• zoom (mouse wheel)  
• optional free Y scaling when anchor zoom disabled  


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

Zoom is anchored to slot center.


Anchor Zoom Mode

When anchor zoom is ON:

• Y axis auto-scales to visible candles  
• viewport snaps to latest candle  

When OFF:

• right axis drag → Y zoom  
• shift + drag → Y pan  
• future padding accessible  


Dependency Overview

HistoricalDataManagerWindow  
 └─ HistoricalWorkspaceWidget  
     ├─ HistoricalChartPanel  
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


Key Rule

All rendering and overlays must respect:

global_index = resident_base_index + local_index

Breaking this invariant will cause incorrect rendering during slice refills.


Summary

The Leonardo GUI chart system now provides:

• scalable historical dataset visualization  
• reusable chart session architecture  
• deterministic workspace layout for up to 4 charts  
• detachable floating chart windows  
• dock-back capability for floating charts  
• modular pane architecture  
• discrete slot-based viewport  
• crosshair synchronization  

The architecture now supports both:

• multi-chart workspace workflows  
• multi-monitor floating chart workflows