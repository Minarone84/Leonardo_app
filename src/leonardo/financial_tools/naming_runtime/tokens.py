from __future__ import annotations

import re
from typing import Any

def _slugify_token(value: Any) -> str:
    """
    Convert an arbitrary value into a canonical lowercase token suitable for:

    - derived column names
    - binding slugs
    - saved construct instance keys / filenames
    - canonical signal names

    Rules:
    - lowercase
    - strip leading/trailing whitespace
    - replace spaces and repeated separators with single underscores
    - keep only ASCII letters, digits, underscores, and hyphens
    - collapse repeated underscores / hyphens
    """
    text = str(value).strip().lower()
    if not text:
        return "unknown"

    text = text.replace("%", "pct")
    text = text.replace(" ", "_")
    text = text.replace("/", "_")
    text = text.replace("\\", "_")
    text = text.replace("(", "_")
    text = text.replace(")", "_")
    text = text.replace("[", "_")
    text = text.replace("]", "_")
    text = text.replace("{", "_")
    text = text.replace("}", "_")
    text = text.replace(",", "_")
    text = text.replace("=", "_")
    text = text.replace(":", "_")
    text = text.replace(";", "_")

    text = re.sub(r"[^a-z0-9_-]+", "_", text)
    text = re.sub(r"_+", "_", text)
    text = re.sub(r"-+", "-", text)
    text = text.strip("_-")

    return text or "unknown"


def build_source_token(source: Any) -> str:
    """
    Build the canonical token for a source series.

    Important rule:
    - preserve existing Leonardo chained separators ``__`` when the source is
      already a canonical derived series name

    Examples:
    - close -> close
    - EMA 14 Close -> ema_14_close
    - rsi(14)_close -> rsi_14_close
    - close__ang -> close__ang
    - close__dlt__ema_14 -> close__dlt__ema_14

    Important naming distinction
    ----------------------------
    This helper is generic. It canonicalizes source series identifiers and
    preserves already-canonical chained names.

    It is *not* the construct-family ground truth by itself.

    For active construct emitted outputs, the authoritative policy is:

    - unary derivative:
        <source>__d1
        <source>__d2

    - unary angle:
        <source>__ang

    - braids:
        <fast>_<mid>_<slow>
        <fast>_<mid>_<slow>_width
        <fast>_<mid>_<slow>_compression

    - braid_instability:
        <fast>_<mid>_<slow>_inst_{n}

    - delta:
        <fast>_<slow>_delta
        <fast>_<slow>_delta_pct

    - trap_area:
        <fast>_<slow>_trapA
        <fast>_<mid>_trapA
        etc., depending on provided roles

    - percent_span_angle:
        <source>_ang_pct_span_{window}

    - angle_momentum:
        <source>_ang_mtm_{n}
    """
    text = str(source).strip().lower()
    if not text:
        return "unknown"

    sentinel = "zzdblsepzz"
    protected = text.replace("__", sentinel)
    slugged = _slugify_token(protected)
    restored = slugged.replace(sentinel, "__")
    restored = restored.strip("_-")
    restored = re.sub(r"__+", "__", restored)

    return restored or "unknown"
