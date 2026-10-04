"""Single implementation of chunked SHA-256 file hashing.

Evidence binding (reports, packets, delivery checks) hashes the same files in
~20 places; each used to carry its own copy of the same 1MB-chunk loop, so a
drift in one copy would silently break the hash equality the binding relies on.
One implementation here; callers import and alias to their local name.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK_BYTES = 1024 * 1024


def file_sha256(path: Path) -> str:
    """Strict variant: raises OSError when the file cannot be read."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_sha256_or_none(path: Path) -> str | None:
    """Tolerant variant: None when the file is missing or unreadable."""
    try:
        if not Path(path).is_file():
            return None
        return file_sha256(path)
    except OSError:
        return None
