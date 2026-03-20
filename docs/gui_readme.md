Leonardo GUI Architecture (Current State)

Version: v2.1  
Date: 2026-03-20  

------------------------------------------------------------
OVERVIEW
------------------------------------------------------------

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

Pane system is **layout-managed**, not passive.

Three pane types:

• PricePane  
• VolumePane  
• OscillatorPane  

Key concept:

Layout is owned by the workspace, not by studies.


------------------------------------------------------------
OSCILLATOR PANE MANAGEMENT
------------------------------------------------------------

Oscillator panes are fully managed.

Workspace owns:

• _oscillator_panes_by_id  
• _oscillator_states_by_id  
• _oscillator_pane_order  
• _study_to_pane_id  

Each pane corresponds to a **study instance**.

Current rule:

• 1 study → 1 pane  
• 1 study → N series supported  


------------------------------------------------------------
STUDY SYSTEM (UPDATED)
------------------------------------------------------------

ChartStudyRegistry (per panel):

• tracks studies  
• resolves render keys  
• manages lifecycle  

Study properties:

• instance_id  
• pane_target  
• computation config  
• style  
• runtime state  
• render_keys  


------------------------------------------------------------
STUDY TYPES (NEW)
------------------------------------------------------------

Three study families exist:

• Indicators  
• Oscillators  
• Constructs  

---

### Indicators

• overlay-rendered  
• price-pane attached  

---

### Oscillators

• rendered in dedicated panes  
• pane-managed  

---

### Constructs (NEW)

Constructs are analysis-oriented tools.

They are NOT defined by rendering.

They may be:

• overlay constructs (price pane)  
• oscillator constructs (lower pane)  
• non-visual constructs (no rendering)  


------------------------------------------------------------
RENDERING MODEL (CRITICAL UPDATE)
------------------------------------------------------------

Rendering is **behavior-driven**, not family-driven.

Old assumption:

indicator → overlay  
oscillator → pane  

New system:

Each study declares:

• output_mode  
    - overlay  
    - oscillator-pane  
    - non-visual  

Panel resolves:

• pane target  
• rendering path  
• lifecycle behavior  


------------------------------------------------------------
NON-VISUAL STUDIES (NEW)
------------------------------------------------------------

Non-visual studies:

• produce no renderable series  
• are still valid study instances  
• exist in ChartStudyRegistry  
• participate in lifecycle  

They:

• do NOT render  
• do NOT create panes  
• do NOT support styling  


------------------------------------------------------------
PANE LIFECYCLE
------------------------------------------------------------

Apply:

• controller computes result  
• panel registers study  
• workspace renders (if applicable)  

Remove:

• workspace removes rendering  
• study removed from registry  

Edit:

• replace-on-apply  

Style:

• visual only  
• computation untouched  


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
• applies financial tools  
• saves artifacts  

Key rule:

Apply ≠ Save  

• Apply → resident slice  
• Save → full dataset  


------------------------------------------------------------
FINANCIAL TOOL WORKFLOW
------------------------------------------------------------

FinancialToolManagerWindow:

• selects tool family  
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
• produces outputs  
• may or may not render  

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
• behavior-driven rendering  
• study-pane separation  
• shell-agnostic sessions  
• controller-driven computation  
• render-key identity mapping  


------------------------------------------------------------
KEY RULES
------------------------------------------------------------

• Studies do NOT control layout  
• Workspace owns pane system  
• Rendering is behavior-driven, not family-driven  
• Non-visual studies are valid studies  
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
• construct system (overlay / oscillator / non-visual)  
• behavior-driven rendering pipeline  
• chart-local study lifecycle  
• multi-series study support  
• render-key mapping  
• interactive pane control (edit/style/remove/move)  
• financial tool workflow with persistence  

The system is now:

• modular  
• extensible  
• layout-aware  
• behavior-driven  
• architecturally consistent  

And still somehow cooperating with you.