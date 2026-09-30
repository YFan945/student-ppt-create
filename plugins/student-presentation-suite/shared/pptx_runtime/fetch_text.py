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
record carries `host_class` (`search_engine` / `private` / `public`) plus a note,
because "a result page is not a source" is an evidence rule for the pack, not a
rule about which URLs may be read — and a fence here would only teach the agent
to reach the same page by another route.

Safety model:
- http/https only; per-request timeout;
- only text-ish content types are extracted, so a binary body is refused instead
  of decoded into garbage;
- every attempt is recorded in the report, failures included.
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
from pathlib import Path
from typing import Any

EXTRACTOR = "fetch-text/1"
ALLOWED_SCOPES = ("A", "B")
DEFAULT_TIMEOUT = 60

# Recorded as `host_class: search_engine`, never refused. Kept in sync with the
# evidence rule in references/research-workflow.md §七 by tests/test_fetch_text.py.
_SEARCH_HOSTS = frozenset(
    {
        "bing.com",
        "www.bing.com",
        "cn.bing.com",
        "so.com",
        "www.so.com",
        "sogou.com",
        "www.sogou.com",
        "duckduckgo.com",
        "lite.duckduckgo.com",
        "html.duckduckgo.com",
        "search.brave.com",
        "brave.com",
        "mojeek.com",
        "www.mojeek.com",
        "search.yahoo.com",
        "yahoo.com",
        "baidu.com",
        "www.baidu.com",
        "google.com",
        "www.google.com",
    }
)
_REDIRECT_MARKERS = ("link?m=", "/link?")

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
    """Classify the host for the provenance trail: search_engine / private / public."""
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    if host in _SEARCH_HOSTS or any(marker in url.lower() for marker in _REDIRECT_MARKERS):
        return "search_engine"
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
    "private": "loopback/private host: fine for local checks, never citable evidence",
}


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
    name = slug(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1] or url)
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
    text_path.write_text(text + "\n", encoding="utf-8")
    record["text_path"] = str(text_path)
    record["text_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    record["text_chars"] = len(text)
    record["ok"] = True
    return record


_REFUSAL_DETAIL = {
    "scope_not_authorized": "pass --scope A or B; C/D never authorize retrieval",
    "scheme_not_allowed": "only http/https URLs can be fetched",
}


def fetch_many(
    urls: list[str],
    out_dir: Path,
    *,
    scope: str,
    timeout: int = DEFAULT_TIMEOUT,
    getter: Callable[[str, int], tuple[int, dict[str, str], bytes]] | None = None,
) -> dict[str, Any]:
    """Fetch every URL and return a report; one failure never hides the others."""
    records = [
        fetch_one(url, Path(out_dir), scope=scope, timeout=timeout, getter=getter) for url in urls
    ]
    fetched = [record for record in records if record["ok"]]
    refused = [record for record in records if record.get("reason") in _REFUSAL_DETAIL]
    return {
        "ok": bool(fetched),
        "scope": scope,
        "extractor": EXTRACTOR,
        "fetched": len(fetched),
        "refused": len(refused),
        "failed": len(records) - len(fetched) - len(refused),
        "records": records,
    }


def write_report(report: dict[str, Any], out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "fetch-text-report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
