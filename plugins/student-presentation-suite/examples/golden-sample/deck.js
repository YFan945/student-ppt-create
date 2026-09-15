// Golden sample generator — "AI 幻觉" 课程汇报（9 页）。
// Reproduces the v0.8 pipeline output for examples/golden-sample/.
//
// Visual system v2:
//   - Real background rhythm: navy cover, light content, navy section, navy closing.
//   - Deliberate type scale (40/32/26/22/11) so hierarchy is visible instead of title≈body.
//   - Accent colour carries meaning: one emphasised line, the recommended option,
//     the conclusion node.
//   - A persistent "evidence rail" motif: an accent rule + caption marking evidence.
//   - Charts are hand-authored: no gridlines, one accent series, direct labels.
//
// Note: pptxgenjs writes invalid OOXML (`a:pPr` placement) for rich-text arrays with
// more than one run, so emphasised lines are separate single-run text boxes instead.
//
// Run via the suite wrapper so pptx-helpers / pptx-visuals resolve:
//   node scripts/run_with_pptxgenjs.js --output <out.pptx> examples/golden-sample/deck.js

const path = require('node:path');
const pptxgen = require('pptxgenjs');
const H = require('pptx-helpers');

const TOKENS = require(path.join(__dirname, 'tokens.json'));

const pptx = new pptxgen();
H.applyTokens(pptx, TOKENS, 'chinese');

const S_W = H.SLIDE_W_IN;
const S_H = H.SLIDE_H_IN;
const M = Number((S_W * 0.06).toFixed(4));
const CW = Number((S_W - M * 2).toFixed(4));
const FOOT_Y = S_H - 0.36;
const EYEBROW_Y = 0.3;
const TITLE_Y = 0.58;
const RULE_Y = 1.42;
const CONTENT_TOP = 1.62;

const F = H.fontFamily(TOKENS);
const LIGHT = H.paletteMode(TOKENS, 'light');
const NAVY = H.color(LIGHT, 'primary_text');

const RECT = pptx.ShapeType.rect;
const ROUND = pptx.ShapeType.roundRect;
const LINE = pptx.ShapeType.line;
const DOT = pptx.ShapeType.ellipse;

function page(mode) {
  const tokens = H.paletteMode(TOKENS, mode);
  const slide = pptx.addSlide();
  slide.background = { color: H.color(tokens, 'canvas') };
  return { slide, tokens };
}

const ink = (tokens) => H.color(tokens, 'primary_text');
const muted = (tokens) => H.color(tokens, 'secondary_text');
const accent = (tokens) => H.color(tokens, 'primary_accent');

// Measure before writing so nothing overflows.
function text(slide, value, box, tokens, role, options = {}) {
  const fit = H.preflightText(value, box, tokens, 'chinese', role, options);
  if (!fit.ok) {
    throw new RangeError(
      `${options.label || role} does not fit ${JSON.stringify(box)}: ratio ${fit.fillRatio}`,
    );
  }
  return H.addFittedText(slide, value, box, tokens, 'chinese', role, options);
}

// Emphasised title: one text box per line, so no rich-text array is needed.
function title(slide, lines, box, tokens, size, options = {}) {
  const accentLines = new Set(options.accentLines || []);
  const lineH = (size * 1.7) / 72;
  lines.forEach((line, index) => {
    text(slide, line, { x: box.x, y: box.y + index * lineH, w: box.w, h: lineH }, tokens, 'title', {
      min: size,
      max: size,
      bold: true,
      margin: 0,
      align: options.align || 'left',
      colorRole: accentLines.has(index) ? 'primary_accent' : 'primary_text',
      label: `${options.label || '标题'} 第${index + 1} 行`,
    });
  });
}

function rect(slide, box, color, transparency = 0, shape = RECT) {
  slide.addShape(shape, {
    x: box.x,
    y: box.y,
    w: box.w,
    h: box.h,
    fill: { color, transparency },
    line: { transparency: 100 },
  });
}

function hrule(slide, x, y, w, color, width = 1) {
  slide.addShape(LINE, {
    x,
    y,
    w,
    h: 0,
    line: { color, width, beginArrowType: 'none', endArrowType: 'none' },
  });
}

function vrule(slide, x, y, h, color, width = 1) {
  slide.addShape(LINE, {
    x,
    y,
    w: 0,
    h,
    line: { color, width, beginArrowType: 'none', endArrowType: 'none' },
  });
}

function footer(slide, tokens, label, pageNo) {
  hrule(slide, M, FOOT_Y - 0.12, CW, muted(tokens), 0.75);
  text(slide, label, { x: M, y: FOOT_Y, w: CW * 0.7, h: 0.26 }, tokens, 'caption', {
    margin: 0,
    colorRole: 'secondary_text',
    label: '页脚',
  });
  text(slide, pageNo, { x: M + CW * 0.8, y: FOOT_Y, w: CW * 0.2, h: 0.26 }, tokens, 'caption', {
    margin: 0,
    align: 'right',
    colorRole: 'secondary_text',
    label: '页码',
  });
}

// Shared page system: accent eyebrow, 32pt title, accent rule.
function pageTitle(slide, tokens, eyebrow, titleText) {
  text(slide, eyebrow, { x: M, y: EYEBROW_Y, w: CW * 0.7, h: 0.26 }, tokens, 'caption', {
    margin: 0,
    colorRole: 'primary_accent',
    label: '眉标',
  });
  title(slide, [titleText], { x: M, y: TITLE_Y, w: CW }, tokens, 32, { label: '页面标题' });
  hrule(slide, M, RULE_Y, 1.1, accent(tokens), 2.5);
}

const PAGES = [
  require('./pages/p01-cover.js'),
  require('./pages/p02-hook.js'),
  require('./pages/p03-section.js'),
  require('./pages/p04-mechanism.js'),
  require('./pages/p05-evidence.js'),
  require('./pages/p06-case.js'),
  require('./pages/p07-mitigation.js'),
  require('./pages/p08-recap.js'),
  require('./pages/p09-closing.js'),
];

PAGES.forEach((mod) =>
  mod({
    pptx,
    page,
    text,
    title,
    rect,
    hrule,
    vrule,
    footer,
    pageTitle,
    TOKENS,
    H,
    F,
    LIGHT,
    NAVY,
    RECT,
    ROUND,
    LINE,
    DOT,
    S_W,
    S_H,
    M,
    CW,
    FOOT_Y,
    EYEBROW_Y,
    TITLE_Y,
    RULE_Y,
    CONTENT_TOP,
    ink,
    muted,
    accent,
  }),
);
pptx.writeFile({ fileName: process.argv[2] });
