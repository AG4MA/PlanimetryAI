"""Backward-compatible facade for topology-engine application services."""

from __future__ import annotations

from .application.batch_service import RegionExecution, execute_region, run_job
from .application.contracts import JOB_SCHEMA_VERSION, JobContractError
from .application.region_analysis import RegionComputation, compute_region
from .application.region_rendering import RegionRendering, render_region
from .interfaces.cli import main


__all__ = [
    "JOB_SCHEMA_VERSION",
    "JobContractError",
    "RegionComputation",
    "RegionExecution",
    "RegionRendering",
    "compute_region",
    "execute_region",
    "main",
    "render_region",
    "run_job",
]


if __name__ == "__main__":
    raise SystemExit(main())
