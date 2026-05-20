from __future__ import annotations

from leonardo.financial_tools.tool_contracts.contracts import (
    BehaviorContract,
    DataInputContract,
    OscillatorGuideLevelContract,
    OscillatorVisualContract,
    OutputContract,
    OutputSignalContract,
    ParamContract,
    ToolContract,
)

HIGH = DataInputContract("high", "float", label="High")
LOW = DataInputContract("low", "float", label="Low")
CLOSE = DataInputContract("close", "float", label="Close")
VOLUME = DataInputContract("volume", "float", label="Volume")

OSC = BehaviorContract("oscillator-pane", chart_renderable=True, supports_style=True, supports_pane_layout=True)
PERIOD = ParamContract("period", "int", default=14, minimum=1, label="Period")
VOLUME_MEAN_PERIOD = ParamContract("period", "int", default=20, minimum=1, label="Mean Period")
ARSI_METHOD = ParamContract(
    "method",
    "str",
    default="RMA",
    label="Method",
    choices=("EMA", "SMA", "RMA", "TMA"),
)
ARSI_SIGNAL_PERIOD = ParamContract(
    "signal_period",
    "int",
    default=14,
    minimum=1,
    label="Signal Period",
)
ARSI_SIGNAL_METHOD = ParamContract(
    "signal_method",
    "str",
    default="EMA",
    label="Signal Method",
    choices=("EMA", "SMA", "RMA", "TMA"),
)
BOUNDED = OscillatorVisualContract(
    range_mode="fixed_bounds",
    bounds=(0.0, 100.0),
    guide_levels=(
        OscillatorGuideLevelContract("overbought", 70.0, label="Overbought"),
        OscillatorGuideLevelContract("center", 50.0, label="Center"),
        OscillatorGuideLevelContract("oversold", 30.0, label="Oversold"),
    ),
)
ARSI_BOUNDED = OscillatorVisualContract(
    range_mode="fixed_bounds",
    bounds=(0.0, 100.0),
    guide_levels=(
        OscillatorGuideLevelContract("overbought", 80.0, label="Overbought"),
        OscillatorGuideLevelContract("center", 50.0, label="Center"),
        OscillatorGuideLevelContract("oversold", 20.0, label="Oversold"),
    ),
)
ZERO_CENTERED = OscillatorVisualContract(
    range_mode="auto",
    bounds=None,
    guide_levels=(OscillatorGuideLevelContract("zero", 0.0, label="Zero"),),
)
UNBOUNDED = OscillatorVisualContract(range_mode="auto", bounds=None)

def line(resolver: str) -> OutputContract:
    return OutputContract(
        structure="line-series",
        naming_resolver=resolver,
        signals=(OutputSignalContract(),),
    )

def multi(resolver: str, count: int) -> OutputContract:
    return OutputContract(
        structure="multi-line-series",
        naming_resolver=resolver,
        signals=tuple(OutputSignalContract() for _ in range(count)),
    )

OSCILLATOR_CONTRACTS: dict[str, ToolContract] = {
    "rsi": ToolContract(
        family="oscillator",
        key="rsi",
        title="RSI",
        data_inputs=(CLOSE,),
        params=(PERIOD,),
        behavior=OSC,
        output=line("oscillator:rsi"),
        oscillator_visual=BOUNDED,
        description="Wilder RSI.",
    ),
    "arsi": ToolContract(
        family="oscillator",
        key="arsi",
        title="ARSI",
        data_inputs=(CLOSE,),
        params=(PERIOD, ARSI_METHOD, ARSI_SIGNAL_PERIOD, ARSI_SIGNAL_METHOD),
        behavior=OSC,
        output=OutputContract(
            structure="multi-line-series",
            naming_resolver="oscillator:arsi",
            signals=(
                OutputSignalContract(label="ARSI", semantic_role="primary"),
                OutputSignalContract(label="ARSI Signal", semantic_role="signal"),
            ),
        ),
        oscillator_visual=ARSI_BOUNDED,
        description="Ultimate RSI-style ARSI with configurable main and signal smoothing.",
    ),
    "tdirsi": ToolContract(
        family="oscillator",
        key="tdirsi",
        title="TDI RSI",
        data_inputs=(CLOSE,),
        params=(
            PERIOD,
            ParamContract("band_length", "int", default=34, minimum=1),
            ParamContract("band_mult", "float", required=False, default=1.6185, minimum=0.000001),
            ParamContract("fast_len", "int", required=False, default=2, minimum=1),
            ParamContract("slow_len", "int", required=False, default=7, minimum=1),
            ParamContract("fast_smo", "str", required=False, default="EMA", choices=("EMA", "RMA", "SMA")),
            ParamContract("slow_smo", "str", required=False, default="RMA", choices=("EMA", "RMA", "SMA")),
        ),
        behavior=OSC,
        output=multi("oscillator:tdirsi", 5),
        oscillator_visual=BOUNDED,
        description="Traders Dynamic Index based on RSI.",
    ),
    "smi": ToolContract(
        family="oscillator",
        key="smi",
        title="SMI",
        data_inputs=(HIGH, LOW, CLOSE),
        params=(ParamContract("k_length", "int", default=14, minimum=1), ParamContract("d_length", "int", default=3, minimum=1)),
        behavior=OSC,
        output=multi("oscillator:smi", 2),
        oscillator_visual=ZERO_CENTERED,
        description="Stochastic Momentum Index.",
    ),
    "mfi": ToolContract(
        family="oscillator",
        key="mfi",
        title="MFI",
        data_inputs=(HIGH, LOW, CLOSE, VOLUME),
        params=(PERIOD,),
        behavior=OSC,
        output=line("oscillator:mfi"),
        oscillator_visual=BOUNDED,
        description="Money Flow Index.",
    ),
    "obv": ToolContract(
        family="oscillator",
        key="obv",
        title="OBV",
        data_inputs=(CLOSE, VOLUME),
        params=(),
        behavior=OSC,
        output=line("oscillator:obv"),
        oscillator_visual=UNBOUNDED,
        description="On-Balance Volume.",
    ),
    "volume": ToolContract(
        family="oscillator",
        key="volume",
        title="Volume",
        data_inputs=(VOLUME,),
        params=(VOLUME_MEAN_PERIOD,),
        behavior=OSC,
        output=multi("oscillator:volume", 2),
        oscillator_visual=UNBOUNDED,
        description="Raw traded volume with configurable rolling mean.",
    ),
}
