from __future__ import annotations

from pathlib import Path

import run_doctr as base


HERE = Path(__file__).resolve().parent
base.SOURCE = (
    HERE.parent
    / "region_split"
    / "artifacts"
    / "scheda_catastale"
    / "page_0001"
    / "revision_002"
    / "region_002.png"
)
base.OUTPUT = (
    HERE.parent.parent
    / "industrial_v1"
    / "text_geometry_guard"
    / "artifacts"
    / "scheda_catastale"
    / "region_002"
    / "revision_001"
    / "ocr_doctr"
)


if __name__ == "__main__":
    base.run()
