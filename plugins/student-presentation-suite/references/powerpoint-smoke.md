# Microsoft PowerPoint release smoke

LibreOffice rendering and Open XML validation do not certify PowerPoint visual
compatibility. Record a separate Windows + Microsoft PowerPoint check for each
release candidate when Office is available; otherwise report `not tested`.

Use `scripts/powerpoint_smoke.ps1 -InputPptx <absolute-pptx> -OutputDir <outside-repo>`.
It opens the source read-only, exports every slide to PNG, records the Office
version, source SHA256 and slide count, and closes only its own presentation.
The report's `automated_open_export_passed` is not a visual approval.

Inspect every exported slide in PowerPoint or its PNGs and record reviewer,
date, source hash, issue/page list and pass/fail for:

- CJK/Latin font fallback, line wrapping, spacing and clipping.
- Charts, SVG, image cropping and transparent backgrounds.
- Theme fonts, master/layout inheritance, headers and footers.
- Notes, hyperlinks and slide order; edit and save a separate copy then reopen.
- Compare representative exports to LibreOffice, documenting differences.

Never label a missing Office installation or an unreviewed export as passed.
