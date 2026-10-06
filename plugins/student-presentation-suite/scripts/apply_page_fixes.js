#!/usr/bin/env node
/**
 * Deterministic mechanical fixes for review findings — the 0.26.0 autofix layer.
 *
 * `node scripts/apply_page_fixes.js --work-dir <wd> --review visual-review.json`
 *
 * Since v0.22.0 a page is DATA (declarative object) and the engine owns
 * geometry, so some critic findings are script-patchable without burning a
 * builder instance: today that class is the layout swap — the finding carries
 * `repair_level: "implementation"` and its `fix` names a layout id that exists
 * in layout-library.json. The script swaps `layout` in the page module, keeping
 * COPY/slots byte-identical (page_copy_fidelity stays intact), and writes
 * <work-dir>/autofix-report.json as the audit trail.
 *
 * Everything else (content, composition redesign, art direction) stays with the
 * builder — the caller falls back when nothing or only some findings are
 * mechanical.
 *
 * Exit codes: 0 = report written (applied may be empty), 2 = usage/infra.
 */

'use strict';

const fs = require('node:fs');
const path = require('node:path');

const SCRIPTS_DIR = __dirname;
const WORK_DIR = (() => {
  const i = process.argv.indexOf('--work-dir');
  return i > 0 ? path.resolve(process.argv[i + 1]) : null;
})();
const REVIEW_ARG = (() => {
  const i = process.argv.indexOf('--review');
  return i > 0 ? path.resolve(process.argv[i + 1]) : null;
})();

if (!WORK_DIR || !REVIEW_ARG) {
  process.stdout.write(
    'Usage: node scripts/apply_page_fixes.js --work-dir <wd> --review visual-review.json\n',
  );
  process.exit(2);
}

let library;
try {
  library = require(
    path.join(SCRIPTS_DIR, '..', 'skills', 'sp-deck', 'references', 'layout-library.json'),
  );
} catch (error) {
  process.stdout.write(`apply_page_fixes: cannot read layout-library.json: ${error.message}\n`);
  process.exit(2);
}
const KNOWN_IDS = new Set((library.layouts || []).map((l) => l.id));

const review = JSON.parse(fs.readFileSync(REVIEW_ARG, 'utf-8'));
const SCAFFOLD_MARKER = 'student-presentation-suite-scaffold';
const applied = [];
const skipped = [];

function pageNumber(entry) {
  return Number(entry.slide);
}

function pagePathFor(number) {
  const pagesDir = path.join(WORK_DIR, 'pages');
  const pattern = new RegExp(`^p0*${number}[-.].*\\.js$`);
  const found = fs
    .readdirSync(pagesDir)
    .filter((name) => pattern.test(name))
    .sort();
  return found.length ? path.join(pagesDir, found[0]) : null;
}

function layoutIdsIn(text) {
  const found = [];
  for (const id of KNOWN_IDS) {
    if (text.includes(id) && !found.includes(id)) found.push(id);
  }
  return found;
}

for (const entry of review.slides || []) {
  const number = pageNumber(entry);
  for (const issue of entry.issues || []) {
    const base = {
      slide: number,
      code: issue.code,
      severity: issue.severity,
    };
    if (issue.severity !== 'major' && issue.severity !== 'critical') {
      skipped.push({ ...base, reason: 'minor findings are advisory' });
      continue;
    }
    if (issue.repair_level !== 'implementation') {
      skipped.push({
        ...base,
        reason: `repair_level=${issue.repair_level || 'absent'} needs a builder`,
      });
      continue;
    }
    if (issue.resolved) {
      skipped.push({ ...base, reason: 'finding already carries resolved evidence' });
      continue;
    }
    const candidates = layoutIdsIn(String(issue.fix || ''));
    if (!candidates.length) {
      skipped.push({ ...base, reason: 'fix names no known layout id' });
      continue;
    }
    const pagePath = pagePathFor(number);
    if (!pagePath || !fs.existsSync(pagePath)) {
      skipped.push({ ...base, reason: `page module for slide ${number} not found` });
      continue;
    }
    const source = fs.readFileSync(pagePath, 'utf-8');
    if (source.includes(SCAFFOLD_MARKER)) {
      skipped.push({ ...base, reason: 'page is still a scaffold stub' });
      continue;
    }
    if (/module\.exports\s*=\s*function/.test(source)) {
      skipped.push({
        ...base,
        reason: 'function-form page (D9 custom coordinates) is not data-patchable',
      });
      continue;
    }
    const target = candidates[0];
    const current = source.match(/layout:\s*(undefined|"[^"]+"|'[^']+')/);
    const currentId = current ? current[1].replace(/["']/g, '') : null;
    if (currentId === target) {
      skipped.push({ ...base, reason: `layout is already ${target}` });
      continue;
    }
    if (!current) {
      skipped.push({ ...base, reason: 'page declares no layout field to swap' });
      continue;
    }
    const replacement = `layout: ${target === 'undefined' ? 'undefined' : `"${target}"`}`;
    const updated = source.replace(/layout:\s*(undefined|"[^"]+"|'[^']+')/, replacement);
    if (updated === source) {
      skipped.push({ ...base, reason: 'layout replacement produced no change' });
      continue;
    }
    fs.writeFileSync(pagePath, updated, 'utf-8');
    applied.push({
      ...base,
      page: path.relative(WORK_DIR, pagePath),
      from: currentId,
      to: target,
      fix: String(issue.fix || '').slice(0, 200),
    });
  }
}

const report = {
  ok: true,
  review: REVIEW_ARG,
  applied,
  skipped,
  applied_count: applied.length,
};
fs.writeFileSync(
  path.join(WORK_DIR, 'autofix-report.json'),
  `${JSON.stringify(report, null, 2)}\n`,
  'utf-8',
);
process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
