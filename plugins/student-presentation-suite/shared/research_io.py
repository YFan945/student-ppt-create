"""Small atomic/locked JSON operations for research checkpoints and receipts."""
from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 10
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - path.stat().st_mtime > 300:
                    path.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Research state lock is busy: {path}")
            time.sleep(0.02)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for attempt in range(5):
            try:
                os.replace(temporary, path)
                break
            except OSError as exc:
                # Windows readers/virus scanners may briefly hold the destination.
                # Keep replacement atomic; permanent access errors still propagate.
                if getattr(exc, "winerror", None) not in {5, 32, 33} or attempt == 4:
                    raise
                time.sleep(0.02 * 2 ** attempt)
    finally:
        temporary.unlink(missing_ok=True)
