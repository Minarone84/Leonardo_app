from __future__ import annotations

import tomllib
from pathlib import Path


def test_pyproject_declares_core_runtime_dependencies() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = set(pyproject["project"]["dependencies"])
    assert {
        "PySide6",
        "aiohttp",
        "numpy",
        "pandas",
        "websockets",
    }.issubset(dependencies)
