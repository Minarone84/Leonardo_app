from __future__ import annotations

from typing import Protocol

from leonardo.core.context import AppContext


class Service(Protocol):
    name: str

    async def start(self, ctx: AppContext) -> None: ...
    async def stop(self, ctx: AppContext) -> None: ...
