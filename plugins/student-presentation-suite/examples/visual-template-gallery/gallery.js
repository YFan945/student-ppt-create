/**
 * Visual template gallery — renders 9 high-quality template pages per style,
 * parameterized by the style's tokens (light + dark palette), svg motif and
 * `visual_language` (rule / panel / radius / motif_at / chart / decor).
 *
 * Input:  gallery-input.json  { styles: [{ key, name, tokens }] }
 * Output: one PPTX with 12 sections x 9 pages.
 *
 * Layout zones come from skills/sp-deck/references/layout-library.json
 * (normalized-safe-area fractions), so the rendered templates are honest
 * implementations of the layout contract, not free-hand art.
 */

const path = require('node:path');
const pptxgen = require('pptxgenjs');
const H = require('pptx-helpers');
const SVG = require('pptx-svg-library');
const V = require('pptx-visuals');

const INPUT = require(path.join(__dirname, 'gallery-input.json'));
const LAYOUTS = {};
for (const id of [
  'cover-split',
  'section-statement',
  'claim-focus',
  'data-chart-takeaway',
  'compare-before-after',
  'timeline-roadmap',
  'quote-focus',
  'visual-annotated',
  'closing-takeaway',
]) {
  LAYOUTS[id] =
    require('E:/student-ppt-create/plugins/student-presentation-suite/skills/sp-deck/references/layout-library.json').layouts.find(
      (l) => l.id === id,
    );
}

const pptx = new pptxgen();
const S_W = H.SLIDE_W_IN;
const S_H = H.SLIDE_H_IN;
const M = S_W * 0.06;
const CW = S_W - M * 2;
const CONTENT_TOP = 1.62; // 与正式 deck 一致的内容起始高度
const AREA = H.safeArea(S_W, S_H, INPUT.styles[0].tokens.geometry || INPUT.styles[0].tokens, {
  reserveTitle: false,
});

/** Map a layout-library zone [x,y,w,h] (fractions of the safe area) to inches. */
function zone(id, name) {
  const z = LAYOUTS[id].zones[name];
  if (!z) return null;
  return {
    x: AREA.x + z[0] * AREA.w,
    y: AREA.y + z[1] * AREA.h,
    w: z[2] * AREA.w,
    h: z[3] * AREA.h,
  };
}

function rect(slide, box, color, opts = {}) {
  slide.addShape('rect', {
    x: box.x,
    y: box.y,
    w: box.w,
    h: box.h,
    fill: { color, transparency: Number(opts.transparency || 0) },
    line: opts.line
      ? { color: opts.line, width: Number(opts.lineWidth || 1) }
      : { color, transparency: 100 },
    ...(opts.rotate ? { rotate: opts.rotate } : {}),
  });
}

function roundRect(slide, box, color, radius, opts = {}) {
  const shape = {
    x: box.x,
    y: box.y,
    w: box.w,
    h: box.h,
    rectRadius: radius,
    fill: { color, transparency: Number(opts.transparency || 0) },
    line: opts.line
      ? { color: opts.line, width: Number(opts.lineWidth || 1) }
      : { color, transparency: 100 },
  };
  if (opts.shadow) shape.shadow = opts.shadow;
  slide.addShape('roundRect', shape);
}

function text(slide, str, box, tokens, role, opts = {}) {
  H.addFittedText(slide, str, box, tokens, 'chinese', role, {
    margin: 0,
    ...opts,
  });
}

/* ── Style personality primitives (visual_language) ─────────────────────── */

function drawRule(slide, t, vl, titleBox) {
  const A = H.color(t, 'primary_accent');
  switch (vl.rule) {
    case 'underline-left':
      rect(slide, { x: titleBox.x, y: titleBox.y + titleBox.h + 0.06, w: 1.25, h: 0.055 }, A);
      break;
    case 'left-rail':
      rect(slide, { x: titleBox.x - 0.16, y: titleBox.y + 0.04, w: 0.07, h: titleBox.h }, A);
      break;
    case 'top-band':
      rect(slide, { x: 0, y: 0, w: S_W, h: 0.12 }, A);
      break;
    case 'slash':
      rect(slide, { x: titleBox.x, y: titleBox.y + titleBox.h + 0.04, w: 1.15, h: 0.05 }, A);
      rect(slide, { x: titleBox.x + 0.08, y: titleBox.y - 0.08, w: 0.05, h: 0.48 }, A, {
        rotate: 335,
      });
      break;
    case 'bracket':
      rect(slide, { x: titleBox.x - 0.08, y: titleBox.y - 0.06, w: 0.42, h: 0.045 }, A);
      rect(slide, { x: titleBox.x - 0.08, y: titleBox.y - 0.06, w: 0.045, h: 0.34 }, A);
      rect(
        slide,
        { x: titleBox.x - 0.08, y: titleBox.y + titleBox.h + 0.02, w: 0.28, h: 0.045 },
        A,
      );
      break;
    default:
      break;
  }
}

function emphasisMark(slide, t, vl, box, index) {
  const A = H.color(t, 'primary_accent');
  const kind = vl.emphasis_marker;
  if (kind === 'dot') {
    slide.addShape('ellipse', {
      x: box.x,
      y: box.y + 0.06,
      w: 0.12,
      h: 0.12,
      fill: { color: A },
      line: { color: A, transparency: 100 },
    });
  } else if (kind === 'square') {
    slide.addShape('rect', {
      x: box.x,
      y: box.y + 0.05,
      w: 0.13,
      h: 0.13,
      fill: { color: A },
      line: { color: A, transparency: 100 },
    });
  } else if (kind === 'dash') {
    slide.addShape('rect', {
      x: box.x,
      y: box.y + 0.09,
      w: 0.2,
      h: 0.05,
      fill: { color: A },
      line: { color: A, transparency: 100 },
    });
  } else if (kind === 'slash') {
    slide.addShape('line', {
      x: box.x + 0.05,
      y: box.y - 0.02,
      w: 0.09,
      h: 0.26,
      line: { color: A, width: 2.25 },
      flipV: true,
    });
  } else if (kind === 'chevron') {
    slide.addShape('chevron', {
      x: box.x,
      y: box.y + 0.01,
      w: 0.2,
      h: 0.17,
      fill: { color: A },
      line: { color: A, transparency: 100 },
    });
  } else if (kind === 'leaf') {
    slide.addShape('ellipse', {
      x: box.x,
      y: box.y,
      w: 0.17,
      h: 0.17,
      rotate: 315,
      fill: { color: A },
      line: { color: A, transparency: 100 },
    });
  } else if (kind === 'number') {
    H.addFittedText(
      slide,
      `0${(index || 0) + 1}`,
      { x: box.x, y: box.y - 0.04, w: 0.45, h: 0.3 },
      t,
      'chinese',
      'caption',
      { margin: 0, min: 12, max: 14, bold: true, colorRole: 'primary_accent', label: '强调编号' },
    );
  }
}

function drawCoverBand(slide, t, vl) {
  const A = H.color(t, 'primary_accent');
  if (vl.cover_band === 'bottom-band') {
    slide.addShape('rect', {
      x: 0,
      y: S_H - 0.3,
      w: S_W,
      h: 0.3,
      fill: { color: A },
      line: { color: A, transparency: 100 },
    });
  } else if (vl.cover_band === 'side-band') {
    slide.addShape('rect', {
      x: 0,
      y: 0,
      w: 0.28,
      h: S_H,
      fill: { color: A },
      line: { color: A, transparency: 100 },
    });
  } else if (vl.cover_band === 'corner-block') {
    slide.addShape('rect', {
      x: 0,
      y: S_H - 0.85,
      w: 0.85,
      h: 0.85,
      fill: { color: A },
      line: { color: A, transparency: 100 },
    });
  }
}

function drawPanel(slide, t, vl, box, emphasis = false) {
  const fillC = emphasis ? H.color(t, 'primary_accent') : H.color(t, 'surface');
  const shadow = H.softShadow(t) || undefined;
  switch (vl.panel) {
    case 'soft-fill':
      roundRect(slide, box, fillC, vl.radius, emphasis ? { shadow } : { transparency: 45, shadow });
      break;
    case 'outlined':
      roundRect(slide, box, H.color(t, 'canvas'), vl.radius, {
        line: emphasis ? H.color(t, 'primary_accent') : H.color(t, 'secondary_accent'),
        lineWidth: emphasis ? 2 : 1,
        shadow,
      });
      break;
    case 'edge-band':
      roundRect(slide, box, fillC, vl.radius, { transparency: 30, shadow });
      rect(
        slide,
        { x: box.x, y: box.y + 0.1, w: 0.07, h: box.h - 0.2 },
        H.color(t, 'primary_accent'),
      );
      break;
    case 'flush':
    default:
      break;
  }
}

function motif(slide, tokens, t, vl, dark) {
  const box = { w: 1.9, h: 1.9 };
  if (vl.motif_at === 'corner-tr') Object.assign(box, { x: S_W - 2.1, y: 0.18 });
  else if (vl.motif_at === 'corner-bl')
    Object.assign(box, { x: 0.2, y: S_H - 2.42, w: 1.75, h: 1.75 });
  else Object.assign(box, { x: S_W - 2.0, y: S_H / 2 - 0.95, w: 1.7, h: 1.7 });
  SVG.addCornerDecoration(slide, tokens.svg_reference.name, box, t, {
    transparency: dark ? 40 : 62,
  });
}

/* ── Signature chart grammar (hand-drawn, no gridlines, direct labels) ──── */

const CHART = {
  labels: ['完全忠实', '部分不忠实', '明显不忠实'],
  values: [68, 22, 10],
};

function drawChart(slide, t, vl, box) {
  const A = H.color(t, 'primary_accent');
  const B = H.color(t, 'secondary_accent');
  const max = Math.max(...CHART.values);

  if (vl.chart === 'columns') {
    const n = CHART.values.length;
    const slot = box.w / n;
    const bw = Math.min(0.72, slot * 0.5);
    const base = box.y + box.h - 0.34;
    CHART.values.forEach((v, i) => {
      const h = ((box.h - 0.72) * v) / max;
      const x = box.x + slot * i + (slot - bw) / 2;
      rect(slide, { x, y: base - h, w: bw, h }, i === 0 ? A : B, {
        transparency: i === 0 ? 0 : 45,
      });
      text(
        slide,
        `${v}%`,
        { x: x - 0.12, y: base - h - 0.38, w: bw + 0.24, h: 0.36 },
        t,
        'caption',
        {
          min: 12,
          max: 14,
          bold: true,
          align: 'center',
          colorRole: i === 0 ? 'primary_accent' : 'secondary_text',
        },
      );
      text(
        slide,
        CHART.labels[i],
        { x: x - 0.3, y: base + 0.05, w: bw + 0.6, h: 0.26 },
        t,
        'caption',
        { min: 11, max: 12, align: 'center', colorRole: 'secondary_text' },
      );
    });
  } else if (vl.chart === 'bars') {
    const n = CHART.values.length;
    const slot = box.h / n;
    const bh = Math.min(0.4, slot * 0.52);
    CHART.values.forEach((v, i) => {
      const y = box.y + slot * i + (slot - bh) / 2;
      const w = ((box.w - 1.3) * v) / max;
      rect(slide, { x: box.x + 1.15, y, w, h: bh }, i === 0 ? A : B, {
        transparency: i === 0 ? 0 : 45,
      });
      text(slide, CHART.labels[i], { x: box.x, y: y + 0.02, w: 1.05, h: 0.28 }, t, 'caption', {
        min: 11,
        max: 12,
        align: 'right',
        colorRole: 'secondary_text',
      });
      text(
        slide,
        `${v}%`,
        { x: box.x + 1.2 + w + 0.08, y: y + 0.02, w: 0.6, h: 0.28 },
        t,
        'caption',
        { min: 12, max: 13, bold: true, colorRole: i === 0 ? 'primary_accent' : 'secondary_text' },
      );
    });
  } else {
    // line
    const padX = 0.25;
    const base = box.y + box.h - 0.4;
    const spanW = box.w - padX * 2;
    const spanH = box.h - 0.85;
    const pts = CHART.values.map((v, i) => ({
      x: box.x + padX + (spanW * i) / (CHART.values.length - 1),
      y: base - (spanH * v) / max,
    }));
    pts.slice(0, -1).forEach((p, i) => {
      const q = pts[i + 1];
      slide.addShape('line', {
        x: Math.min(p.x, q.x),
        y: Math.min(p.y, q.y),
        w: Math.abs(q.x - p.x),
        h: Math.abs(q.y - p.y),
        line: { color: A, width: 2.5 },
        flipV: q.y < p.y,
      });
    });
    pts.forEach((p, i) => {
      const r = i === 0 ? 0.09 : 0.06;
      slide.addShape('ellipse', {
        x: p.x - r,
        y: p.y - r,
        w: r * 2,
        h: r * 2,
        fill: { color: i === 0 ? A : B },
        line: { color: A, transparency: 100 },
      });
      text(
        slide,
        `${CHART.values[i]}%`,
        { x: p.x - 0.4, y: p.y - 0.46, w: 0.8, h: 0.34 },
        t,
        'caption',
        {
          min: 12,
          max: 13,
          bold: true,
          align: 'center',
          colorRole: i === 0 ? 'primary_accent' : 'secondary_text',
        },
      );
      text(
        slide,
        CHART.labels[i],
        { x: p.x - 0.6, y: base + 0.08, w: 1.2, h: 0.26 },
        t,
        'caption',
        { min: 11, max: 12, align: 'center', colorRole: 'secondary_text' },
      );
    });
  }
}

/* ── Page system ────────────────────────────────────────────────────────── */

function pageChrome(slide, t, vl, tokens, dark, eyebrow, pageNo, opts = {}) {
  slide.background = { color: H.color(t, 'canvas') };
  if (vl.rule === 'top-band')
    rect(slide, { x: 0, y: 0, w: S_W, h: 0.12 }, H.color(t, 'primary_accent'));
  if (vl.decor !== 'restrained' && !opts.noMotif) motif(slide, tokens, t, vl, dark);
  text(slide, eyebrow, { x: M, y: 0.32, w: CW * 0.6, h: 0.3 }, t, 'caption', {
    min: 11,
    max: 12,
    colorRole: 'primary_accent',
    bold: true,
  });
  text(slide, pageNo, { x: S_W - M - 1.0, y: S_H - 0.46, w: 1.0, h: 0.3 }, t, 'caption', {
    min: 11,
    max: 11,
    align: 'right',
    colorRole: 'secondary_text',
  });
  slide.addShape('line', {
    x: M,
    y: S_H - 0.38,
    w: CW - 1.1,
    h: 0,
    line: { color: H.color(t, 'secondary_accent'), width: 0.75 },
  });
}

function pageTitle(slide, t, vl, str) {
  const box = { x: vl.rule === 'left-rail' ? M + 0.16 : M, y: 0.72, w: CW * 0.86, h: 0.78 };
  text(slide, str, box, t, 'title', { min: 32, max: 32, bold: true });
  drawRule(slide, t, vl, box);
}

/* ── The 9 template pages ───────────────────────────────────────────────── */

const PAGES = {
  cover: (slide, tokens, t, vl) => {
    slide.background = { color: H.color(t, 'canvas') };
    const zv = zone('cover-split', 'visual');
    SVG.addCornerDecoration(
      slide,
      tokens.svg_reference.name,
      { x: zv.x + 0.35, y: zv.y + 0.6, w: zv.w - 0.7, h: zv.h - 1.4 },
      t,
      { transparency: 25 },
    );
    rect(
      slide,
      { x: zv.x - 0.06, y: zv.y + 0.5, w: 0.07, h: zv.h - 1.0 },
      H.color(t, 'primary_accent'),
    );
    const zt = zone('cover-split', 'title');
    text(
      slide,
      '课程汇报 · AI 素养系列',
      { x: zt.x, y: zt.y - 0.14, w: zt.w, h: 0.3 },
      t,
      'caption',
      { min: 12, max: 13, colorRole: 'primary_accent', bold: true },
    );
    text(
      slide,
      'AI 会「编」，\n而且编得很自信',
      { x: zt.x, y: zt.y + 0.24, w: AREA.w * 0.5, h: 1.85 },
      t,
      'title',
      { min: 34, max: 40, bold: true },
    );
    drawRule(slide, t, vl, { x: zt.x, y: zt.y + 2.16, w: zt.w, h: 0.02 });
    const zb = zone('cover-split', 'body');
    text(slide, '幻觉的机制、证据与对策', { x: zb.x, y: zb.y, w: zb.w + 0.5, h: 0.46 }, t, 'body', {
      min: 18,
      max: 20,
      colorRole: 'secondary_text',
    });
    text(
      slide,
      '汇报人 · 2026 年 9 月 · 第 3 讲',
      { x: zb.x, y: zb.y + 0.56, w: zb.w + 0.5, h: 0.3 },
      t,
      'caption',
      { min: 11, max: 11, colorRole: 'secondary_text' },
    );
    drawCoverBand(slide, t, vl);
  },

  section: (slide, tokens, t, vl, n) => {
    slide.background = { color: H.color(t, 'canvas') };
    // 纹理背景按 visual_language.pattern 选择，透明度随 decor 密度
    if (vl.pattern && vl.pattern !== 'none') {
      const opac = { restrained: 0.03, balanced: 0.05, expressive: 0.07 };
      H.patternBackground(slide, t, { pattern: vl.pattern, opacity: opac[vl.decor] || 0.05 });
    }
    const zs = zone('section-statement', 'title') || { x: M, y: AREA.y + 0.5, w: CW, h: 1.2 };
    text(slide, `0${n}`, { x: M, y: zs.y - 0.3, w: 2.8, h: 1.95 }, t, 'title', {
      min: 78,
      max: 92,
      bold: true,
      colorRole: 'primary_accent',
    });
    text(slide, '机制：幻觉从哪里来', { x: M, y: zs.y + 1.55, w: CW * 0.8, h: 0.85 }, t, 'title', {
      min: 32,
      max: 32,
      bold: true,
    });
    drawRule(slide, t, vl, { x: M, y: zs.y + 2.5, w: CW, h: 0.02 });
    text(
      slide,
      '三类因素共同放大同一种失败模式',
      { x: M, y: zs.y + 2.72, w: CW * 0.7, h: 0.52 },
      t,
      'body',
      { min: 20, max: 20, colorRole: 'secondary_text' },
    );
  },

  claim: (slide, tokens, t, vl) => {
    pageChrome(slide, t, vl, tokens, false, '论点 · CLAIM', '04');
    pageTitle(slide, t, vl, '流畅 ≠ 正确，自信 ≠ 有据');
    const zf = zone('claim-focus', 'body');
    text(
      slide,
      '它先学会的是预测下一个\n最可能的词，',
      { x: zf.x, y: zf.y, w: zf.w, h: 1.12 },
      t,
      'title',
      { min: 22, max: 26, bold: true },
    );
    text(slide, '而不是先查证事实。', { x: zf.x, y: zf.y + 1.16, w: zf.w, h: 0.52 }, t, 'title', {
      min: 22,
      max: 26,
      bold: true,
      colorRole: 'primary_accent',
    });
    text(
      slide,
      '判断一条输出：是否有来源 · 是否可检索 · 是否在知识边界内',
      { x: zf.x, y: zf.y + 1.72, w: zf.w, h: 0.42 },
      t,
      'caption',
      { min: 12, max: 14, align: 'left', bold: true, colorRole: 'secondary_text' },
    );
  },

  data: (slide, tokens, t, vl) => {
    pageChrome(slide, t, vl, tokens, false, '证据 · EVIDENCE', '05');
    pageTitle(slide, t, vl, '示意数据：不忠实的摘要占比');
    const zf = zone('data-chart-takeaway', 'body');
    const zv = zone('data-chart-takeaway', 'visual');
    text(
      slide,
      '约三成摘要与原文不一致 —— 结论先于图表被读到',
      { x: zf.x, y: zf.y + 0.26, w: zf.w, h: 0.55 },
      t,
      'body',
      { min: 18, max: 20, colorRole: 'secondary_text' },
    );
    const panel = { x: zv.x, y: zv.y, w: zv.w, h: zv.h - 0.45 };
    drawPanel(slide, t, vl, panel);
    text(slide, '≈30%', { x: panel.x + 0.35, y: panel.y + 0.32, w: 2.3, h: 1.05 }, t, 'title', {
      min: 38,
      max: 44,
      bold: true,
      colorRole: 'primary_accent',
    });
    text(
      slide,
      '课堂示意分组\n非已发表统计',
      { x: panel.x + 0.35, y: panel.y + 1.5, w: 2.1, h: 0.72 },
      t,
      'caption',
      { min: 11, max: 12, colorRole: 'secondary_text' },
    );
    drawChart(slide, t, vl, {
      x: panel.x + 3.0,
      y: panel.y + 0.25,
      w: panel.w - 3.35,
      h: panel.h - 0.5,
    });
    text(
      slide,
      '示意数据 · E2 · 图表职责是支撑一句结论，不是展示所有数字',
      { x: M, y: zv.y + zv.h - 0.32, w: CW, h: 0.28 },
      t,
      'caption',
      { min: 11, max: 11, colorRole: 'secondary_text' },
    );
  },

  compare: (slide, tokens, t, vl) => {
    pageChrome(slide, t, vl, tokens, false, '对策 · MITIGATION', '06');
    pageTitle(slide, t, vl, '先取证，再回答');
    const zb = zone('compare-before-after', 'body');
    const zv = zone('compare-before-after', 'visual');
    const preferred = { x: zb.x, y: zb.y, w: zb.w + (zv.x - (zb.x + zb.w)) * 0.7, h: zb.h };
    const other = {
      x: zv.x + (zv.x - (zb.x + zb.w)) * 0.3,
      y: zv.y,
      w: zv.w - (zv.x - (zb.x + zb.w)) * 0.3,
      h: zv.h,
    };
    const panelH = Math.min(zb.h, 2.5);
    const prefBox = { x: preferred.x, y: preferred.y, w: preferred.w, h: panelH };
    const otherBox = { x: other.x, y: other.y, w: other.w, h: panelH };
    drawPanel(slide, t, vl, prefBox, true);
    drawPanel(slide, t, vl, otherBox, false);
    const pi = vl.panel === 'flush';
    text(
      slide,
      '推荐 · 先检索再回答',
      { x: prefBox.x + 0.32, y: prefBox.y + 0.22, w: prefBox.w - 0.64, h: 0.5 },
      t,
      'body',
      { min: 20, max: 22, bold: true, colorRole: pi ? 'primary_accent' : undefined },
    );
    text(
      slide,
      '引用可核验\n补足知识边界\n把查证写进流程',
      { x: prefBox.x + 0.32, y: prefBox.y + 0.82, w: prefBox.w - 0.64, h: panelH - 1.05 },
      t,
      'body',
      { min: 18, max: 20, align: 'left', colorRole: pi ? 'secondary_text' : undefined },
    );
    text(
      slide,
      '对照',
      { x: otherBox.x + 0.28, y: otherBox.y + 0.2, w: otherBox.w - 0.56, h: 0.32 },
      t,
      'caption',
      { min: 12, max: 13, bold: true, colorRole: 'secondary_text' },
    );
    text(
      slide,
      '仅提示「不要编」',
      { x: otherBox.x + 0.28, y: otherBox.y + 0.56, w: otherBox.w - 0.56, h: 0.46 },
      t,
      'body',
      { min: 18, max: 20, bold: true, colorRole: 'secondary_text' },
    );
    text(
      slide,
      '零成本，但效果不稳定。',
      { x: otherBox.x + 0.28, y: otherBox.y + 1.14, w: otherBox.w - 0.56, h: 0.6 },
      t,
      'caption',
      { min: 12, max: 13, colorRole: 'secondary_text' },
    );
    text(
      slide,
      '两种做法的差异不是成本，而是把查证交给流程还是交给自觉。',
      { x: zb.x, y: zb.y + zb.h - 0.5, w: CW, h: 0.42 },
      t,
      'caption',
      { min: 12, max: 13, align: 'left', colorRole: 'secondary_text' },
    );
  },

  timeline: (slide, tokens, t, vl) => {
    pageChrome(slide, t, vl, tokens, false, '路径 · PROCESS', '07');
    pageTitle(slide, t, vl, '从机制到对策的推理链');
    const z = zone('timeline-roadmap', 'visual');
    const steps = [
      ['训练目标', '最大化似然'],
      ['数据噪声', '真假混杂'],
      ['知识边界', '不知道就猜'],
      ['流程对策', '先取证再回答'],
    ];
    const y = z.y + z.h * 0.42;
    slide.addShape('line', {
      x: z.x + 0.3,
      y,
      w: z.w - 0.6,
      h: 0,
      line: { color: H.color(t, 'secondary_accent'), width: 1.5 },
    });
    const slot = (z.w - 0.6) / 3;
    steps.forEach(([name, desc], i) => {
      const cx = z.x + 0.3 + slot * i;
      const last = i === steps.length - 1;
      const r = last ? 0.13 : 0.09;
      slide.addShape('ellipse', {
        x: cx - r,
        y: y - r,
        w: r * 2,
        h: r * 2,
        fill: { color: last ? H.color(t, 'primary_accent') : H.color(t, 'surface') },
        line: { color: H.color(t, 'primary_accent'), width: last ? 0 : 1.5 },
      });
      text(slide, `0${i + 1}`, { x: cx - 0.5, y: y - 0.85, w: 1.0, h: 0.3 }, t, 'caption', {
        min: 12,
        max: 13,
        bold: true,
        align: 'center',
        colorRole: 'primary_accent',
      });
      text(slide, name, { x: cx - 0.85, y: y + 0.26, w: 1.7, h: 0.5 }, t, 'body', {
        min: 18,
        max: 20,
        bold: true,
        align: 'center',
      });
      text(slide, desc, { x: cx - 0.85, y: y + 0.82, w: 1.7, h: 0.34 }, t, 'caption', {
        min: 11,
        max: 12,
        align: 'center',
        colorRole: 'secondary_text',
      });
    });
    drawPanel(slide, t, vl, { x: z.x + z.w * 0.2, y: y + 1.15, w: z.w * 0.6, h: 0.55 });
    text(
      slide,
      '结论：三者共同放大「合理但未核实」的输出',
      { x: z.x + z.w * 0.2 + 0.2, y: y + 1.24, w: z.w * 0.6 - 0.4, h: 0.38 },
      t,
      'body',
      { min: 16, max: 18, align: 'center' },
    );
  },

  quote: (slide, tokens, t, vl) => {
    pageChrome(slide, t, vl, tokens, false, '引语 · QUOTE', '08');
    const z = zone('quote-focus', 'body');
    text(slide, '「', { x: z.x - 0.1, y: z.y - 0.3, w: 1.3, h: 1.62 }, t, 'title', {
      min: 66,
      max: 72,
      bold: true,
      colorRole: 'primary_accent',
    });
    text(
      slide,
      '流畅是一种能力，\n忠实是一种选择。',
      { x: z.x + 0.85, y: z.y + 0.35, w: z.w * 0.82, h: 1.7 },
      t,
      'title',
      { min: 34, max: 34, bold: true },
    );
    drawRule(slide, t, vl, { x: z.x + 0.85, y: z.y + 2.2, w: z.w * 0.8, h: 0.02 });
    text(
      slide,
      '—— 把「查证」放进流程，而不是指望模型自觉',
      { x: z.x + 0.85, y: z.y + 2.42, w: z.w * 0.8, h: 0.36 },
      t,
      'caption',
      { min: 12, max: 13, colorRole: 'secondary_text' },
    );
  },

  annotated: (slide, tokens, t, vl) => {
    pageChrome(slide, t, vl, tokens, false, '案例 · ANNOTATED', '09');
    pageTitle(slide, t, vl, '一条检索不到的「文献」');
    const zl = zone('visual-annotated', 'visual');
    const zr = zone('visual-annotated', 'body');
    // typographic illustration: layered geometry in the style's own tones
    const g = { x: zl.x + 0.2, y: zl.y + 0.15, w: zl.w - 0.4, h: zl.h - 0.3 };
    drawPanel(slide, t, vl, g);
    slide.addShape('ellipse', {
      x: g.x + g.w * 0.18,
      y: g.y + g.h * 0.16,
      w: g.w * 0.52,
      h: g.w * 0.52,
      fill: { color: H.color(t, 'surface'), transparency: 20 },
      line: { color: H.color(t, 'secondary_accent'), width: 1 },
    });
    slide.addShape('ellipse', {
      x: g.x + g.w * 0.4,
      y: g.y + g.h * 0.34,
      w: g.w * 0.34,
      h: g.w * 0.34,
      fill: { color: H.color(t, 'primary_accent'), transparency: 25 },
      line: { color: H.color(t, 'primary_accent'), transparency: 100 },
    });
    rect(
      slide,
      { x: g.x + g.w * 0.14, y: g.y + g.h * 0.74, w: g.w * 0.66, h: 0.05 },
      H.color(t, 'primary_accent'),
    );
    SVG.addCornerDecoration(
      slide,
      tokens.svg_reference.name,
      { x: g.x + g.w * 0.6, y: g.y + 0.1, w: g.w * 0.34, h: g.w * 0.34 },
      t,
      { transparency: 35 },
    );
    const items = ['作者与年份格式自洽', '期刊名真实存在', '组合后检索不到'];
    items.forEach((s, i) => {
      const y = zr.y + 0.2 + i * 0.66;
      emphasisMark(slide, t, vl, { x: zr.x + 0.05, y: y + 0.02, w: 0.3, h: 0.3 }, i);
      text(slide, s, { x: zr.x + 0.35, y, w: zr.w - 0.3, h: 0.48 }, t, 'body', {
        min: 16,
        max: 18,
        align: 'left',
        bold: i === 2,
      });
    });
    text(
      slide,
      '每个局部都合理，组合起来才失效 —— 核对要看整体是否可溯源。',
      { x: M, y: zl.y + zl.h + 0.1, w: CW, h: 0.28 },
      t,
      'caption',
      { min: 11, max: 11, colorRole: 'secondary_text' },
    );
  },

  kpi: (slide, tokens, t, vl) => {
    pageChrome(slide, t, vl, tokens, false, '指标 · KPI', '05');
    pageTitle(slide, t, vl, '三个数字读懂现状');
    V.addMetricDashboard(
      slide,
      {
        metrics: [
          { value: '3 类', label: '失败诱因' },
          { value: '≈30%', label: '示意不忠实占比' },
          { value: '0 条', label: '可溯源引用' },
        ],
        emphasis: 1,
      },
      { x: M, y: CONTENT_TOP + 0.35, w: CW, h: S_H - CONTENT_TOP - 1.75 },
      t,
      'chinese',
    );
    text(
      slide,
      '先读放大的关键数字，其余指标按重要度排列',
      { x: M, y: S_H - 0.92, w: CW, h: 0.32 },
      t,
      'caption',
      { min: 11, max: 11, colorRole: 'secondary_text' },
    );
  },

  architecture: (slide, tokens, t, vl) => {
    pageChrome(slide, t, vl, tokens, false, '结构 · SYSTEM', '09');
    pageTitle(slide, t, vl, '把取证写进生成流程');
    V.addArchitecture(
      slide,
      { nodes: ['提问与意图', '外部检索取证', '生成与引用', '人工核验'] },
      { x: M, y: CONTENT_TOP + 0.35, w: CW, h: S_H - CONTENT_TOP - 1.75 },
      t,
      'chinese',
    );
    text(
      slide,
      '每一层只对上一层负责 —— 核验层是流程的一部分，不是事后补救',
      { x: M, y: S_H - 0.92, w: CW, h: 0.32 },
      t,
      'caption',
      { min: 11, max: 11, colorRole: 'secondary_text' },
    );
  },

  references: (slide, tokens, t, vl) => {
    pageChrome(slide, t, vl, tokens, false, '参考 · REFERENCES', '11', { noMotif: true });
    pageTitle(slide, t, vl, '参考与来源');
    const refs = [
      'Ji et al. 2023 · Survey of Hallucination in Natural Language Generation · ACM Computing Surveys',
      '课程讲义 · 第 3 讲 · 语言模型的概率本质（E1）',
      '课堂示意数据 · E2 · 非已发表统计，仅用于演示证据读法',
    ];
    refs.forEach((s, i) => {
      const y = CONTENT_TOP + 0.4 + i * 0.95;
      emphasisMark(slide, t, vl, { x: M, y, w: 0.32, h: 0.32 }, i);
      text(slide, s, { x: M + 0.55, y, w: CW - 0.6, h: 0.85 }, t, 'body', {
        min: 14,
        max: 18,
        align: 'left',
        colorRole: 'secondary_text',
      });
    });
    text(
      slide,
      '证据闭环：每条 reference 都能回指到正文的具体页面',
      { x: M, y: S_H - 0.92, w: CW, h: 0.32 },
      t,
      'caption',
      { min: 11, max: 11, colorRole: 'secondary_text' },
    );
  },

  closing: (slide, tokens, t, vl) => {
    slide.background = { color: H.color(t, 'canvas') };
    const zf = zone('closing-takeaway', 'title');
    text(slide, '结语', { x: M, y: 0.34, w: 3.0, h: 0.28 }, t, 'caption', {
      min: 11,
      max: 11,
      colorRole: 'primary_accent',
      bold: true,
    });
    text(
      slide,
      '流畅是能力，\n忠实是选择。',
      { x: zf.x, y: zf.y, w: zf.w * 0.85, h: 2.1 },
      t,
      'title',
      { min: 38, max: 44, bold: true },
    );
    drawRule(slide, t, vl, { x: zf.x, y: zf.y + 2.05, w: zf.w, h: 0.02 });
    text(
      slide,
      '无法要求模型凭自觉变得诚实，但可以在流程里强制它先取证。',
      { x: zf.x, y: zf.y + 2.3, w: zf.w, h: 0.75 },
      t,
      'body',
      { min: 18, max: 20, colorRole: 'secondary_text' },
    );
    slide.addShape('line', {
      x: M,
      y: S_H - 0.72,
      w: CW,
      h: 0,
      line: { color: H.color(t, 'secondary_accent'), width: 0.75 },
    });
    text(
      slide,
      '来源 · Ji et al. 2023 (ACM Computing Surveys) · 课堂示意数据 (E2)',
      { x: M, y: S_H - 0.62, w: CW, h: 0.28 },
      t,
      'caption',
      { min: 11, max: 12, colorRole: 'secondary_text' },
    );
    text(slide, '谢谢 · Q&A', { x: S_W - M - 2.0, y: S_H - 0.62, w: 2.0, h: 0.28 }, t, 'caption', {
      min: 11,
      max: 11,
      align: 'right',
      colorRole: 'primary_accent',
      bold: true,
    });
  },
};

/* ── Emit ───────────────────────────────────────────────────────────────── */

const ORDER = [
  'cover',
  'section',
  'claim',
  'data',
  'kpi',
  'compare',
  'timeline',
  'quote',
  'architecture',
  'annotated',
  'references',
  'closing',
];
let slideNo = 0;
for (const entry of INPUT.styles) {
  const tokens = entry.tokens;
  const vl = tokens.visual_language;
  if (!vl) throw new Error(`${entry.key}: tokens.visual_language missing`);
  ORDER.forEach((pageId, i) => {
    const slide = pptx.addSlide();
    slideNo += 1;
    const t = H.paletteMode(
      tokens,
      pageId === 'cover' || pageId === 'section' || pageId === 'closing' ? 'dark' : 'light',
    );
    PAGES[pageId](slide, tokens, t, vl, i);
    if (pageId !== 'cover' && pageId !== 'closing') {
      // page number uses the in-deck counter for easy navigation
    }
  });
}

const OUT = process.argv[2];
if (!OUT) throw new Error('usage: node gallery.js <output.pptx>');
pptx.writeFile({ fileName: OUT }).then(() => {
  process.stdout.write(`wrote ${OUT}: ${slideNo} slides\n`);
});
