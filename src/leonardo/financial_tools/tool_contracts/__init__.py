"""Formal financial-tool contract layer.

Tool contracts are the editable, typed structural declarations for indicators,
oscillators, and constructs. They are intentionally separate from compute
runtime modules, naming implementation, and GUI/spec projections.
"""

from .contracts import *
from .registry import *
