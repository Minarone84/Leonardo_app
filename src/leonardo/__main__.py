from __future__ import annotations

import asyncio
import sys

from leonardo.core.app import LeonardoApp


def main() -> int:
    try:
        asyncio.run(LeonardoApp.run_main())
        return 0
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
