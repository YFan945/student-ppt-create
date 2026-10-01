"""Deterministic source retrieval for the research layer: bytes in, text out.

Why this exists (2026-09-29 live): the harness page reader answers *a prompt*
through a small model, so what came back was a summary — and a summarizer
rewrites numbers, while the Evidence Ledger binds byte-exact quotes. When the
search tool returned nothing that same day, the researcher fell back to reading
search-result pages: 81 of 135 fetches, median 8.5 s, 94% of that run's retrieval
wall clock, and almost none of it citable. The fix has two halves — the deputy
never reads a result page (see `references/research-workflow.md` §七), and this
module makes the direct-source half deterministic: HTTP GET → raw bytes (kept)
→ extracted text (kept) → provenance bound to both hashes, with no model anywhere
between the publisher's sentence and the pack.

Permission gate: research retrieval is authorized inside scope A/B only
(`references/research-workflow.md` §一; C = no search, D = no web retrieval).
The caller must pass its scope explicitly and C/D are refused, so the D-class
rule is enforced mechanically instead of by reminder.

Safety model:
On-demand by design (owner, 2026-09-29): the fetcher does not police *what* you
fetch. Search-result hosts and private hosts are fetched like anything else; the
record carries `host_class` (`search_engine` / `listing` / `private` / `public`) plus a note,
because "a result page is not a source" is an evidence rule for the pack, not a
rule about which URLs may be read — and a fence here would only teach the agent
to reach the same page by another route.

Safety model:
- http/https only; per-request timeout;
- only text-ish content types are extracted, so a binary body is refused instead
  of decoded into garbage;
- every attempt is recorded in the report, failures included.

Degenerate channels (2026-09-30 live): a publisher's record endpoint answered ten
differently-parameterised requests with one byte-identical 97-byte body while each
variation cost a full model turn, and nothing in the trail said so. The verdict is
computed here, from hashes this module already writes, and owned by
`shared/retrieval_trail.py` — a capability, not a strategy rule.
"""

from __future__ import annotations

import datetime
import hashlib
import html
import ipaddress
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from shared.research_io import atomic_json, file_lock
from shared.retrieval_trail import (
    DEGENERATE_ECHO,
    DEGENERATE_ECHO_NOTE,
    SEARCH_LOCATOR_HOSTS,
    degenerate_channels,
    endpoint_key,
    is_listing_locator,
    is_search_locator,
)

EXTRACTOR = "fetch-text/1"
ALLOWED_SCOPES = ("A", "B")
DEFAULT_TIMEOUT = 60

# Recorded as `host_class: search_engine`, never refused. The set lives in
# retrieval_trail (one owner, also used by the WebFetch refusal) and is re-exported
# under the name tests already pin.
_SEARCH_HOSTS = SEARCH_LOCATOR_HOSTS

_TEXT_TYPES = ("text/", "application/json", "application/xml", "application/xhtml")
_PDF_TYPES = ("application/pdf",)

_TAG = re.compile(r"<[^>]*>")
_DROP_BLOCKS = re.compile(
    r"<(script|style|noscript|template|svg)\b[^>]*>.*?</\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_HEAD_BLOCK = re.compile(r"<head\b[^>]*>.*?</head\s*>", re.IGNORECASE | re.DOTALL)
_TITLE = re.compile(r"<title\b[^>]*>(.*?)</title\s*>", re.IGNORECASE | re.DOTALL)
_META_CHARSET = re.compile(
    r"""<meta[^>]+charset\s*=\s*["']?\s*([\w-]+)""",
    re.IGNORECASE,
)
_BLOCK_TAGS = re.compile(
    r"</?(p|div|br|li|tr|h[1-6]|section|article|header|footer|table|ul|ol|blockquote)\b[^>]*>",
    re.IGNORECASE,
)
_WHITESPACE = re.compile(r"[ \t\u00a0]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def slug(text: str) -> str:
    value = re.sub(r"[^0-9A-Za-z\u3400-\u9fff]+", "-", text.strip()).strip("-").lower()
    return value[:60] or "source"


def host_class(url: str) -> str:
    """Classify the host for the provenance trail: search_engine / listing / private / public."""
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    if is_search_locator(url):
        return "search_engine"
    if is_listing_locator(url):
        return "listing"
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        return "private"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return "public"
    if address.is_loopback or address.is_private or address.is_link_local or address.is_reserved:
        return "private"
    return "public"


_HOST_CLASS_NOTES = {
    "search_engine": (
        "a search-result page is a locator, not a source — use the search tool to find the "
        "document URL (or a publisher's own record endpoint), then read that"
    ),
    "listing": (
        "an index, news listing, or publisher record endpoint is a locator, not a source — "
        "read the document URL it points at"
    ),
    "private": "loopback/private host: fine for local checks, never citable evidence",
}


def annotate_channels(report: dict[str, Any]) -> dict[str, Any]:
    """Add the per-channel verdict to the report and flag the records that earned it.

    Both halves matter: the records are where the executor looks while reading the report
    it just produced, and the channel summary makes "judge this channel once" actionable
    without re-deriving the grouping downstream (the validator recomputes it from
    `raw_sha256` anyway, so an older report audits the same way).
    """
    records = report.get("records") or []
    found = degenerate_channels(records)
    report["degenerate_channels"] = found
    flagged = {(entry["channel"], entry["raw_sha256"]) for entry in found}
    if not flagged:
        return report
    for record in records:
        if not isinstance(record, dict) or not record.get("ok"):
            continue
        key = (endpoint_key(str(record.get("url") or "")), str(record.get("raw_sha256") or ""))
        if key in flagged:
            record["channel_verdict"] = DEGENERATE_ECHO
            record["channel"] = key[0]
            record["channel_note"] = DEGENERATE_ECHO_NOTE
    return report


def scheme_refusal(url: str) -> str | None:
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme not in {"http", "https"}:
        return "scheme_not_allowed"
    return None


def decode_body(raw: bytes, content_type: str) -> tuple[str, str]:
    """Decode a body using the header, a meta tag, or a CJK-aware fallback chain.

    Chinese government and news sites still serve GBK/GB2312; guessing UTF-8 only
    would turn their text into mojibake and silently corrupt every quote.
    """
    charset = ""
    match = re.search(r"charset\s*=\s*\"?\s*([\w-]+)", content_type or "", re.IGNORECASE)
    if match:
        charset = match.group(1)
    if not charset:
        probe = raw[:4096].decode("ascii", errors="ignore")
        meta = _META_CHARSET.search(probe)
        if meta:
            charset = meta.group(1)
    candidates = [charset] if charset else []
    candidates.extend(["utf-8", "gb18030", "big5"])
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return raw.decode(candidate), candidate
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8/replace"


def extract_text(decoded: str, content_type: str) -> tuple[str, str]:
    """Return (text, title). HTML is stripped deterministically; other text passes through."""
    lowered = (content_type or "").lower()
    is_html = "html" in lowered or "<html" in decoded[:2000].lower() or "<body" in decoded[:2000].lower()
    if not is_html:
        return decoded.strip(), ""
    title_match = _TITLE.search(decoded)
    title = html.unescape(_TAG.sub("", title_match.group(1))).strip() if title_match else ""
    body = _HEAD_BLOCK.sub(" ", decoded)
    body = _COMMENT.sub(" ", body)
    body = _DROP_BLOCKS.sub(" ", body)
    body = _BLOCK_TAGS.sub("\n", body)
    body = _TAG.sub(" ", body)
    body = html.unescape(body)
    body = _WHITESPACE.sub(" ", body)
    lines = [line.strip() for line in body.splitlines()]
    body = "\n".join(line for line in lines if line)
    return _BLANK_LINES.sub("\n\n", body).strip(), title


def _default_getter(url: str, timeout: int) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "student-presentation-suite/fetch-text (+research citation fetch)",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - scheme gated
        headers = {key.lower(): value for key, value in response.headers.items()}
        return int(getattr(response, "status", 200) or 200), headers, response.read()


def _pdf_text(raw: bytes) -> tuple[str | None, str]:
    """Convert a PDF body with markitdown when it is installed; never guess."""
    try:
        import markitdown  # noqa: PLC0415 - optional runtime dependency
    except ModuleNotFoundError:
        return None, "pdf text extraction requires markitdown"
    import tempfile  # noqa: PLC0415 - only needed on the PDF path

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "source.pdf"
        target.write_bytes(raw)
        try:
            result = markitdown.MarkItDown().convert(str(target))
        except Exception as exc:  # markitdown raises a wide range; report, never crash
            return None, f"markitdown failed: {type(exc).__name__}"
    text = str(getattr(result, "text_content", "") or "").strip()
    return (text or None), "" if text else "markitdown returned no text"


def _artifact_name(url: str, raw: bytes, _out_dir: Path) -> str:
    """A file name that can never silently replace a *different* response.

    One accumulating out-dir is what makes a run auditable, and slugs collide: every
    ``sousuo.www.gov.cn/search-gov/data?…`` request slugs to ``data``, so the second
    one overwrote the first while both records kept pointing at the surviving path —
    a record whose ``raw_path`` holds someone else's bytes (2026-09-30 live, and the
    reason the executor started hand-rolling a sub-directory per fetch, which then
    scattered the report the audit reads).
    """
    base = slug(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1] or url)
    return f"{base}-{hashlib.sha256(url.encode()).hexdigest()[:12]}-{hashlib.sha256(raw).hexdigest()[:12]}"


def fetch_one(
    url: str,
    out_dir: Path,
    *,
    scope: str,
    timeout: int = DEFAULT_TIMEOUT,
    getter: Callable[[str, int], tuple[int, dict[str, str], bytes]] | None = None,
) -> dict[str, Any]:
    """Fetch one URL into ``out_dir`` and return its provenance record."""
    record: dict[str, Any] = {
        "url": url,
        "scope": scope,
        "extractor": EXTRACTOR,
        "fetched_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "ok": False,
    }
    if scope not in ALLOWED_SCOPES:
        record["reason"] = "scope_not_authorized"
        record["detail"] = (
            f"scope {scope!r} does not authorize web retrieval "
            f"(A/B only; C = no search, D = user-restricted sources)"
        )
        return record
    refusal = scheme_refusal(url)
    if refusal:
        record["reason"] = refusal
        record["detail"] = _REFUSAL_DETAIL[refusal]
        return record
    klass = host_class(url)
    record["host_class"] = klass
    if klass in _HOST_CLASS_NOTES:
        record["note"] = _HOST_CLASS_NOTES[klass]

    get = getter or _default_getter
    try:
        status, headers, raw = get(url, timeout)
    except urllib.error.HTTPError as exc:
        record["reason"] = "http_error"
        record["detail"] = f"HTTP {exc.code}"
        return record
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        record["reason"] = "unreachable"
        record["detail"] = f"{type(exc).__name__}: {exc}"
        return record

    content_type = headers.get("content-type", "")
    record["status"] = status
    record["content_type"] = content_type
    record["bytes"] = len(raw)
    record["raw_sha256"] = hashlib.sha256(raw).hexdigest()
    out_dir.mkdir(parents=True, exist_ok=True)
    name = _artifact_name(url, raw, out_dir)
    raw_path = out_dir / f"{name}.raw"
    raw_path.write_bytes(raw)
    record["raw_path"] = str(raw_path)

    note = ""
    if any(kind in content_type.lower() for kind in _PDF_TYPES):
        text, note = _pdf_text(raw)
        record["pdf"] = True
    elif any(kind in content_type.lower() for kind in _TEXT_TYPES):
        decoded, charset = decode_body(raw, content_type)
        text, title = extract_text(decoded, content_type)
        record["charset"] = charset
        if title:
            record["title"] = title
    else:
        text, note = None, f"content type not extractable: {content_type or 'unknown'}"
        record["pdf"] = False

    if note:
        record["note"] = note
    if text is None:
        record["reason"] = "not_extractable"
        return record

    text_path = out_dir / f"{name}.txt"
    # Hash exactly the bytes on disk, including the trailing newline (and without
    # platform newline translation). Evidence bindings compare this file hash.
    text_bytes = (text + "\n").encode("utf-8")
    text_path.write_bytes(text_bytes)
    record["text_path"] = str(text_path)
    record["text_sha256"] = hashlib.sha256(text_bytes).hexdigest()
    record["text_chars"] = len(text)
    record["ok"] = True
    return record


_REFUSAL_DETAIL = {
    "scope_not_authorized": "pass --scope A or B; C/D never authorize retrieval",
    "scheme_not_allowed": "only http/https URLs can be fetched",
}


def report_directory(out_dir: Path) -> Path:
    """Where the accumulating report lives.

    The caller is told to use one directory, `<work-dir>/research/fetched`. A nested
    `uN` directory (the 2026-09-30 run numbered these to `u120`) would otherwise keep
    its own report and the cross-call verdict would never see the earlier hashes.
    One level under `research/fetched` is folded back; any other directory is itself.
    """
    path = Path(out_dir)
    parent = path.parent
    if parent.name == "fetched" and parent.parent.name == "research":
        return parent
    return path


def load_records(out_dir: Path) -> list[dict[str, Any]]:
    """Records already written for this run, or an empty list if nothing is there yet."""
    path = report_directory(out_dir) / "fetch-text-report.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    records = data.get("records") if isinstance(data, dict) else None
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]


def _closed_record(url: str, scope: str, channel: str) -> dict[str, Any]:
    return {
        "url": url,
        "scope": scope,
        "extractor": EXTRACTOR,
        "fetched_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "ok": False,
        "reason": "channel_closed",
        "channel": channel,
        "channel_verdict": DEGENERATE_ECHO,
        "channel_note": DEGENERATE_ECHO_NOTE,
        "detail": (
            "this endpoint already returned one body for distinct requests; "
            "the request was not sent"
        ),
    }


def _report_from_records(records: list[dict[str, Any]], scope: str) -> dict[str, Any]:
    fetched = [record for record in records if record.get("ok")]
    refused = [record for record in records if record.get("reason") in _REFUSAL_DETAIL]
    report = {
        "ok": bool(fetched),
        "scope": scope,
        "extractor": EXTRACTOR,
        "fetched": len(fetched),
        "refused": len(refused),
        "failed": len(records) - len(fetched) - len(refused),
        "records": records,
    }
    return annotate_channels(report)


def fetch_many(
    urls: list[str],
    out_dir: Path,
    *,
    scope: str,
    timeout: int = DEFAULT_TIMEOUT,
    getter: Callable[[str, int], tuple[int, dict[str, str], bytes]] | None = None,
    workers: int = 4,
) -> dict[str, Any]:
    """Fetch every URL and return a report accumulated with whatever this directory already holds.

    A channel already classified as a degenerate echo is not requested again: the new
    URL is recorded as `channel_closed` and no HTTP call is made. An exact URL that
    already succeeded is reused. Both are classifications of the trail, not a cap on
    how many documents a run may fetch. `this_call` lists the rows this invocation
    touched; `write_report` strips it so the file stays the audit shape.
    """
    stable = report_directory(out_dir)
    task_path = stable.parent.parent / "research-task.json"
    frozen_path = stable.parent.parent / "research-task-binding.json"
    if task_path.is_file():
        task = json.loads(task_path.read_text(encoding="utf-8"))
        scope = task["scope"]
        if frozen_path.is_file() and json.loads(frozen_path.read_text(encoding="utf-8")).get("sha256") != hashlib.sha256(task_path.read_bytes()).hexdigest():
            scope = "task_changed"
    elif frozen_path.is_file():
        scope = "task_missing"
    records = load_records(stable)
    closed = {entry["channel"] for entry in degenerate_channels(records)}
    by_url = {str(record.get("url") or ""): record for record in records}
    this_call: list[dict[str, Any]] = []
    pending = []
    def cache_valid(record):
        try:
            return all(hashlib.sha256(Path(record[key]).read_bytes()).hexdigest() == record[digest]
                       for key, digest in (("raw_path", "raw_sha256"), ("text_path", "text_sha256")))
        except (OSError, KeyError, TypeError):
            return False

    for url in dict.fromkeys(urls):
        if scope not in ALLOWED_SCOPES:
            refused = fetch_one(url, stable, scope=scope, timeout=timeout, getter=getter)
            this_call.append(refused)
            write_report(_report_from_records([refused], scope), stable)
            continue
        channel = endpoint_key(url)
        if channel and channel in closed:
            existing = by_url.get(url)
            if existing is None:
                existing = _closed_record(url, scope, channel)
                records.append(existing)
                by_url[url] = existing
            this_call.append(existing)
            continue
        existing = by_url.get(url)
        if existing and existing.get("ok") and cache_valid(existing):
            this_call.append({**existing, "reused": True})
            continue
        pending.append(url)
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as executor:
        futures = {executor.submit(fetch_one, url, stable, scope=scope, timeout=timeout, getter=getter): url for url in pending}
        for future in as_completed(futures):
            fetched = future.result()
            this_call.append(fetched)
            write_report(_report_from_records([fetched], scope), stable)
    # Closed rows must also survive interrupted invocations.
    write_report(_report_from_records(this_call, scope), stable)
    report = _report_from_records(load_records(stable), scope)
    report["ok"] = any(r.get("ok") for r in this_call)
    report["this_call"] = this_call
    return report


def call_summary(report: dict[str, Any], report_path: Path) -> dict[str, Any]:
    """The stdout view: this call's rows and the channel verdicts, not every historical body.

    Page text stays in `text_path`. Printing the accumulated report on every call is how
    a long run's tool output grew without bound.
    """
    kept = (
        "url",
        "ok",
        "reason",
        "reused",
        "text_chars",
        "text_path",
        "raw_sha256",
        "text_sha256",
        "channel_verdict",
        "channel",
        "host_class",
        "title",
        "detail",
    )
    rows = []
    for record in report.get("this_call") or []:
        rows.append({key: record[key] for key in kept if key in record})
    return {
        "ok": report.get("ok"),
        "scope": report.get("scope"),
        "fetched": report.get("fetched"),
        "refused": report.get("refused"),
        "failed": report.get("failed"),
        "degenerate_channels": report.get("degenerate_channels") or [],
        "records": rows,
        "records_total": len(report.get("records") or []),
        "report": str(report_path),
    }


def write_report(report: dict[str, Any], out_dir: Path) -> Path:
    stable = report_directory(out_dir)
    stable.mkdir(parents=True, exist_ok=True)
    path = stable / "fetch-text-report.json"
    with file_lock(stable / ".report.lock"):
        records = load_records(stable)
        for incoming in report.get("records", []):
            if incoming.get("reused"):
                continue
            if incoming not in records:
                records.append(incoming)
        atomic_json(path, _report_from_records(records, str(report.get("scope", ""))))
    return path
