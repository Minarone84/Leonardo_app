from __future__ import annotations

import argparse
import os
import zipfile
from pathlib import Path

from .release_checks import run_all_checks


def _should_skip(path: Path) -> bool:
    parts = set(path.parts)
    if "__pycache__" in parts:
        return True
    if ".pytest_cache" in parts:
        return True
    if ".git" in parts:
        return True
    if path.suffix == ".pyc":
        return True
    return False


def build_clean_zip(gui_root: Path, out_zip: Path) -> None:
    failures = run_all_checks(gui_root)
    if failures:
        msgs = "\n".join(f"[{f.code}] {f.path}: {f.detail}" for f in failures)
        raise SystemExit(f"Refusing to package: release checks failed:\n{msgs}")

    out_zip.parent.mkdir(parents=True, exist_ok=True)

    base_dir = gui_root.parent  # directory containing "gui/"
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in base_dir.rglob("*"):
            if p.is_dir():
                continue
            if _should_skip(p):
                continue
            rel = p.relative_to(base_dir)
            z.write(p, rel.as_posix())


def main() -> int:
    parser = argparse.ArgumentParser(description="Package a clean GUI zip after running release checks.")
    parser.add_argument("--gui-root", default=None, help="Path to the gui/ folder (defaults to this package's gui/).")
    parser.add_argument("--out", required=True, help="Output zip path.")
    args = parser.parse_args()

    gui_root = Path(args.gui_root).resolve() if args.gui_root else Path(__file__).resolve().parents[1]
    out_zip = Path(args.out).resolve()

    build_clean_zip(gui_root, out_zip)
    print(f"OK: wrote {out_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
