from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from .contracts import ContractViolation, canonical_json_bytes


def create_directory_exclusive(path: Path) -> None:
    """Create a run/revision directory and refuse any pre-existing target."""
    try:
        path.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise ContractViolation(f"Refusing to reuse existing directory: {path}") from exc


def write_bytes_atomic_exclusive(destination: Path, payload: bytes) -> None:
    """Publish complete bytes atomically without ever replacing a destination.

    A same-directory temporary file is created with O_EXCL, fsynced, and then
    hard-linked into its final name. Creating the hard link is atomic and fails
    if the final path already exists. There is deliberately no unsafe fallback.
    """
    destination = destination.resolve()
    if not destination.parent.is_dir():
        raise ContractViolation(f"Destination parent does not exist: {destination.parent}")
    temporary = destination.parent / f".{destination.name}.{uuid.uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    descriptor = None
    try:
        descriptor = os.open(temporary, flags, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError as exc:
            raise ContractViolation(f"Refusing to overwrite: {destination}") from exc
        except OSError as exc:
            raise ContractViolation(
                f"Atomic exclusive publication is unavailable for {destination}: {exc}"
            ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def write_json_atomic_exclusive(destination: Path, value: Any) -> None:
    payload = canonical_json_bytes(value) + b"\n"
    write_bytes_atomic_exclusive(destination, payload)


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)
