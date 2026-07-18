from __future__ import annotations

import runpy
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
STAGING = HERE.parent / ".staging"
ORIGINAL_MKDTEMP = tempfile.mkdtemp


def workspace_mkdtemp(prefix: str = "", suffix: str = "", dir: str | None = None) -> str:
    STAGING.mkdir(parents=True, exist_ok=True)
    return ORIGINAL_MKDTEMP(prefix=prefix, suffix=suffix, dir=STAGING)


tempfile.mkdtemp = workspace_mkdtemp
runpy.run_path(str(HERE / "build_tiles_revision_001.py"), run_name="__main__")
