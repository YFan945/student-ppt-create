"""UTF-8-safe hook event input shared by every hook entrypoint.

Claude Code pipes hook events as UTF-8 JSON, but Python's ``sys.stdin`` on
Windows decodes with the locale codec (cp936), so every non-ASCII path in the
event turned into mojibake the moment it was read (run-14 live: a project under
``E:\\1学习资料\\…`` was recorded in guard ledgers as ``E:\\1瀛︿範璧勬枡\\…``).
Corrupted strings never matched the real filesystem again, silently defeating
every path-equality check — notably the researcher's own task-read credentials
in runtime_evidence, so a resumed researcher was refused retrieval with
``work_dir_ambiguous`` forever on non-ASCII project paths.

Every hook entrypoint must read the event through :func:`read_event`: bytes in,
strict UTF-8 decode, empty dict on any malformed payload (hooks are advisory
and must not crash on host churn).
"""

from __future__ import annotations

import json
import re
import sys

_TERMINAL_HELP_RE = re.compile(r"(?:^|[\s\"'])(?:--help|-h)\s*(?:2>&1)?\s*$")


def read_event() -> dict:
    try:
        buffer = getattr(sys.stdin, "buffer", None)
        # Text-level stdin (test harnesses patch io.StringIO in): the string is
        # already decoded, so encode/decode round-trips it unchanged.
        raw = buffer.read() if buffer is not None else str(sys.stdin.read() or "").encode("utf-8")
    except (AttributeError, OSError, ValueError):
        raw = b""
    if not raw:
        return {}
    try:
        event = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return event if isinstance(event, dict) else {}


def terminal_help_probe(command: str) -> bool:
    """True when the command ends in a bare ``--help``/``-h`` usage print.

    A usage probe is read-only and its output IS the discovery surface — refusing
    it costs the round trip it was meant to save and yields a failure instead of
    information (run-14: `copy_fit_preflight.py --help` refused, then the same
    question asked again by trial and error). Anything that does not END in the
    help token — bare invocations, help chained with real work — is still
    refused, which keeps the 2026-09-17 chained-probe rationale intact.
    """
    return bool(_TERMINAL_HELP_RE.search(command or ""))
