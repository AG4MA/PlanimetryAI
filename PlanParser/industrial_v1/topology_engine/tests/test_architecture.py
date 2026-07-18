from __future__ import annotations

from pathlib import Path


ENGINE_ROOT = Path(__file__).resolve().parents[1]
MAX_PRODUCTION_LINES = 350
FACADE_LIMITS = {
    "pipeline.py": 60,
    "topology.py": 60,
    "document_graph.py": 60,
    "text.py": 60,
}


def _production_modules() -> list[Path]:
    return sorted(
        path
        for path in ENGINE_ROOT.rglob("*.py")
        if "tests" not in path.relative_to(ENGINE_ROOT).parts
        and "artifacts" not in path.relative_to(ENGINE_ROOT).parts
        and "__pycache__" not in path.relative_to(ENGINE_ROOT).parts
    )


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_no_production_module_can_regress_into_a_god_file() -> None:
    oversized = {
        path.relative_to(ENGINE_ROOT).as_posix(): _line_count(path)
        for path in _production_modules()
        if _line_count(path) > MAX_PRODUCTION_LINES
    }
    assert oversized == {}


def test_compatibility_facades_stay_thin() -> None:
    violations = {
        name: _line_count(ENGINE_ROOT / name)
        for name, limit in FACADE_LIMITS.items()
        if _line_count(ENGINE_ROOT / name) > limit
    }
    assert violations == {}


def test_domain_has_no_filesystem_or_publication_dependency() -> None:
    forbidden = ("from pathlib import Path", "import pathlib", "publication import")
    violations: dict[str, list[str]] = {}
    for path in sorted((ENGINE_ROOT / "domain").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        hits = [token for token in forbidden if token in source]
        if hits:
            violations[path.name] = hits
    assert violations == {}


def test_cli_has_no_compute_or_rendering_dependency() -> None:
    source = (ENGINE_ROOT / "interfaces" / "cli.py").read_text(encoding="utf-8")
    for forbidden in ("import cv2", "import numpy", "from PIL", "compute_region"):
        assert forbidden not in source
