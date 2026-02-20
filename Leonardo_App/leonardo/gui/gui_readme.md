Leonardo GUI Overview (current state)
High-level architecture

The GUI is built around a single central workspace containing a stack of chart panes (price + optional volume + optional oscillators).
The panes share:

a ChartViewport (controls X-range: start/end/visible, pan/zoom)

a Crosshair (controls shared crosshair index and chart-hover state)

The app also includes:

a MainWindow with menus wired to workspace actions

a Window Manager service (in core registry) used to open auxiliary windows (Signals, Windows Inspector)

a WindowsInspectorWindow that polls core state to display open windows tracking

Core GUI entry points
leonardo/gui/main_window.py — MainWindow(QMainWindow)

Role: Main UI shell: menus, status bar, central workspace, registry-driven actions.

Owns:

ChartWorkspaceWidget as central widget

menu actions (volume toggle, add oscillator, realtime control, windows inspector, anchor zoom toggle)

a CoreBridge reference to interact with the core loop

Calls into:

ChartWorkspaceWidget:

set_volume_enabled()

add_oscillator(), clear_oscillators()

set_asset_label(), set_studies_labels()

set_anchor_zoom_enabled()

Core state (async via CoreBridge.submit()):

ctx.state.window_open("main", "MainWindow", where="gui")

ctx.state.window_close("main", where="gui")

ctx.state.set_realtime_active(...)

ctx.state.is_realtime_active()

Calls into window manager service:

wm.open_windows_inspector()

wm.open_signals(), wm.get_signals()

leonardo/gui/core_bridge.py — CoreBridge

Role: Thread-safe bridge from Qt GUI thread to the async core loop.

Used by:

MainWindow

WindowsInspectorWindow

Typical usage:

submit(coro) returns a future-like result

emits status_changed into GUI thread

Chart workspace & panes
leonardo/gui/chart/workspace.py — ChartWorkspaceWidget(QWidget)

Role: The chart container: holds model, viewport, crosshair, and the vertical splitter stacking panes.

Owns:

ChartModel (dummy candles, volume, oscillator series)

ChartViewport (shared X-axis state)

Crosshair (shared crosshair state)

QSplitter(Qt.Vertical) with:

PricePane always

optional VolumePane

optional OscillatorPane instances

Calls into:

PricePane(viewport, model, crosshair)

VolumePane(viewport, volume, crosshair) (created on toggle)

OscillatorPane(title, viewport, values, crosshair) (created per spec)

Public API (used by MainWindow):

set_asset_label(text)

set_studies_labels(indicators, oscillators)

set_volume_enabled(True/False)

add_oscillator(OscillatorSpec)

clear_oscillators()

set_anchor_zoom_enabled(True/False) → delegates to ChartViewport.set_anchor_zoom_enabled()

leonardo/gui/chart/panes.py

Contains the pane widgets and their overlays.

_PaneOverlay(QWidget)

Role: Small translucent overlay (top-left) with three labels:

title

line1

line2
Mouse-transparent so it doesn’t steal hover.

Used by all panes.

PricePane(QWidget)

Role: Price pane container:

hosts the ChartRenderSurface

maintains overlay with:

“ASSET · TF”

OHLC at crosshair index

indicator overlay values at crosshair index

Owns:

ChartRenderSurface(viewport, crosshair, candles)

_PaneOverlay

Reads from:

crosshair.index to decide which candle to display

ChartModel.overlays() for indicator values

Subscribes to:

viewport.viewport_changed

crosshair.changed, crosshair.cleared (though clearing is now rare by design)

VolumePane(QWidget)

Role: Volume pane container:

hosts VolumeRenderSurface

overlay shows Vol: <value> at crosshair index

Reads from:

crosshair.index to display volume at that index

Subscribes to:

viewport + crosshair signals for repaint and overlay updates

OscillatorPane(QWidget)

Role: Oscillator pane container:

hosts OscillatorRenderSurface

overlay shows oscillator value at crosshair index

Reads from:

crosshair.index

Subscribes to:

viewport + crosshair signals

Rendering surfaces (actual drawing + mouse interaction)
leonardo/gui/chart/chart_render.py — ChartRenderSurface(QWidget)

Role: Draws the candlestick chart + grid + price axis + shared crosshair vertical line.
Also supports:

horizontal pan (drag inside plot)

anchored horizontal zoom (wheel, anchored at mouse X)

optional non-anchored Y scaling when anchor zoom is OFF:

right-axis drag = zoom Y

shift + right-axis drag = pan Y

Mouse behavior implemented:

Crosshair vertical line is shared across all panes via Crosshair.index

Horizontal line on chart is shown only when hovering the chart plot

Crosshair index is updated from mouse X when hovering chart plot area

Wheel zoom uses viewport.zoom_in_at/zoom_out_at anchored to mouse X

Axis interaction:

only when anchor zoom OFF

click/drag right axis = Y zoom

shift + drag right axis = Y pan

Calls into:

ChartViewport.index_from_x(), x_from_index()

ChartViewport.zoom_in_at() / zoom_out_at()

ChartViewport.pan_left()/pan_right()

Crosshair.set(...) (idx + y_rel) in earlier versions

current behavior uses Crosshair.index + hover tracking (depending on version you’re running)

leonardo/gui/chart/series_render.py

Contains VolumeRenderSurface and OscillatorRenderSurface.

VolumeRenderSurface(QWidget)

Role: Draws volume bars + right-side label.
Handles mouse to update shared crosshair index and wheel zoom.

Crosshair behavior:

On mouse move inside plot:

computes idx from mouse X

sets shared Crosshair.index

forces Crosshair.hover_on_price=False so chart horizontal line does not appear

Draws:

shared vertical line if index is visible

horizontal line that follows volume[idx] (value-based)

uses current visible scale; clamps if needed to avoid off-plot y

Calls into:

viewport.index_from_x(), viewport.x_from_index()

viewport.zoom_in_at()/zoom_out_at()

crosshair.set_index()

crosshair.set_hover_on_price(False)

OscillatorRenderSurface(QWidget)

Role: Draws oscillator line series + right-side label.
Handles mouse to update shared crosshair index and wheel zoom.

Crosshair behavior:

On mouse move inside plot:

sets shared Crosshair.index

forces Crosshair.hover_on_price=False

Draws:

shared vertical line if visible

horizontal line at values[idx] (value-based)

Calls into:

same viewport + crosshair methods as volume surface

Shared state objects
leonardo/gui/chart/viewport.py — ChartViewport(QObject)

Role: Shared horizontal (time) viewport for all panes.

State:

_total, _visible, _start

derived:

end = start + visible

anchor_zoom_enabled flag (controls chart-only Y behavior; X zoom is always anchored)

Provides:

pan:

pan_left(step), pan_right(step)

index mapping:

index_from_x(plot, x) → absolute index in [start, end-1]

x_from_index(plot, idx) → x pixel for index

anchored zoom:

zoom_in_at(anchor_idx, anchor_rel)

zoom_out_at(anchor_idx, anchor_rel)

_set_visible_anchored(...) internal helper

Emits:

viewport_changed whenever range changes (pan/zoom/total/etc.)

Used by:

ChartRenderSurface

VolumeRenderSurface

OscillatorRenderSurface

panes overlays (for updates)

leonardo/gui/chart/crosshair.py — Crosshair(QObject)

Role: Shared crosshair state across panes.

State (current concept):

shared index → drives the vertical line everywhere

hover_on_price → tells ChartRenderSurface whether to draw its horizontal line

Signals:

changed (most commonly used)

cleared (less used now because we avoid flicker between panes)

Used by:

ChartRenderSurface

VolumeRenderSurface

OscillatorRenderSurface

all panes overlays (to update values at index)

Chart data model (GUI-local for now)
leonardo/gui/chart/model.py — ChartModel

Role: Holds:

candles

volume

overlays (indicators)

oscillators (series by key)

Used by:

ChartWorkspaceWidget (ownership)

PricePane overlay reads overlays

OscillatorPane uses oscillator series values

leonardo/gui/chart/dummy_data.py

Role: Generates fake data:

make_dummy_candles()

make_dummy_volume()

make_dummy_oscillator()

Used by:

ChartWorkspaceWidget during initialization

Auxiliary windows
leonardo/gui/windows_inspector.py — WindowsInspectorWindow(QMainWindow)

Role: Diagnostic window showing registry-truth list of open windows.

Behavior:

polls every 500ms

calls core thread-safely via CoreBridge.submit()

uses ctx.state.windows_state() snapshot (copy)

renders into QTableWidget: Name / Type / Open

Calls into:

AppContext.state.windows_state()

Current interaction rules (canonical)
Crosshair

The vertical line is global: driven by Crosshair.index and drawn on all panes.

The horizontal line:

On chart: shown only when hovering chart plot (mouse Y)

On volume/osc: always value-based at series[idx] (not mouse Y)

Volume/osc horizontal lines are always shown when crosshair is active (driven by index)

Zoom

Mouse wheel zoom changes X range via ChartViewport.zoom_*_at(...), anchored at mouse X.

This wheel zoom can be used on chart/volume/osc panes (same mechanics).

Anchor Zoom toggle:

ON: chart auto-scales Y to visible candles (TradingView-style “anchored”)

OFF: chart enters free Y mode:

drag right axis = Y zoom

shift + drag right axis = Y pan

volume/osc remain naturally constrained (still behave “anchored” vertically)

############################################################################

DEPENDENCY DIAGRAM GUI

gui/app.py (bootstrap)
└─ MainWindow (QMainWindow)
   ├─ ChartWorkspaceWidget (central widget)
   │  ├─ ChartModel
   │  │  ├─ candles (List[Candle])
   │  │  ├─ volume (List[float])
   │  │  ├─ overlays (Series dict)
   │  │  └─ oscillators (Series dict)
   │  ├─ ChartViewport (shared X viewport + anchor flag)
   │  ├─ Crosshair (shared crosshair state)
   │  └─ QSplitter (Vertical)
   │     ├─ PricePane
   │     │  ├─ ChartRenderSurface
   │     │  └─ _PaneOverlay
   │     ├─ VolumePane (optional)
   │     │  ├─ VolumeRenderSurface
   │     │  └─ _PaneOverlay
   │     └─ OscillatorPane(s) (0..N)
   │        ├─ OscillatorRenderSurface
   │        └─ _PaneOverlay
   ├─ Menu actions (QAction)
   └─ QTimer (audit polling)


MainWindow
├─ _on_toggle_volume(bool) ───────────────→ ChartWorkspaceWidget.set_volume_enabled()
├─ _add_osc(key,title) ───────────────────→ ChartWorkspaceWidget.add_oscillator()
├─ _clear_osc() ──────────────────────────→ ChartWorkspaceWidget.clear_oscillators()
├─ _on_anchor_zoom_toggled(bool) ─────────→ ChartWorkspaceWidget.set_anchor_zoom_enabled()
│                                           └→ ChartViewport.set_anchor_zoom_enabled()
├─ on_core_started() ─────────────────────→ core state: ctx.state.window_open("main"...)
├─ closeEvent() ──────────────────────────→ core state: ctx.state.window_close("main"...)
│                                           └→ CoreBridge.stop()
└─ _open_windows_inspector() ─────────────→ WindowManager.open_windows_inspector()


ChartRenderSurface (price)
├─ mouseMoveEvent
│  ├─ ChartViewport.index_from_x(...) ─────→ idx
│  └─ Crosshair.set(...) / set_index(...)  → shared crosshair index updated
├─ wheelEvent
│  └─ ChartViewport.zoom_in_at/out_at(...) → updates start/visible → viewport_changed
├─ axis drag (when anchor OFF)
│  └─ modifies local _y_lo/_y_hi (free Y)  → update()
└─ paintEvent
   ├─ reads ChartViewport.start/end
   ├─ draws candles
   └─ reads Crosshair.index / hover_on_price
      ├─ draw shared vertical line (index)
      └─ draw price horizontal line (mouse Y only if hover_on_price)


VolumeRenderSurface
├─ mouseMoveEvent
│  ├─ ChartViewport.index_from_x(...) ─────→ idx
│  └─ Crosshair.set_index(idx)
│     └─ Crosshair.set_hover_on_price(False)
├─ wheelEvent
│  └─ ChartViewport.zoom_in_at/out_at(...)
└─ paintEvent
   ├─ reads ChartViewport.start/end
   ├─ draws volume bars
   └─ reads Crosshair.index
      ├─ draw shared vertical line (index)
      └─ draw horizontal line at volume[idx] (value-based)


OscillatorRenderSurface
├─ mouseMoveEvent
│  ├─ ChartViewport.index_from_x(...) ─────→ idx
│  └─ Crosshair.set_index(idx)
│     └─ Crosshair.set_hover_on_price(False)
├─ wheelEvent
│  └─ ChartViewport.zoom_in_at/out_at(...)
└─ paintEvent
   ├─ reads ChartViewport.start/end
   ├─ draws oscillator polyline
   └─ reads Crosshair.index
      ├─ draw shared vertical line (index)
      └─ draw horizontal line at values[idx] (value-based)


PricePane._update_overlay()
└─ idx = Crosshair.index (fallback to last candle)
   ├─ reads ChartModel.candles[idx] → OHLC line1
   └─ reads ChartModel.overlays()[*].values[idx] → line2 (overlay indicators)


VolumePane._update_overlay()
└─ idx = Crosshair.index (fallback last)
   └─ reads volume[idx] → "Vol: ..."


OscillatorPane._update_overlay()
└─ idx = Crosshair.index (fallback last)
   └─ reads values[idx] → "<val>"


ChartViewport.viewport_changed ─→ surfaces.update(), panes._update_overlay()
Crosshair.changed / cleared     ─→ surfaces.update(), panes._update_overlay()


MainWindow.on_core_started()
└─ CoreBridge.submit(ctx.state.window_open("main","MainWindow"...))

MainWindow.closeEvent()
└─ CoreBridge.submit(ctx.state.window_close("main"...))

WindowsInspectorWindow.refresh() [timer every 500ms]
└─ CoreBridge.submit(ctx.state.windows_state()) → snapshot
   └─ renders table rows


MainWindow._open_windows_inspector()
└─ ctx.registry.get(SVC_GUI_WINDOW_MANAGER) → wm
   └─ wm.open_windows_inspector() → creates WindowsInspectorWindow
   
      