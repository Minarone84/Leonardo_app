Leonardo GUI Architecture (Current State)
Overview

The Leonardo GUI provides the visualization layer for both historical and real-time charting.
It is built around a modular chart engine capable of rendering large datasets using resident slices and a global index model.

The GUI is composed of independent chart windows, each fully operational on its own.
A separate Window Manager organizes these windows on screen.

Each chart window contains a chart workspace composed of multiple stacked panes:

Price pane (always present)

Optional volume pane

Optional oscillator panes

Future construct panels

All panes share the same viewport and crosshair state.

Chart Window Model
Independent Windows

The system uses fully independent chart windows.

Examples:

HistoricalChartWindow

RealtimeChartWindow

Each window owns its own:

chart workspace

controller/session

viewport

crosshair

pane configuration

status bar

symbol/timeframe state

These windows are self-contained and can operate alone.

Window Manager

Charts are organized by a Window Manager, not by embedding charts inside a container window.

The Window Manager provides:

bring window to front

collapse / expand

layout presets

organize multiple charts

manage screen placement

Typical layout presets:

1 chart

2 charts side-by-side

3 charts (1 top / 2 bottom)

4 charts grid

Both historical and realtime charts can be arranged using these layouts.

The system supports up to 4 independent chart windows simultaneously.

Chart Workspace Architecture

ChartWorkspaceWidget

The workspace is the main chart container inside each chart window.

It owns:

ChartModel

ChartViewport

Crosshair

vertical splitter stacking panes

ChartWorkspaceWidget
    PricePane
    VolumePane (optional)
    OscillatorPane(s)
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

slot-based discrete X axis

pan left / right

zoom anchored at mouse

future padding

anchor zoom mode

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

vertical line shown on all panes

price pane horizontal line follows mouse Y

volume / oscillator panes show value-based horizontal lines

Chart Model

ChartModel

Stores GUI-side data series.

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

Definitions:

Term	Meaning
Dataset	Entire historical data
Resident slice	Portion currently loaded in memory
Viewport	Visible part of dataset
Global Index Model

The chart engine uses dataset-global indexing.

global_index = resident_base_index + local_index

Rendering surfaces translate:

viewport global index
→ resident local index
→ candle / series value

This ensures the chart behaves like a continuous dataset.

Historical Controller

HistoricalChartController

The controller manages dataset interaction with the core layer.

Responsibilities:

open dataset

request slices

apply slices to workspace

trigger refills when navigating near slice edges

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

if left_margin <= threshold:
    refill-left

if right_margin <= threshold:
    refill-right

The refill is centered around the current viewport center.

Viewport position is preserved.

Rendering System

Rendering is performed by specialized surfaces.

Price Chart

ChartRenderSurface

Draws:

candlesticks

grid

price axis

time axis

real-time price tag

crosshair

Supports:

pan (drag)

zoom (mouse wheel)

optional free Y scaling when anchor zoom disabled

Volume Pane

VolumeRenderSurface

Draws:

volume bars

volume legend tag

crosshair index line

horizontal value line

Oscillator Pane

OscillatorRenderSurface

Draws:

oscillator polyline

oscillator legend tag

crosshair index line

horizontal value line

Pane System

Each pane is composed of:

Pane
 ├─ RenderSurface
 └─ Overlay

Overlay displays:

title

values at crosshair index

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

Mouse wheel zoom adjusts visible slot range:

viewport.zoom_in_at(...)
viewport.zoom_out_at(...)

Zoom is anchored to slot center.

Anchor Zoom Mode

When anchor zoom is ON:

Y axis auto-scales to visible candles

viewport snaps to latest candle

When OFF:

right axis drag → Y zoom

shift + drag → Y pan

future padding accessible

Phase Roadmap
Phase 1 — Historical Engine Foundation (Completed)

Implemented:

dataset-global indexing

resident slice management

refill-on-pan

viewport preservation

crosshair compatibility

rendering support for resident slices

Phase 2 — Navigation Stability

Goals:

refine refill triggers

stabilize crosshair across refills

ensure smooth viewport continuity

prevent refill request storms

stress test navigation

Phase 3 — Indicator Engine

Indicators must handle historical slices correctly.

Oscillators may require lookback beyond slice boundaries.

Example:

RSI(14)

If a slice begins at index 5000, RSI requires data from earlier candles.

Future solutions may include:

indicator warmup windows

extended slice requests

cached indicator state

Phase 4 — Real-Time Integration

Realtime charts will reuse the same chart engine.

Lifecycle:

load historical slice
switch to realtime stream
append new candles
maintain dataset continuity
Dependency Overview
ChartWindow
 └─ ChartWorkspaceWidget
     ├─ ChartModel
     ├─ ChartViewport
     ├─ Crosshair
     └─ QSplitter
         ├─ PricePane
         │   └─ ChartRenderSurface
         ├─ VolumePane
         │   └─ VolumeRenderSurface
         └─ OscillatorPane
             └─ OscillatorRenderSurface
Architectural Principles

The chart engine is designed around the following invariants:

Global dataset indexing

Resident slice rendering

Viewport continuity

Pane independence

Independent chart windows

These principles ensure the chart behaves as if rendering a continuous dataset, even when only partial slices are loaded in memory.

Key Rule

All rendering and overlays must respect:

global_index = resident_base_index + local_index

Breaking this invariant will cause incorrect rendering during slice refills.

Summary

The Leonardo GUI chart system now provides:

scalable historical dataset visualization

modular pane architecture

discrete slot-based viewport

crosshair synchronization

independent chart windows

window-manager-based layout organization

The architecture is ready for navigation stabilization (Phase 2) and future realtime integration.