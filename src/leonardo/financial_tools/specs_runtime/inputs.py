from __future__ import annotations

from .models import DataInputSpec

OPEN_INPUT = DataInputSpec(
    name="open",
    dtype="float",
    label="Open",
    description="Open price series.",
)

HIGH_INPUT = DataInputSpec(
    name="high",
    dtype="float",
    label="High",
    description="High price series.",
)

LOW_INPUT = DataInputSpec(
    name="low",
    dtype="float",
    label="Low",
    description="Low price series.",
)

CLOSE_INPUT = DataInputSpec(
    name="close",
    dtype="float",
    label="Close",
    description="Close price series.",
)

VOLUME_INPUT = DataInputSpec(
    name="volume",
    dtype="float",
    label="Volume",
    description="Volume series. Compute layer may resolve 'Volume' or 'volume'.",
)


