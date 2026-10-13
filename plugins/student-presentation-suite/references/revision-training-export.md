# Revision, Training, And Export Contract

## Local Revision Operations

Supported edit intents:

- `rewrite-slide`
- `rewrite-section`
- `change-style`
- `compress`
- `expand`
- `add-evidence`

Apply only the requested scope. A slide with `locked: true` must not change
unless the user explicitly unlocks it. Use `create_revision_manifest.py` to
compare old and new specs and fail when a locked slide changed.

Revision manifests record parent revision, current revision, changed slides,
preserved locked slides, violations, reason, and file hashes. Store versioned
deliverables under `outputs/versions/<revision-id>/`; keep the current approved
copy under `outputs/`.

Use `manage_versions.py snapshot` to create an immutable local package and
`manage_versions.py restore` to create a non-destructive rollback candidate
under `outputs/restored/<revision-id>/`.

## Training Mode

For each slide provide:

- one-sentence speaking goal;
- useful keyword cues for the selective speaking path;
- planned seconds;
- likely teacher/judge question;
- concise answer points;
- one claim or phrase to avoid overstating.

Rehearsal checks compare `timing_sec` with note length, detect abrupt timing
changes, missing transitions, long sentences, and vocabulary that is difficult
to say naturally.

Notes normally cover selected highlights, the necessary explanation and transitions rather than narrating every visible detail. A short note does not require reducing substantive slide content. Explicit oral requirements and requested full narration remain binding; do not stretch notes with filler to match the planned seconds.

## Quality Report

For requested review/scoring, optional scores can summarize:

- logic;
- evidence;
- readability;
- speakability;
- defense readiness.

Scores summarize findings and never replace slide-specific fixes. Every issue
must include severity, target, problem, impact, and concrete fix.

Main-session production does not require a score file or critic receipt. A requested production quality report must distinguish technical checks from author self-check; it does not establish independent visual or semantic review.

## Export Matrix

Supported local deliverables:

- editable PPTX;
- PDF exported through LibreOffice;
- PNG page previews/contact sheet;
- Markdown speaker notes;
- HTML teleprompter;
- quality report;
- revision manifest.

DOCX notes are not produced by the suite-owned PPTX runtime. Web editing, cloud
synchronization, and multi-user collaboration require an external service and
are not claimed by this local plugin.
