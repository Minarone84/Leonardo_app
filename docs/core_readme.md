Leonardo Core Architecture (Current State)

Overview

The Leonardo Core layer is responsible for:

• data access  
• dataset structure  
• historical slicing  
• financial computation  
• artifact persistence  

It is completely independent from the GUI.

The core is designed to support:

• large historical datasets  
• partial data loading (slice-based)  
• deterministic computation  
• reproducible financial tool outputs  

The core must never depend on GUI state or rendering logic.


------------------------------------------------------------
CORE RESPONSIBILITIES
------------------------------------------------------------

The core layer is responsible for:

• loading historical datasets  
• managing dataset identity  
• slicing large datasets efficiently  
• computing financial tools (indicators, oscillators, constructs)  
• persisting derived artifacts  
• exposing clean interfaces to controllers  

The core is NOT responsible for:

• rendering  
• chart layout  
• pane management  
• user interaction  


------------------------------------------------------------
DATASET MODEL
------------------------------------------------------------

Canonical dataset structure:

data/historical/{exchange}/{market_type}/{symbol}/{timeframe}/ohlcv/candles.csv

Example:

data/historical/bybit/linear/BTCUSDT/1h/ohlcv/candles.csv


Dataset Identity

A dataset is uniquely defined by:

• exchange  
• market_type  
• symbol  
• timeframe  

This identity is used across:

• loading  
• computation  
• persistence  


------------------------------------------------------------
SLICE SYSTEM (CRITICAL)
------------------------------------------------------------

Large datasets are not loaded entirely.

Instead, the core provides **resident slices**.

Definitions:

Dataset  
Full dataset on disk.

Slice  
Subset of dataset loaded into memory.

Viewport  
Visible region (managed by GUI).


Slice Payload

Each slice provides:

• candles  
• base_index  
• has_more_left  
• has_more_right  


Key invariant:

global_index = base_index + local_index


The core guarantees:

• consistent indexing across slices  
• deterministic slice boundaries  
• safe navigation across dataset edges  


------------------------------------------------------------
SLICE LOADING
------------------------------------------------------------

The controller requests slices based on:

• viewport center  
• navigation direction  

The core returns:

• a centered slice  
• metadata for further navigation  


The core does NOT:

• track viewport  
• trigger refills  
• manage navigation state  

That responsibility belongs to the controller.


------------------------------------------------------------
FINANCIAL TOOL SYSTEM
------------------------------------------------------------

The core computes financial tools.

Tool families:

• indicators (price overlays)  
• oscillators (separate series)  
• constructs (future expansion)  


Each tool defines:

• input parameters  
• computation logic  
• output series  


------------------------------------------------------------
COMPUTATION MODEL
------------------------------------------------------------

Financial tools operate on:

• candle arrays  
• optional auxiliary data  

They produce:

• one or more output series  


Important:

The core is **multi-series aware**.

Examples:

• SMA → 1 series  
• RSI → 1 series  
• MACD → multiple series  


The core does NOT:

• assign render keys  
• manage chart studies  
• manage panes  

It only returns raw computed series.


------------------------------------------------------------
APPLY VS SAVE (CRITICAL RULE)
------------------------------------------------------------

The system enforces strict separation:

Apply:

• operates on resident slice  
• fast  
• not persisted  
• used for chart interaction  

Save:

• operates on full dataset  
• deterministic  
• persisted to disk  
• used for reproducible analysis  


The core supports both modes explicitly.


------------------------------------------------------------
ARTIFACT PERSISTENCE
------------------------------------------------------------

Derived artifacts are stored alongside canonical data.

Structure:

data/historical/{exchange}/{market_type}/{symbol}/{timeframe}/

Subfolders:

• indicators  
• oscillators  
• constructs  


Examples:

sma__period-20.csv  
rsi__period-14.csv  


Rules:

• one file per configured tool  
• naming encodes parameters  
• artifacts are deterministic  


------------------------------------------------------------
PERSISTENCE CONTRACT
------------------------------------------------------------

The core guarantees:

• reproducible outputs for same inputs  
• stable file structure  
• deterministic naming  


The core does NOT:

• handle overwrite confirmation  
• show dialogs  
• manage user decisions  

Those belong to the GUI.


------------------------------------------------------------
CONTROLLER INTERACTION
------------------------------------------------------------

The core is accessed via controllers.

Example:

HistoricalChartController


Controller responsibilities:

• request slices  
• call computation  
• apply results to GUI  
• trigger persistence  


The core only provides:

• data  
• computation  
• storage  


------------------------------------------------------------
ERROR HANDLING
------------------------------------------------------------

The core reports:

• computation errors  
• file errors  
• dataset issues  

It returns structured error information.

The GUI decides:

• how to display errors  
• how to notify users  


------------------------------------------------------------
ARCHITECTURAL PRINCIPLES
------------------------------------------------------------

The core enforces:

• determinism  
• reproducibility  
• stateless computation  
• dataset identity consistency  
• separation from GUI  


------------------------------------------------------------
KEY RULES
------------------------------------------------------------

• Core must never depend on GUI  
• Core must not know about panes or rendering  
• Core must not manage chart state  
• Computation must be deterministic  
• Apply and Save must remain separate  
• Slice indexing must remain consistent  


------------------------------------------------------------
SUMMARY
------------------------------------------------------------

The Leonardo Core provides:

• scalable dataset access  
• efficient slice-based loading  
• deterministic financial computation  
• structured artifact persistence  

It is:

• independent  
• reusable  
• predictable  

The core is the foundation.

If this layer breaks, everything above it becomes chaos.