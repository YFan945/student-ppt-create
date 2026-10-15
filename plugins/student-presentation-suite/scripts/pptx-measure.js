#!/usr/bin/env node
'use strict';

/*
 * Measure every text block a deck would draw, without building a deliverable.
 *
 * addFittedText/addPositionedText are replaced by measuring no-ops, so one pass
 * reports every overflow and every tight-margin block instead of failing on the
 * first page. Nothing here draws, writes or validates a real deck.
 *
 * Usage: node pptx-measure.js <work-dir>/deck.js <report.json>
 * Reads module roots from PPTX_HELPERS_DIR (set by the pipeline) and resolves
 * pptxgenjs/fontkit through the shared runtime paths.
 */

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const deckPath = process.argv[2] ? path.resolve(process.argv[2]) : '';
const reportPath = process.argv[3] ? path.resolve(process.argv[3]) : '';
if (!deckPath || !reportPath || !fs.existsSync(deckPath)) {
  // eslint-disable-next-line no-console
  console.error('usage: pptx-measure.js <work-dir>/deck.js <report.json>');
  process.exit(2);
}

const HELPERS_DIR =
  process.env.PPTX_HELPERS_DIR || path.join(process.env.CLAUDE_PLUGIN_ROOT || '', 'scripts');
const { resolveModule, installSearchPaths } = require(
  path.join(HELPERS_DIR, 'pptx-runtime-paths.js'),
);
installSearchPaths([resolveModule('pptxgenjs'), resolveModule('fontkit')], [HELPERS_DIR]);
process.env.PPTX_HELPERS_DIR = HELPERS_DIR;
process.env.PPTX_MEASURE = '1';
const H = require(path.join(HELPERS_DIR, 'pptx-helpers.js'));

const pages = new WeakMap();
let pageSeq = 0;
const blocks = [];

function record(slide, value, box, policy, fit) {
  if (slide && typeof slide === 'object') {
    if (!pages.has(slide)) pages.set(slide, ++pageSeq);
  }
  const lines = Array.isArray(fit.lineGeometry) ? fit.lineGeometry : [];
  blocks.push({
    page: (slide && pages.get(slide)) || null,
    role: policy.role || null,
    text: H.plainText(value).slice(0, 60),
    box: { x: box.x, y: box.y, w: box.w, h: box.h },
    font_size: policy.fontSize ?? fit.fontSize ?? null,
    lines: fit.lines ?? null,
    required_h: fit.requiredH ?? null,
    max_line_w: lines.length ? Math.max(...lines.map((line) => line.w || 0)) : null,
    fits: Boolean(fit.fits),
  });
}

H.addFittedText = function measureOnly(slide, value, box, tokens, lang, role, options = {}) {
  const policy = H.rolePolicy(tokens, lang, role, options);
  record(slide, value, box, policy, H.fitText(value, box, policy));
  return slide;
};

H.addPositionedText = function measurePositioned(
  slide,
  value,
  box,
  tokens,
  lang,
  role,
  options = {},
) {
  const policy = H.rolePolicy({ ...tokens, model_led: true }, lang, role, options);
  record(slide, value, box, policy, H.fitText(value, box, policy));
  return slide;
};

// The deck's main() reads its output path from argv and may call process.exit
// on collected page errors; both are redirected so the report is always written.
const tempOutput = path.join(
  fs.mkdtempSync(path.join(os.tmpdir(), 'pptx-measure-')),
  'measure.pptx',
);
process.on('exit', () => {
  fs.rmSync(path.dirname(tempOutput), { recursive: true, force: true });
});
process.argv = [process.argv[0], deckPath, tempOutput];
let exitCode = 0;
const realExit = process.exit;
process.exit = (code) => {
  exitCode = code || 0;
  throw new Error(`deck requested exit ${exitCode}`);
};

let buildError = null;
try {
  require(deckPath);
} catch (error) {
  buildError = String((error && error.message) || error);
} finally {
  process.exit = realExit;
}

const overflow = blocks.filter((block) => !block.fits);
const tight = blocks.filter(
  (block) =>
    block.fits &&
    ((block.required_h !== null && block.box.h > 0 && block.required_h / block.box.h > 0.92) ||
      (block.max_line_w !== null && block.box.w > 0 && block.max_line_w / block.box.w > 0.92)),
);
const report = {
  deck: deckPath,
  block_count: blocks.length,
  overflow,
  tight,
  build_error: buildError,
};
fs.mkdirSync(path.dirname(reportPath), { recursive: true });
fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');

const lines = [
  `measured ${blocks.length} text block(s): ${overflow.length} overflow, ${tight.length} tight`,
];
for (const block of overflow)
  lines.push(
    `  overflow p${block.page} "${block.text}" box ${block.box.w}x${block.box.h}in needs ${block.required_h}in`,
  );
for (const block of tight)
  lines.push(`  tight    p${block.page} "${block.text}" box ${block.box.w}x${block.box.h}in`);
if (buildError) lines.push(`  build error: ${buildError}`);
process.stdout.write(`${lines.join('\n')}\n`);
process.exitCode = overflow.length || buildError ? 1 : 0;
