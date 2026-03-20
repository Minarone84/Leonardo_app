Leonardo GUI Architecture (Current State)

Overview

The Leonardo GUI provides the visualization layer for both historical and real-time charting.

It is built around a modular chart engine capable of rendering large datasets using resident slices and a global index model.

The GUI supports two chart deployment models:

• Embedded historical chart panels managed by a workspace window  
• Independent top-level chart windows (floating historical charts and future realtime charts)

Both models use the same underlying chart engine.

The GUI architecture separates four concerns:

• chart session (data + viewport + rendering)  
• workspace management (layout + pane system)  
• shell window (top-level OS window behavior)  
• financial tool workflow (selection, configuration, apply/save review, persistence feedback)

This separation allows:

• charts to move between embedded and floating states without losing session state  
• financial tools to be configured without coupling GUI to compute/storage  
• rendering, layout, and computation to evolve independently  


------------------------------------------------------------
HISTORICAL WORKSPACE MODEL
------------------------------------------------------------

Historical charts are primarily managed inside:

HistoricalDataManagerWindow

This window hosts a workspace capable of managing up to four charts.

Each chart is implemented as:

HistoricalChartPanel


------------------------------------------------------------
CHART PANEL
------------------------------------------------------------

HistoricalChartPanel is the chart session unit.

It owns:

• ChartWorkspaceWidget  
• HistoricalChartController  
• dataset identity  
• chart-local actions  
• financial tool entrypoint  
• ChartStudyRegistry  

The panel is:

• reusable  
• shell-agnostic  
• the owner of study lifecycle  


------------------------------------------------------------
EMBEDDED MODE
------------------------------------------------------------

Created via:

File → New Chart

Managed by:

HistoricalWorkspaceWidget

Layout policy:

1 chart → full  
2 charts → split  
3 charts → 2x2 (one empty)  
4 charts → full 2x2  


------------------------------------------------------------
FLOATING MODE
------------------------------------------------------------

Panels can detach:

Panel → Float  
→ removed from workspace  
→ reparented into HistoricalChartWindow  

Dock back:

Panel → Dock  
→ reinserted into workspace  
→ floating window closes  

Same session persists.


------------------------------------------------------------
WINDOW MANAGER
------------------------------------------------------------

Manages all top-level windows:

• MainWindow  
• HistoricalDataManagerWindow  
• HistoricalChartWindow  
• FinancialToolManagerWindow  
• others  

Embedded panels are NOT tracked.


------------------------------------------------------------
CHART WORKSPACE ARCHITECTURE
------------------------------------------------------------

ChartWorkspaceWidget is the core rendering container.

Owns:

• ChartModel  
• ChartViewport  
• Crosshair  
• Pane stack (QSplitter)  

Structure:

ChartWorkspaceWidget  
    PricePane  
    VolumePane (optional)  
    OscillatorPane(s)

All panes share:

• viewport  
• crosshair  


------------------------------------------------------------
PANE SYSTEM (UPDATED)
------------------------------------------------------------

Pane system is now **layout-managed**, not passive.

Three pane types:

• PricePane  
• VolumePane  
• OscillatorPane  

Key concept:

Layout is owned by the workspace, not by studies.


------------------------------------------------------------
OSCILLATOR PANE MANAGEMENT (NEW)
------------------------------------------------------------

Oscillator panes are now fully managed.

Workspace owns:

• _oscillator_panes_by_id  
• _oscillator_states_by_id  
• _oscillator_pane_order  
• _study_to_pane_id  

Each pane corresponds to a **study instance**.

Current rule:

• 1 study → 1 pane  
• 1 study → N series supported  

Pane state includes:

• pane_id  
• study_instance_id  
• title  
• render_keys  
• preferred_height  


------------------------------------------------------------
PANE LIFECYCLE
------------------------------------------------------------

Apply:

• controller computes series  
• panel applies study  
• workspace creates or updates pane  

Remove:

• workspace removes pane  
• series removed from model  

Edit:

• replace-on-apply  
• pane reused or recreated  

Style:

• visual only  
• no layout impact  


------------------------------------------------------------
PANE LAYOUT MANAGEMENT
------------------------------------------------------------

Panes are stacked vertically in a splitter.

Workspace is responsible for:

• pane order  
• pane sizing  
• layout rebuilds  
• visibility  

Height persistence:

• captured before layout changes  
• restored after rebuild  

Important rule:

A pane must never be created with zero height.


------------------------------------------------------------
PANE REORDERING
------------------------------------------------------------

Users can:

• move pane up  
• move pane down  

Implementation:

• reorder internal list  
• rebuild splitter  
• reapply sizes  


------------------------------------------------------------
LEGACY OSCILLATOR PATH
------------------------------------------------------------

Legacy system still exists:

• _oscillators map  
• series-based panes  

This is:

• backward compatibility only  
• not used by new study system  


------------------------------------------------------------
SHARED STATE OBJECTS
------------------------------------------------------------

ChartViewport

Controls visible slot range.

Supports:

• pan  
• zoom  
• anchor zoom  
• future padding  


Crosshair

Shared across panes.

• vertical line shared  
• horizontal line per pane  


ChartModel

Stores:

• candles  
• volume  
• overlays  
• oscillators  

Includes:

resident_base_index


------------------------------------------------------------
HISTORICAL ENGINE
------------------------------------------------------------

Uses:

• resident slice model  
• global dataset indexing  

global_index = resident_base_index + local_index  

Allows:

• large dataset handling  
• smooth navigation  


------------------------------------------------------------
CONTROLLER
------------------------------------------------------------

HistoricalChartController:

• loads dataset  
• manages slices  
• applies studies  
• saves artifacts  

Key rule:

Apply ≠ Save  

• Apply → resident slice  
• Save → full dataset  


------------------------------------------------------------
RENDERING SYSTEM
------------------------------------------------------------

Price:

• candlesticks  
• overlays  
• crosshair  

Volume:

• bars  
• value lines  

Oscillator:

• multi-series rendering  
• crosshair  
• value display  

All panes share viewport mapping.


------------------------------------------------------------
FINANCIAL TOOL WORKFLOW
------------------------------------------------------------

FinancialToolManagerWindow:

• selects tool  
• configures parameters  
• emits intent  

Apply:

• compute on slice  
• render immediately  

Save:

• compute full dataset  
• persist CSV  
• show result  


------------------------------------------------------------
STUDY SYSTEM (UPDATED)
------------------------------------------------------------

ChartStudyRegistry (per panel):

• tracks studies  
• resolves render keys  
• manages lifecycle  

Study properties:

• instance_id  
• computation config  
• style  
• runtime state  
• render_keys (multi-series support)  


------------------------------------------------------------
RENDER KEY MODEL
------------------------------------------------------------

Render keys are:

• unique per series  
• mapped to study instance  

Used for:

• edit  
• remove  
• style  

They are the ONLY bridge between UI and study.


------------------------------------------------------------
STUDY VS PANE (CRITICAL DISTINCTION)
------------------------------------------------------------

Study:

• defines computation  
• produces series  
• pane-agnostic  

Pane:

• layout container  
• owned by workspace  
• visual grouping only  

Mixing these responsibilities breaks the architecture.


------------------------------------------------------------
INTERACTION MODEL
------------------------------------------------------------

User actions:

• Edit  
• Style  
• Remove  
• Move pane  

Signals:

• study_edit_requested(instance_id)  
• study_style_requested(instance_id)  
• study_remove_requested(instance_id)  
• pane_move_up_requested(instance_id)  
• pane_move_down_requested(instance_id)  


------------------------------------------------------------
ARCHITECTURAL PRINCIPLES
------------------------------------------------------------

The system enforces:

• global dataset indexing  
• resident slice rendering  
• viewport continuity  
• pane-managed layout  
• study-pane separation  
• shell-agnostic sessions  
• controller-driven computation  
• render-key identity mapping  


------------------------------------------------------------
KEY RULES
------------------------------------------------------------

• Studies do NOT control layout  
• Workspace owns pane system  
• Render keys are the only identity bridge  
• Apply and Save are fundamentally different  
• Style does not trigger computation  
• Layout does not affect computation  


------------------------------------------------------------
SUMMARY
------------------------------------------------------------

The GUI now provides:

• multi-chart workspace  
• detachable chart sessions  
• pane-managed oscillator system  
• chart-local study lifecycle  
• multi-series study support  
• render-key mapping  
• interactive pane control (edit/style/remove/move)  
• financial tool workflow with persistence  

The system is now:

• modular  
• extensible  
• layout-aware  
• architecturally consistent  

And, for once, not actively trying to sabotage you.