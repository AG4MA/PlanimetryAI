from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from industrial_v1.core.contracts import ContractViolation

from ..application.batch_service import run_job
from ..application.contracts import JobContractError


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(
        description="Run and atomically publish the PlanParser topology engine."
    )
    command.add_argument("--job", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--planparser-root", type=Path)
    return command


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = run_job(
            job_path=args.job,
            output=args.output,
            planparser_root=args.planparser_root,
        )
    except (
        ContractViolation,
        JobContractError,
        FileNotFoundError,
        PermissionError,
        OSError,
        ValueError,
    ) as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": {
                        "code": "TOPOLOGY_ENGINE_JOB_REJECTED",
                        "message": str(exc),
                        "exception_type": type(exc).__name__,
                    },
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            {
                "status": "completed",
                "target": str(result.target),
                "manifest": str(result.manifest_path),
                "manifest_sha256": result.manifest_sha256,
                "artifact_count": len(result.artifacts),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


__all__ = ["main", "parser"]
