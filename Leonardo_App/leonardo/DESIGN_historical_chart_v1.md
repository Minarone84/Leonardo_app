Updated README (Historical Chart v1)

You should replace the content of the current README with this updated version.

Leonardo
DESIGN — Historical Chart v1

Version: v1
Date: 2026-03-04
Scope: Historical Data Visualization (OHLC + Volume, multi-tab ready, async)

Reference: 

DESIGN_historical_chart_v1

1. Purpose

The Historical Chart v1 provides a GUI environment for visualizing stored OHLCV data from the historical dataset.

It is designed as a visual research interface, not an analysis engine.

The chart window allows:

• Visualization of stored OHLC candles
• Volume histogram display
• Async data loading from Core
• Safe GUI/Core thread separation
• Foundation for future chart features

The component is intentionally separated from:

• backtesting
• indicators
• signal generation
• strategy analysis

These systems will integrate later.

2. Architectural Principles
2.1 Separation of Concerns

Two independent layers exist.

Visualization (Historical Chart)

Operates only on windowed data slices.

Constraints:

• Maximum visible candles ≤ 1000
• Buffered resident window
• Rendering only

It never computes analytical truth.

Analysis (Future subsystem)

Will operate on:

• full dataset
• deterministic indexed series
• reproducible computations

Analysis will be independent from viewport state.

2.2 Async Discipline

The GUI must never block.

Rules:

• All IO runs in the Core thread
• GUI requests operations using CoreBridge.submit()
• GUI never awaits coroutines
• Each chart tab runs independently

Future callbacks must never mutate Qt widgets directly.

All UI updates must be marshalled to the GUI thread via Qt signals.

This rule prevents Qt thread-affinity violations.

3. Implemented Components (Current Status)

The following components were implemented.

HistoricalChartWindow

GUI window responsible for:

• hosting the chart workspace
• instantiating the controller
• managing the window lifecycle

Responsibilities:

• create ChartWorkspaceWidget
• attach HistoricalChartController
• request dataset loading

The window is a top-level GUI window.

HistoricalChartController

GUI-thread controller that coordinates Core communication.

Responsibilities:

• request dataset opening
• request candle slices
• ignore stale responses
• convert slice payload → ChartSnapshot
• update chart workspace

Important constraint:

Future callbacks may execute in the Core thread, therefore the controller uses Qt signals to marshal updates back to the GUI thread.

This prevents:

QObject::setParent: Cannot set parent, new parent is in a different thread

which occurs if Qt widgets are created from the wrong thread.

ChartWorkspaceWidget

Reusable chart container used by:

• realtime chart
• historical chart

Responsibilities:

• manage shared ChartModel
• manage viewport state
• host rendering panes

Components:

PricePane
VolumePane
OscillatorPane (future use)

The workspace owns the chart model and viewport.

ChartModel

Holds GUI-side chart data:

• candles
• volume
• overlays (future)
• oscillators (future)
• trades (future)

Important design rule:

Series lists must be mutated in place so that render surfaces can safely hold references.

ChartViewport

Responsible for:

• visible window range
• zoom
• pan
• future padding
• anchor zoom behavior

Viewport state is independent per tab.

4. Windowing Model

The chart uses bounded resident windows to prevent loading entire datasets.

Constants:

VISIBLE_MAX = 1000
BUFFER_LEFT = 500
BUFFER_RIGHT = 500

Total resident target ≈ 2000 candles.

Edge Handling

Near dataset edges buffers adjust dynamically.

Oldest edge:

Left buffer shrinks
Right buffer expands

Newest edge:

Right buffer shrinks
Left buffer expands

Refill Threshold

New slices are requested only when the viewport enters a danger zone.

REFILL_THRESHOLD = 70% buffer consumed

This prevents excessive slice requests during fast pan operations.

5. Dataset Service

Historical data is served by:

HistoricalDatasetService

Responsibilities:

• dataset discovery
• CSV reading
• slice generation
• validation
• optional caching

Dataset path format:

data/historical/
    {exchange}/
        {market_type}/
            {symbol}/
                {timeframe}/
                    ohlcv/
                        candles.csv

CSV is the canonical storage format.

6. Core ↔ GUI Communication

All requests use the CoreBridge.

Pattern:

future = CoreBridge.submit(coro)
future.add_done_callback(...)

Important rule:

Callbacks must not modify Qt widgets directly.

Instead:

Core thread callback
        ↓
Qt Signal
        ↓
GUI thread slot
        ↓
apply_snapshot()
7. Current Rendering Features

Historical Chart v1 currently renders:

• OHLC candles
• Volume histogram

Indicators and oscillators are intentionally disabled in this phase.

8. State Machine (Future Multi-Tab)

Each tab will follow a defined lifecycle.

States:

NEW
OPENING_DATASET
READY
LOADING_SLICE
DISPLAYING
ERROR
CLOSED

Transitions:

NEW → OPENING_DATASET → READY → LOADING_SLICE → DISPLAYING
DISPLAYING → LOADING_SLICE → DISPLAYING
* → ERROR
* → CLOSED

User interaction allowed only in:

DISPLAYING
9. Caching Strategy (v1)

Slices may be cached by the dataset service.

Cache key:

(dataset_id, slice_range_signature)

Cache type:

LRU

Shared across tabs.

10. Concurrency Model

Core side:

• single asyncio event loop
• multiple concurrent slice requests allowed

GUI side:

• single Qt thread
• all UI mutations occur here

Tabs operate independently.

11. Addressing Model

External API uses:

center_ts_ms

Core may convert internally to:

global_index

Canonical candle identity:

ts_ms
12. Error Handling

Errors never crash the GUI.

Examples:

• dataset missing
• CSV parse failure
• corrupt data
• out-of-range slice request

Controller emits an error signal.

Future UI will display error messages.

13. Non-Goals (v1)

The historical chart does not include:

• indicator computation
• oscillator layers
• strategy execution
• backtesting
• live stream merge

These will be added later.

14. Role in the Leonardo Architecture

The Historical Chart provides the foundation chart engine.

Once stabilized, the Realtime Chart will be refactored to reuse the same system.

This ensures:

• consistent rendering behavior
• shared viewport logic
• shared chart model
• minimal duplication