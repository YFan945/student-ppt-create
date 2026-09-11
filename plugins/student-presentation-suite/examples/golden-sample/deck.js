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

// ── 1. Cover — navy field, oversized thesis, echo motif ──────────────────
{
  const { slide, tokens } = page('dark');
  rect(slide, { x: 0, y: 0, w: S_W, h: S_H }, NAVY);

  // Echo motif: fluent repetition fading out, one unverified claim standing out.
  const bars = [
    { w: 3.0, t: 84 },
    { w: 2.55, t: 76 },
    { w: 2.1, t: 66 },
    { w: 1.65, t: 52 },
    { w: 1.2, t: 0 },
  ];
  const barH = 0.26;
  const step = 0.44;
  const bx = 5.0;
  const by = 1.38;
  bars.forEach((bar, index) => {
    rect(slide, { x: bx, y: by + index * step, w: bar.w, h: barH }, accent(tokens), bar.t, ROUND);
  });
  text(
    slide,
    '重复生成\n≠\n已核实',
    { x: bx - 0.04, y: by + bars.length * step + 0.14, w: 3.4, h: 1.0 },
    tokens,
    'caption',
    { margin: 0, fontSize: 12, colorRole: 'secondary_text', label: '母题注释' },
  );

  text(slide, '课堂汇报 · 人工智能导论', { x: M, y: 1.0, w: 4.3, h: 0.26 }, tokens, 'caption', {
    margin: 0,
    colorRole: 'primary_accent',
    label: '封面眉标',
  });
  title(slide, ['AI 会「编」，', '而且编得很自信'], { x: M, y: 1.4, w: 4.7 }, tokens, 40, {
    label: '封面标题',
    accentLines: [1],
  });
  hrule(slide, M, 3.5, 1.4, accent(tokens), 3);
  text(
    slide,
    '从语言模型的训练目标理解「幻觉」',
    { x: M, y: 3.7, w: 4.5, h: 0.34 },
    tokens,
    'caption',
    { margin: 0, fontSize: 13, colorRole: 'secondary_text', label: '封面副标题' },
  );
  footer(slide, tokens, 'AI 幻觉 · 课程汇报', '01 / 09');
}

// ── 2. Hook — question title, thesis with an emphasised line ────────────
{
  const { slide, tokens } = page('light');
  pageTitle(slide, tokens, '问题', '为什么一个模型能立刻给出流畅的答案？');

  title(
    slide,
    ['因为它先学会的是', '预测下一个最可能的词，', '而不是先查证事实。'],
    { x: M, y: CONTENT_TOP + 0.16, w: CW * 0.6 },
    tokens,
    26,
    { label: '核心命题', accentLines: [1] },
  );

  const chipX = M + CW * 0.66;
  const chipW = CW * 0.34;
  text(
    slide,
    '两条判断',
    { x: chipX, y: CONTENT_TOP + 0.1, w: chipW, h: 0.26 },
    tokens,
    'caption',
    { margin: 0, colorRole: 'secondary_text', label: '小标题' },
  );
  ['流畅 ≠ 正确', '自信 ≠ 有据'].forEach((label, index) => {
    const y = CONTENT_TOP + 0.46 + index * 0.78;
    rect(slide, { x: chipX, y, w: chipW, h: 0.62 }, accent(tokens), 90, ROUND);
    vrule(slide, chipX, y, 0.62, accent(tokens), 2.5);
    text(
      slide,
      label,
      { x: chipX + 0.24, y: y + 0.1, w: chipW - 0.4, h: 0.42 },
      tokens,
      'caption',
      { margin: 0, fontSize: 15, colorRole: 'primary_accent', label: '判断要点' },
    );
  });
  text(
    slide,
    '后面每个结论都会回到它',
    { x: chipX, y: CONTENT_TOP + 2.14, w: chipW, h: 0.26 },
    tokens,
    'caption',
    { margin: 0, fontSize: 11, colorRole: 'secondary_text', label: '提示' },
  );
  footer(slide, tokens, 'AI 幻觉 · 课程汇报', '02 / 09');
}

// ── 3. Section divider — navy field, oversized numeral ─────────────────
{
  const { slide, tokens } = page('dark');
  rect(slide, { x: 0, y: 0, w: S_W, h: S_H }, NAVY);

  text(slide, '01', { x: M, y: 1.66, w: 2.2, h: 1.66 }, tokens, 'title', {
    min: 64,
    max: 64,
    bold: true,
    margin: 0,
    colorRole: 'primary_accent',
    label: '章节序号',
  });
  title(slide, ['幻觉不是偶发 bug'], { x: M + 2.1, y: 1.96, w: CW - 2.1 }, tokens, 32, {
    label: '章节标题',
  });
  hrule(slide, M + 2.1, 2.86, 1.2, accent(tokens), 3);
  text(
    slide,
    '从训练目标进入：它优化的是「像」，不是「真」',
    { x: M + 2.1, y: 3.06, w: CW - 2.1, h: 0.36 },
    tokens,
    'caption',
    { margin: 0, fontSize: 13, colorRole: 'secondary_text', label: '章节引导' },
  );
  // 章节页此前是整份 deck 唯一没有页脚的页面：内容只占页面高度 31%，
  // 底部留白高达 39%，深色场上显得悬空；且它不计数导致后续页码整体错位。
  footer(slide, tokens, 'AI 幻觉 · 课程汇报', '03 / 09');
}

// ── 4. Mechanism — three causes converge on one dominant result ─────────
{
  const { slide, tokens } = page('light');
  const dark = H.paletteMode(TOKENS, 'dark');
  pageTitle(slide, tokens, '机制', '三类因素在放大「合理但未核实」');

  const causes = ['训练目标：最大化似然', '数据噪声：真假混杂', '知识边界：不知道就猜'];
  const cellW = (CW - 0.5) / 3;
  const topY = CONTENT_TOP + 0.24;
  causes.forEach((label, index) => {
    const x = M + index * (cellW + 0.25);
    hrule(slide, x, topY, cellW * 0.45, accent(tokens), 2);
    text(slide, label, { x, y: topY + 0.16, w: cellW, h: 0.5 }, tokens, 'caption', {
      margin: 0,
      fontSize: 14,
      colorRole: 'primary_text',
      label: `因素 ${index + 1}`,
    });
  });

  // Connectors converge into the dominant conclusion panel.
  const mergeX = S_W / 2;
  const mergeY = topY + 0.9;
  causes.forEach((_, index) => {
    const x = M + index * (cellW + 0.25) + cellW / 2;
    slide.addShape(LINE, {
      x: Math.min(x, mergeX),
      y: topY + 0.72,
      w: Math.abs(mergeX - x),
      h: mergeY - (topY + 0.72),
      line: { color: muted(tokens), width: 1.25 },
    });
  });

  const panel = { x: M, y: mergeY + 0.12, w: CW, h: 1.56 };
  rect(slide, panel, NAVY, 0, ROUND);
  text(
    slide,
    '都在放大同一种失败模式：\n输出「合理但未核实」',
    { x: panel.x + 0.44, y: panel.y + 0.3, w: panel.w - 0.88, h: 1.14 },
    dark,
    'quote',
    { min: 22, max: 24, margin: 0, bold: true, align: 'left', label: '共同结果' },
  );
  footer(slide, tokens, 'AI 幻觉 · 课程汇报', '04 / 09');
}

// ── 5. Evidence — big number dominates, chart proves, source closes ─────
{
  const { slide, tokens } = page('light');
  pageTitle(slide, tokens, '证据', '示意数据：流畅的摘要有多少不忠实');

  text(slide, '≈30', { x: M, y: CONTENT_TOP + 0.22, w: 2.7, h: 1.42 }, tokens, 'title', {
    min: 58,
    max: 58,
    bold: true,
    margin: 0,
    colorRole: 'primary_accent',
    label: '关键数字',
  });
  text(
    slide,
    '约三成摘要与原文不一致',
    { x: M, y: CONTENT_TOP + 1.78, w: 2.9, h: 0.34 },
    tokens,
    'caption',
    { margin: 0, fontSize: 13, colorRole: 'primary_text', label: '数字说明' },
  );
  hrule(slide, M, CONTENT_TOP + 2.24, 2.4, accent(tokens), 2.5);

  slide.addChart(
    pptx.ChartType.bar,
    [{ name: '占比', labels: ['完全忠实', '部分不忠实', '明显不忠实'], values: [68, 22, 10] }],
    {
      x: M + CW * 0.4,
      y: CONTENT_TOP + 0.04,
      w: CW * 0.6,
      h: 2.5,
      barDir: 'col',
      chartColors: [accent(tokens)],
      showTitle: false,
      showLegend: false,
      showValue: true,
      dataLabelPosition: 'outEnd',
      dataLabelFontFace: F.body,
      dataLabelFontSize: 18,
      dataLabelColor: ink(tokens),
      catAxisLabelFontFace: F.body,
      catAxisLabelFontSize: 13,
      catAxisLabelColor: muted(tokens),
      catAxisLineShow: false,
      valAxisHidden: true,
      // 轴即使隐藏，柱高比例仍由轴范围决定；渲染回读门禁要求显式 min/max，
      // 禁止自动缩放把 68/84/89 这类差异抹平。
      valAxisMaxVal: 80,
      valAxisMinVal: 0,
      valAxisMajorUnit: 20,
      valGridLine: { style: 'none' },
      catGridLine: { style: 'none' },
      border: { pt: 0, color: H.color(tokens, 'canvas') },
      barGapWidthPct: 110,
      altText: '示意柱状图：完全忠实 68、部分不忠实 22、明显不忠实 10',
    },
  );

  text(
    slide,
    '示意数据，非已发表统计；用于演示「结论先于图表」的读法。',
    { x: M, y: CONTENT_TOP + 2.56, w: CW, h: 0.3 },
    tokens,
    'caption',
    { margin: 0, fontSize: 11, colorRole: 'secondary_text', label: '来源说明' },
  );
  footer(slide, tokens, 'AI 幻觉 · 课程汇报', '05 / 09');
}

// ── 6. Case — evidence rail: an unsourced citation, typeset ─────────────
{
  const { slide, tokens } = page('light');
  pageTitle(slide, tokens, '案例', '案例：一条检索不到的「文献」');

  const left = { x: M, y: CONTENT_TOP, w: CW * 0.58, h: 2.62 };
  rect(slide, left, H.color(tokens, 'surface'));
  hrule(slide, left.x, left.y, left.w, muted(tokens), 0.75);
  vrule(slide, left.x, left.y, 0.9, accent(tokens), 3);
  text(
    slide,
    '模型给出的引用 · 格式自洽，却检索不到',
    { x: left.x + 0.36, y: left.y + 0.26, w: left.w - 0.66, h: 0.3 },
    tokens,
    'caption',
    { margin: 0, fontSize: 12, colorRole: 'primary_accent', label: '证据标题' },
  );
  text(
    slide,
    'Wang, L., & Chen, R. (2021).\nFaithfulness in Neural\nSummarization. Journal of\nLanguage Modelling, 12(3),\n245-263.',
    { x: left.x + 0.36, y: left.y + 0.72, w: left.w - 0.66, h: 1.7 },
    tokens,
    'caption',
    { min: 12, max: 14, margin: 0, align: 'left', colorRole: 'primary_text', label: '示例引用' },
  );

  const rightX = M + CW * 0.64;
  const rightW = CW * 0.36;
  const rowH = 0.78;
  ['作者与年份格式自洽', '期刊名真实存在', '组合后检索不到'].forEach((label, index) => {
    const y = CONTENT_TOP + index * (rowH + 0.14);
    vrule(slide, rightX, y + 0.1, 0.44, accent(tokens), 2.5);
    text(slide, label, { x: rightX + 0.28, y, w: rightW - 0.28, h: 0.64 }, tokens, 'caption', {
      margin: 0,
      fontSize: 15,
      colorRole: 'primary_text',
      label: `标注 ${index + 1}`,
    });
    if (index < 2) {
      hrule(slide, rightX, y + rowH + 0.06, rightW, muted(tokens), 0.75);
    }
  });
  footer(slide, tokens, 'AI 幻觉 · 课程汇报', '06 / 09');
}

// ── 7. Mitigation — asymmetric comparison, recommended option dominates ─
{
  const { slide, tokens } = page('light');
  pageTitle(slide, tokens, '对策', '降低幻觉：先取证，再回答');

  const preferred = { x: M, y: CONTENT_TOP, w: CW * 0.6, h: 2.6 };
  rect(slide, preferred, accent(tokens), 88, ROUND);
  vrule(slide, preferred.x, preferred.y, preferred.h, accent(tokens), 3);
  text(
    slide,
    '推荐',
    { x: preferred.x + 0.36, y: preferred.y + 0.22, w: 1.2, h: 0.26 },
    tokens,
    'caption',
    { margin: 0, fontSize: 12, colorRole: 'primary_accent', label: '推荐标记' },
  );
  title(
    slide,
    ['先检索再回答（RAG）'],
    { x: preferred.x + 0.36, y: preferred.y + 0.56, w: preferred.w - 0.72 },
    tokens,
    24,
    { label: '首选方案' },
  );
  text(
    slide,
    '引用可核验，补足知识边界\n把查证写进流程',
    { x: preferred.x + 0.36, y: preferred.y + 1.3, w: preferred.w - 0.72, h: 1.16 },
    tokens,
    'body',
    { margin: 0, align: 'left', bullet: false, lineSpacingMultiple: 1.3, label: '首选理由' },
  );

  const alt = { x: M + CW * 0.66, y: CONTENT_TOP + 0.34, w: CW * 0.34, h: 2.0 };
  hrule(slide, alt.x, alt.y, alt.w, muted(tokens), 0.75);
  text(
    slide,
    '仅提示「不要编」',
    { x: alt.x, y: alt.y + 0.26, w: alt.w, h: 0.6 },
    tokens,
    'caption',
    { margin: 0, fontSize: 15, colorRole: 'primary_text', label: '对照方案' },
  );
  text(
    slide,
    '零成本，但效果不稳定。',
    { x: alt.x, y: alt.y + 0.94, w: alt.w, h: 1.0 },
    tokens,
    'caption',
    { margin: 0, fontSize: 12, colorRole: 'secondary_text', label: '对照说明' },
  );
  footer(slide, tokens, 'AI 幻觉 · 课程汇报', '07 / 09');
}

// ── 8. Recap — argument path, conclusion emphasized ─────────────────────
{
  const { slide, tokens } = page('light');
  pageTitle(slide, tokens, '回顾', '回到这条推理链');

  const steps = ['幻觉源于优化目标', '流畅不等于忠实', '先取证，再回答'];
  const cellW = (CW - 0.6) / 3;
  const spineY = CONTENT_TOP + 0.8;

  hrule(slide, M + cellW / 2, spineY, CW - cellW, accent(tokens), 1.25);

  steps.forEach((label, index) => {
    const x = M + index * (cellW + 0.3);
    const cx = x + cellW / 2;
    const last = index === steps.length - 1;
    const radius = last ? 0.3 : 0.22;
    slide.addShape(DOT, {
      x: cx - radius,
      y: spineY - radius,
      w: radius * 2,
      h: radius * 2,
      fill: { color: last ? accent(tokens) : H.color(tokens, 'canvas') },
      line: { color: accent(tokens), width: last ? 0 : 1.5 },
    });
    text(
      slide,
      String(index + 1),
      { x: cx - radius, y: spineY - radius, w: radius * 2, h: radius * 2 },
      tokens,
      'caption',
      {
        margin: 0,
        fontSize: last ? 15 : 13,
        align: 'center',
        valign: 'mid',
        colorRole: last ? 'canvas' : 'primary_accent',
        label: `步骤 ${index + 1} 序号`,
      },
    );
    text(slide, label, { x, y: spineY + 0.46, w: cellW, h: 0.78 }, tokens, 'caption', {
      margin: 0,
      fontSize: last ? 17 : 14,
      align: 'center',
      colorRole: last ? 'primary_accent' : 'primary_text',
      label: `步骤 ${index + 1} 说明`,
    });
  });

  hrule(slide, M, CONTENT_TOP + 2.42, CW, muted(tokens), 0.75);
  text(
    slide,
    '这三步是有先后的推理链，不是三个并列要点。',
    { x: M, y: CONTENT_TOP + 2.54, w: CW, h: 0.3 },
    tokens,
    'caption',
    { margin: 0, fontSize: 11, colorRole: 'secondary_text', label: '回顾提示' },
  );
  footer(slide, tokens, 'AI 幻觉 · 课程汇报', '08 / 09');
}

// ── 9. Closing — callback thesis + closed evidence loop ─────────────────
{
  const { slide, tokens } = page('dark');
  rect(slide, { x: 0, y: 0, w: S_W, h: S_H }, NAVY);
  rect(slide, { x: M, y: 1.0, w: 1.4, h: 0.06 }, accent(tokens));

  title(slide, ['流畅是能力，', '忠实是选择。'], { x: M, y: 1.36, w: CW * 0.9 }, tokens, 38, {
    label: '结语',
    accentLines: [1],
  });
  text(
    slide,
    '把「查证」放进流程，而不是指望模型自觉。',
    { x: M, y: 3.24, w: CW * 0.8, h: 0.34 },
    tokens,
    'caption',
    { margin: 0, fontSize: 13, colorRole: 'secondary_text', label: '结语补充' },
  );

  hrule(slide, M, 3.86, CW, H.color(tokens, 'secondary_accent'), 0.75);
  text(
    slide,
    '参考：Ji et al., Survey of Hallucination in Natural Language Generation, ACM Computing Surveys, 2023；本汇报作者，课堂示意数据（2026，非已发表统计）。',
    { x: M, y: 3.96, w: CW, h: 0.92 },
    tokens,
    'caption',
    { margin: 0, fontSize: 11, colorRole: 'secondary_text', label: '参考来源' },
  );
  footer(slide, tokens, '谢谢 · Q&A', '09 / 09');
}

pptx.writeFile({ fileName: process.argv[2] });
