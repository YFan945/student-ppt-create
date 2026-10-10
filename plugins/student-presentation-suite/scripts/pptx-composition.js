'use strict';

/**
 * Generation-time composition.
 *
 * A move names the page's visual job. This module computes type scale, mass,
 * and whitespace while drawing — the model supplies the claim and the supports,
 * not a rectangle from the 36-layout catalog. If the copy cannot fit the move,
 * renderMove throws layoutFit and the caller may fall back to an archetype.
 */

const H = require('./pptx-helpers.js');
const V = require('./pptx-visuals.js');

const MOVES = ['thesis', 'weighted', 'metric', 'proof', 'sequence', 'figure'];

function layoutFit(message) {
  const error = new RangeError(message);
  error.layoutFit = true;
  return error;
}

function linesOf(value) {
  if (Array.isArray(value)) return value.map((item) => String(item || '').trim()).filter(Boolean);
  if (value === undefined || value === null || value === '') return [];
  return [String(value).trim()].filter(Boolean);
}

function register(ctx, element) {
  const n = ctx.slideNumber;
  if (ctx.registry && Number.isInteger(n) && n >= 1) ctx.registry.register(n, element);
}

function contentFrame(area, slots) {
  const key = slots.key_line ? String(slots.key_line).trim() : '';
  if (!key) return { area, key: '', keyBand: null };
  const bandH = 0.72;
  return {
    area: { x: area.x, y: area.y, w: area.w, h: Math.max(1.4, area.h - bandH - 0.1) },
    key,
    keyBand: { x: area.x, y: area.y + area.h - bandH, w: area.w, h: bandH },
  };
}

/**
 * Measure first. Drawing happens only after every text box fits, so a
 * layoutFit fallback does not leave a half-painted slide.
 */
function planText(ctx, text, box, role, options = {}) {
  const lang = ctx.lang || 'chinese';
  const sizes = H.fontSizeScale(ctx.tokens, lang);
  const floors = {
    stat: 36,
    subtitle: sizes.subtitle,
    body: sizes.body,
    label: sizes.label,
  };
  const ceilings = {
    stat: 60,
    subtitle: sizes.bodyMax,
    body: sizes.bodyMax,
    label: 20,
  };
  const floor = floors[role] || sizes.body;
  const ceiling = options.max || ceilings[role] || sizes.bodyMax;
  const requested = Math.max(floor, Number(options.min) || 0);
  const measure = (min) =>
    H.fitText(String(text), box, {
      min,
      max: Math.max(min, ceiling),
      margin: options.margin ?? 0,
      role,
      align: options.align,
      balance: false,
      isCJK: lang === 'chinese' || lang === 'bilingual' ? true : undefined,
    });
  let fit = measure(requested);
  if (!fit.fits && requested > floor) fit = measure(floor);
  if (!fit.fits) {
    throw layoutFit(
      `${options.label || role} cannot fit in ${box.w.toFixed(2)}x${box.h.toFixed(2)}in ` +
        `at ${options.min || 'role'}pt`,
    );
  }
  return {
    kind: 'text',
    text: String(text),
    box,
    role,
    fit,
    options,
  };
}

function paint(ctx, planned) {
  const lang = ctx.lang || 'chinese';
  for (const op of planned) {
    if (op.kind !== 'text') continue;
    H.addFittedText(ctx.slide, op.text, op.box, ctx.tokens, lang, op.role, {
      ...op.options,
      fontSize: op.fit.fontSize,
      margin: op.options.margin ?? 0,
      balance: false,
      label: op.options.label,
    });
    register(ctx, {
      type: 'text',
      role: op.role,
      text: op.text,
      x: op.box.x,
      y: op.box.y,
      w: op.box.w,
      h: op.box.h,
      fontSize: op.fit.fontSize,
    });
  }
}

function paintKeyLine(ctx, frame) {
  if (!frame.key || !frame.keyBand) return;
  const lang = ctx.lang || 'chinese';
  const band = frame.keyBand;
  const ruleY = band.y - 0.04;
  try {
    H.addDivider(ctx.slide, band.x, ruleY, band.w, ctx.tokens, 'hairline');
    register(ctx, { type: 'line', x1: band.x, y1: ruleY, x2: band.x + band.w, y2: ruleY });
    const textBox = { x: band.x, y: band.y + 0.06, w: band.w, h: band.h - 0.12 };
    const fit = H.fitText(frame.key, textBox, { min: 14, max: 22, margin: 0, role: 'body' });
    if (!fit.fits) return;
    H.addFittedText(ctx.slide, frame.key, textBox, ctx.tokens, lang, 'body', {
      bold: true,
      margin: 0,
      fontSize: fit.fontSize,
      label: 'key_line',
    });
    register(ctx, {
      type: 'text',
      role: 'subtitle',
      text: frame.key,
      ...textBox,
      fontSize: fit.fontSize,
    });
  } catch (error) {
    if (!(error instanceof RangeError)) throw error;
  }
}

function visualLanguage(ctx) {
  const language = ctx.tokens && ctx.tokens.visual_language;
  return language && typeof language === 'object' ? language : {};
}

function addRuleLine(ctx, x1, y1, x2, y2, options = {}) {
  const color = options.color || H.color(ctx.tokens, 'primary_accent');
  const width = Number(options.width) || 1.25;
  ctx.slide.addShape('line', {
    x: Math.min(x1, x2),
    y: Math.min(y1, y2),
    w: Math.abs(x2 - x1),
    h: Math.abs(y2 - y1),
    line: { color, width },
  });
  register(ctx, {
    type: 'line',
    x1,
    y1,
    x2,
    y2,
    ...(options.role ? { role: options.role, decorative: true, allowTextCrossing: true } : {}),
  });
}

const STYLE_RULES = ['bracket', 'left-rail', 'underline-left', 'top-band', 'slash'];

/**
 * 样式声明的 rule 标记（0.28.4）。
 *
 * 此前 visual_language.rule 没有任何渲染器读它——12 套风格因此共用同一个骨架，
 * 改这个字段不产生任何效果。画在每个内容页的左侧留白里：不进入正文盒子，
 * 登记为 style_rule + decorative，重叠判定自动豁免，D1 也按角色放行。
 */
function renderStyleRule(ctx, area) {
  const rule = String(visualLanguage(ctx).rule || '')
    .trim()
    .toLowerCase();
  if (!rule || rule === 'none' || !STYLE_RULES.includes(rule)) return null;
  const color = H.color(ctx.tokens, 'primary_accent');
  const gx = Math.max(0.16, area.x - 0.22);
  const top = Math.max(0.34, area.y - 0.3);
  const line = (x1, y1, x2, y2, width) =>
    addRuleLine(ctx, x1, y1, x2, y2, { color, width, role: 'style_rule' });
  if (rule === 'left-rail') {
    const h = Math.min(Math.max(1.2, area.h * 0.66), 2.2);
    line(gx, area.y + 0.1, gx, area.y + 0.1 + h, 2.5);
  } else if (rule === 'underline-left') {
    line(gx, top, gx + 1.25, top, 2.5);
  } else if (rule === 'bracket') {
    line(gx, top, gx + 0.62, top, 2);
    line(gx, top, gx, top + 0.5, 2);
  } else if (rule === 'slash') {
    line(gx, area.y + 0.36, gx + 0.36, Math.max(0.3, area.y - 0.3), 3);
  } else if (rule === 'top-band') {
    const band = { x: gx, y: Math.max(0.28, top - 0.06), w: 0.44, h: 0.13 };
    ctx.slide.addShape('rect', {
      ...band,
      fill: { color },
      line: { color, transparency: 100 },
    });
    register(ctx, {
      type: 'shape',
      role: 'style_rule',
      decorative: true,
      allowTextCrossing: true,
      ...band,
    });
  }
  return rule;
}

/** 计划文本的实际高度（估算器的行数 × 行距），用于把装饰面板收到文案大小。 */
function plannedTextHeight(op) {
  const fit = (op && op.fit) || {};
  const lines = Math.max(1, Number(fit.lines) || 1);
  const size = Math.max(8, Number(fit.fontSize) || 24);
  return lines * (size / 72) * 1.24;
}

/**
 * 焦点带里的紧致面板盒。
 *
 * 0.28.4：outlined 面板此前按整条焦点带（内容高度的 70–84%）画，短文案因此
 * 在框内留下半幅空白——看起来像没写完的占位框。现在按文案的实际行数/行长收边
 * 并在带内居中；soft-fill / edge-band 保持整带（那是"场"，不是"框"）。
 */
function tightFocalBox(focal, op) {
  const padX = 0.28;
  const padY = 0.24;
  const text = String((op && op.text) || '');
  const chars = [...text].length;
  const lines = Math.max(1, Number(((op && op.fit) || {}).lines) || 1);
  const size = Math.max(8, Number(((op && op.fit) || {}).fontSize) || 24);
  const perLine = Math.max(1, Math.ceil(chars / lines));
  const w = Math.max(1.6, Math.min(focal.w, perLine * (size / 72) * 1.02 + padX * 2));
  const h = Math.max(0.6, Math.min(focal.h, plannedTextHeight(op) + padY * 2));
  return { x: focal.x, y: focal.y + (focal.h - h) / 2, w, h };
}

/** 主区域的面板。flush 不加线。装饰层不参与文字重叠判定。 */
function paintFocalSurface(ctx, focal, op) {
  if (!focal) return;
  const panel = String(visualLanguage(ctx).panel || 'flush');
  if (panel === 'flush' || panel === 'none') return;
  const radius = Math.max(0, Math.min(0.2, Number(visualLanguage(ctx).radius) || 0));
  const outlined = panel === 'outlined';
  const box = outlined && op ? tightFocalBox(focal, op) : focal;
  ctx.slide.addShape(radius > 0.02 ? 'roundRect' : 'rect', {
    x: box.x,
    y: box.y,
    w: box.w,
    h: box.h,
    fill: { color: H.color(ctx.tokens, outlined ? 'canvas' : 'surface') },
    line: outlined
      ? { color: H.color(ctx.tokens, 'secondary_accent'), width: 1.25 }
      : { color: H.color(ctx.tokens, 'surface'), transparency: 100 },
    rectRadius: radius,
  });
  register(ctx, { type: 'shape', role: 'surface', decorative: true, ...box });
}

function drawEmphasisMarker(ctx, box, marker) {
  const color = H.color(ctx.tokens, 'primary_accent');
  const mark = { x: box.x, y: box.y + 0.08, w: 0.18, h: 0.18 };
  if (marker === 'dot' || marker === 'leaf') {
    ctx.slide.addShape('ellipse', {
      ...mark,
      fill: { color },
      line: { color, transparency: 100 },
    });
  } else if (marker === 'chevron') {
    ctx.slide.addShape('chevron', {
      x: mark.x,
      y: mark.y,
      w: 0.22,
      h: 0.16,
      fill: { color },
      line: { color, transparency: 100 },
    });
  } else if (marker === 'dash') {
    ctx.slide.addShape('rect', {
      x: mark.x,
      y: mark.y + 0.06,
      w: 0.28,
      h: 0.12,
      fill: { color },
      line: { color, transparency: 100 },
    });
  } else if (marker === 'slash') {
    addRuleLine(ctx, mark.x, mark.y + 0.16, mark.x + 0.22, mark.y + 0.16);
    addRuleLine(ctx, mark.x, mark.y, mark.x, mark.y + 0.16);
    return;
  } else {
    ctx.slide.addShape('rect', {
      ...mark,
      fill: { color },
      line: { color, transparency: 100 },
    });
  }
  register(ctx, { type: 'shape', role: 'label', decorative: true, ...mark });
}

function kicker(ctx, canvas, title, claim) {
  if (!title || !claim || title === claim) return { box: null, planned: [] };
  const box = { x: canvas.x, y: canvas.y, w: Math.min(canvas.w * 0.7, 7.2), h: 0.38 };
  return {
    box,
    planned: [
      planText(ctx, title, box, 'label', {
        align: 'left',
        colorRole: 'secondary_text',
        label: 'kicker',
        margin: 0,
        min: 14,
        max: 18,
      }),
    ],
    nextY: box.y + box.h + 0.16,
  };
}

function renderThesis(ctx, request, canvas) {
  const slots = request.slots || {};
  const undrawn = undrawnPayload(slots.visual);
  if (undrawn) {
    throw layoutFit(
      `thesis draws text only; the declared ${undrawn} payload needs proof, figure, ` +
        `or a layout that carries a visual zone`,
    );
  }
  const claim = String(slots.claim || '').trim();
  const title = String(slots.title || '').trim();
  const primary = claim || title;
  if (!primary) throw layoutFit('thesis needs a claim or a title');
  const kick = kicker(ctx, canvas, title, claim);
  const top = kick.nextY || canvas.y;
  const supportLine = linesOf(slots.body)[0] || '';
  const bottom = canvas.y + canvas.h;
  const avail = bottom - top;
  const supportH = supportLine ? 0.46 : 0;
  const gapAfter = supportLine ? 0.14 : 0;
  const maxPrimary = avail - supportH - gapAfter;
  const minPrimaryH = Math.max(1.35, canvas.h * 0.46);
  if (maxPrimary < minPrimaryH) {
    throw layoutFit('thesis primary region is below 40% of the content area');
  }
  const word = [...primary].length <= 6 && !/\s/.test(primary);
  const primaryH = word ? maxPrimary : Math.min(maxPrimary, Math.max(minPrimaryH, canvas.h * 0.58));
  const stackH = primaryH + supportH + gapAfter;
  const startY = top + Math.max(0, (avail - stackH) / 2);
  const primaryBox = { x: canvas.x, y: startY, w: canvas.w, h: primaryH };
  const share = (primaryBox.w * primaryBox.h) / (canvas.w * canvas.h);
  if (share < 0.4) {
    throw layoutFit('thesis primary region is below 40% of the content area');
  }
  const sizes = H.fontSizeScale(ctx.tokens, ctx.lang || 'chinese');
  const shortClaim = [...primary].length <= 8;
  const minPrimary = shortClaim
    ? Math.max(52, Math.round(sizes.body * 2.4))
    : Math.max(44, Math.round(sizes.body * 2.2));
  const planned = [...kick.planned];
  const primaryOp = planText(ctx, primary, primaryBox, 'stat', {
    align: 'left',
    min: minPrimary,
    max: 60,
    margin: 0,
    label: 'thesis',
  });
  planned.push(primaryOp);
  if (supportLine) {
    planned.push(
      planText(
        ctx,
        supportLine,
        {
          x: canvas.x,
          y: primaryBox.y + primaryBox.h + 0.12,
          w: canvas.w * 0.72,
          h: supportH,
        },
        'body',
        {
          align: 'left',
          colorRole: 'secondary_text',
          margin: 0,
          label: 'thesis support',
        },
      ),
    );
  }
  paintFocalSurface(ctx, primaryBox, primaryOp);
  paint(ctx, planned);
  return { focal: primaryBox };
}

function primaryShare(params, fallback) {
  const raw = Number(params && params.primaryShare);
  if (!Number.isFinite(raw)) return fallback;
  return Math.min(0.74, Math.max(0.52, raw));
}

function emphasisIndex(params, count) {
  const index = Number(params && params.emphasis);
  if (!Number.isInteger(index) || index < 0 || index >= count) return 0;
  return index;
}

// visual.type 的别名 → pptx-visuals 的组件名。权威词汇表在那边（KNOWN_VISUAL_TYPES
// = COMPONENTS 的全部键 + image/illustration/screenshot）；这里补齐其余组件名，
// 否则 KPI/矩阵/对比这类载荷只有版式路径画得出来，proof/figure 一律拒绝。
const VISUAL_TYPE_ALIASES = {
  dashboard: 'dashboard',
  chart: 'dashboard',
  data: 'dashboard',
  kpi: 'dashboard',
  stat: 'dashboard',
  table: 'table',
  timeline: 'timeline',
  process: 'process-path',
  flow: 'process-path',
  'process-path': 'process-path',
  comparison: 'comparison',
  matrix: 'matrix',
  architecture: 'architecture',
  quote: 'quote',
  summary: 'summary',
  reference: 'reference',
  hero: 'hero',
  image: 'visual-dominant',
  illustration: 'visual-dominant',
  screenshot: 'visual-dominant',
  'visual-dominant': 'visual-dominant',
};

function visualPayloadKeys(flat) {
  if (linesOf(flat.items).length || linesOf(flat.values).length) return true;
  return [flat.series, flat.rows, flat.stages, flat.steps, flat.nodes].some(
    (value) => Array.isArray(value) && value.length > 0,
  );
}

function visualComponent(visual) {
  if (!visual || typeof visual !== 'object') return null;
  if (typeof visual.component === 'string' && visual.component) return visual.component;
  const type = String(visual.type || '').toLowerCase();
  const details =
    visual.details && typeof visual.details === 'object' && !Array.isArray(visual.details)
      ? visual.details
      : {};
  const flat = { ...details, ...visual };
  if (type === 'chart' || (Array.isArray(flat.series) && flat.series.length)) return 'dashboard';
  if (type === 'table' || (Array.isArray(flat.rows) && flat.rows.length)) return 'table';
  if (type === 'timeline' || (Array.isArray(flat.stages) && flat.stages.length)) return 'timeline';
  if (type === 'process' || type === 'flow' || (Array.isArray(flat.steps) && flat.steps.length)) {
    return 'process-path';
  }
  if (flat.asset || type === 'image' || type === 'illustration' || type === 'screenshot') {
    return 'visual-dominant';
  }
  const alias = VISUAL_TYPE_ALIASES[type];
  // 别名只在载荷真带内容时才成立：空的 dashboard 会画成一排空壳。
  return alias && visualPayloadKeys(flat) ? alias : null;
}

/**
 * 声明的载荷这条动作画不出来时的载荷名（画得出来则 null）。
 *
 * 0.28.4：thesis / weighted / metric / sequence 画的是文字构图，此前会静默丢掉
 * 视觉载荷——绘制成功、内容却没上屏，只有 builder 事后自检才可能发现。现在直接
 * 抛 layoutFit，让候选链换一个画得出来的动作（proof / figure 或版式路径）。
 */
function undrawnPayload(visual, allowedKeys = []) {
  if (!visual || typeof visual !== 'object' || !Object.keys(visual).length) return null;
  const flat = flatVisual(visual);
  for (const key of allowedKeys) {
    if (Array.isArray(flat[key]) ? flat[key].length : flat[key] !== undefined) return null;
  }
  const component = visualComponent(visual);
  if (component) return component;
  if (linesOf(flat.items).length) return 'items';
  if (linesOf(flat.values).length) return 'values';
  return null;
}

function flatVisual(visual) {
  const details =
    visual.details && typeof visual.details === 'object' && !Array.isArray(visual.details)
      ? visual.details
      : {};
  return { ...details, ...visual };
}

function renderWeighted(ctx, request, canvas) {
  const slots = request.slots || {};
  const undrawn = undrawnPayload(slots.visual);
  if (undrawn) {
    throw layoutFit(
      `weighted draws text only; the declared ${undrawn} payload needs proof, figure, ` +
        `or a layout that carries a visual zone`,
    );
  }
  const title = String(slots.title || '').trim();
  const claim = String(slots.claim || title).trim();
  const supports = linesOf(slots.body);
  if (!claim) throw layoutFit('weighted needs a claim');
  if (supports.length < 1) throw layoutFit('weighted needs at least one support');
  const kick = kicker(ctx, canvas, title, claim);
  const top = kick.nextY || canvas.y;
  const band = { x: canvas.x, y: top, w: canvas.w, h: canvas.y + canvas.h - top };
  const gap = H.spacing(ctx.tokens, 4);
  const primaryW = band.w * primaryShare(request.params, 0.6);
  const primary = { x: band.x, y: band.y, w: primaryW, h: band.h };
  const rail = {
    x: band.x + primaryW + gap,
    y: band.y,
    w: band.w - primaryW - gap,
    h: band.h,
  };
  const heights = supports.map((_, index) => Math.max(0.85, 2.1 - index * 0.4));
  const heightTotal = heights.reduce((sum, value) => sum + value, 0);
  const railGap = Math.min(0.12, rail.h / (supports.length * 12));
  const usable = rail.h - railGap * (supports.length - 1);
  const claimOp = planText(
    ctx,
    claim,
    { x: primary.x, y: primary.y, w: primary.w, h: primary.h * 0.72 },
    'stat',
    {
      align: 'left',
      min: 36,
      max: 54,
      margin: 0,
      label: 'weighted claim',
    },
  );
  const planned = [...kick.planned, claimOp];
  let supportY = rail.y;
  supports.forEach((line, index) => {
    const rowH = (usable * heights[index]) / heightTotal;
    planned.push(
      planText(
        ctx,
        line,
        { x: rail.x, y: supportY, w: rail.w, h: rowH },
        index === 0 ? 'subtitle' : 'body',
        {
          align: 'left',
          margin: 0,
          colorRole: index === 0 ? 'primary_text' : 'secondary_text',
          label: `support ${index + 1}`,
        },
      ),
    );
    supportY += rowH + railGap;
  });
  paintFocalSurface(ctx, primary, claimOp);
  paint(ctx, planned);
  return { focal: primary };
}

function renderMetric(ctx, request, canvas) {
  const slots = request.slots || {};
  // metric 是一页一个大数字：只有 visual.value（或 claim）是它画得出来的载荷。
  const undrawn = undrawnPayload(slots.visual, ['value']);
  if (undrawn) {
    throw layoutFit(
      `metric draws one figure only; the declared ${undrawn} payload needs proof, figure, ` +
        `or a layout that carries a visual zone`,
    );
  }
  const visual = slots.visual && typeof slots.visual === 'object' ? slots.visual : {};
  const figure = String(visual.value || slots.claim || '').trim();
  if (!figure) throw layoutFit('metric needs a number in slots.claim or slots.visual.value');
  const title = String(slots.title || '').trim();
  const note = linesOf(slots.body).join('\n') || String(visual.label || '').trim();
  const kick = kicker(ctx, canvas, title, figure);
  const top = kick.nextY || canvas.y;
  const bandH = canvas.y + canvas.h - top;
  const statH = note ? bandH * 0.7 : bandH * 0.84;
  const statBox = { x: canvas.x, y: top, w: canvas.w, h: statH };
  const statOp = planText(ctx, figure, statBox, 'stat', {
    align: 'left',
    min: 48,
    max: 60,
    margin: 0,
    label: 'metric',
  });
  const planned = [...kick.planned, statOp];
  if (note) {
    const noteBox = {
      x: canvas.x,
      y: statBox.y + statBox.h + 0.08,
      w: canvas.w * 0.72,
      h: Math.max(0.4, bandH - statH - 0.1),
    };
    planned.push(
      planText(ctx, note, noteBox, 'body', {
        align: 'left',
        colorRole: 'secondary_text',
        margin: 0,
        label: 'metric note',
      }),
    );
  }
  paintFocalSurface(ctx, statBox, statOp);
  paint(ctx, planned);
  return { focal: statBox };
}

function renderProof(ctx, request, canvas) {
  const slots = request.slots || {};
  const claim = String(slots.claim || slots.title || '').trim();
  const visual = slots.visual && typeof slots.visual === 'object' ? slots.visual : null;
  if (!claim || !visual) throw layoutFit('proof needs a claim and a visual payload');
  const title = String(slots.title || '').trim();
  const kick = kicker(ctx, canvas, title, claim);
  const top = kick.nextY || canvas.y;
  const band = { x: canvas.x, y: top, w: canvas.w, h: canvas.y + canvas.h - top };
  const claimH = Math.min(0.72, band.h * 0.22);
  const visualBox = {
    x: band.x,
    y: band.y + claimH + 0.12,
    w: band.w,
    h: band.h - claimH - 0.12,
  };
  if (visualBox.w * visualBox.h < 2.5 || visualBox.h < 1.2) {
    throw layoutFit('proof evidence region is too small for a real chart or figure');
  }
  const claimBox = { x: band.x, y: band.y, w: band.w * 0.86, h: claimH };
  const planned = [
    ...kick.planned,
    planText(ctx, claim, claimBox, 'subtitle', { align: 'left', margin: 0, label: 'proof claim' }),
  ];
  const lang = ctx.lang || 'chinese';
  const family = visualComponent(visual);
  if (!family)
    throw layoutFit('proof visual needs a chart, table, image, or other known component');
  V.renderVisual(ctx.slide, family, flatVisual(visual), visualBox, ctx.tokens, lang);
  register(ctx, {
    type: 'shape',
    role: 'visual',
    x: visualBox.x,
    y: visualBox.y,
    w: visualBox.w,
    h: visualBox.h,
  });
  paint(ctx, planned);
  return { focal: visualBox };
}

function renderSequence(ctx, request, canvas) {
  const slots = request.slots || {};
  // sequence 把 stages/steps 当自己的步骤用；其余载荷它画不出来。
  const undrawn = undrawnPayload(slots.visual, ['stages', 'steps']);
  if (undrawn) {
    throw layoutFit(
      `sequence draws steps only; the declared ${undrawn} payload needs proof, figure, ` +
        `or a layout that carries a visual zone`,
    );
  }
  const visual = slots.visual && typeof slots.visual === 'object' ? slots.visual : {};
  const stages = linesOf(visual.stages || visual.steps);
  const steps = stages.length ? stages : linesOf(slots.body);
  if (steps.length < 2 || steps.length > 5) throw layoutFit('sequence needs 2-5 steps');
  const title = String(slots.title || '').trim();
  const claim = String(slots.claim || '').trim();
  const kick = kicker(ctx, canvas, title, claim || steps[0]);
  const top = kick.nextY || canvas.y;
  let head = [];
  if (claim && title && title !== claim) {
    head = kick.planned;
  } else if (claim) {
    const claimBox = { x: canvas.x, y: top, w: canvas.w * 0.8, h: 0.7 };
    head = [
      planText(ctx, claim, claimBox, 'subtitle', {
        align: 'left',
        margin: 0,
        label: 'sequence claim',
      }),
    ];
  }
  const usedTop = head.length ? Math.max(...head.map((op) => op.box.y + op.box.h)) + 0.24 : top;
  const band = { x: canvas.x, y: usedTop, w: canvas.w, h: canvas.y + canvas.h - usedTop };
  if (band.h < 1.3) throw layoutFit('sequence has no room under the claim');
  const years = steps.every((step) => /\d{4}/.test(step));
  if (years && visual.stages) {
    paint(ctx, head);
    V.addTimeline(
      ctx.slide,
      { stages: steps.map((label) => ({ label })) },
      band,
      ctx.tokens,
      ctx.lang || 'chinese',
    );
    register(ctx, { type: 'shape', role: 'visual', ...band });
    return { focal: band };
  }
  const lead = emphasisIndex(request.params, steps.length);
  const marker = String(visualLanguage(ctx).emphasis_marker || 'number');
  const weights = steps.map((_, index) => (index === lead ? 2.2 : 1));
  const weightTotal = weights.reduce((sum, value) => sum + value, 0);
  let cursor = band.x;
  const cells = steps.map((_, index) => {
    const w = (band.w * weights[index]) / weightTotal;
    const cell = { x: cursor, y: band.y, w: Math.max(0.8, w - 0.1), h: band.h };
    cursor += w;
    return cell;
  });
  const spineY = band.y + 0.28;
  const planned = [...head];
  const sizes = H.fontSizeScale(ctx.tokens, ctx.lang || 'chinese');
  steps.forEach((step, index) => {
    const cell = cells[index];
    const node = index === lead ? 0.72 : 0.32;
    const numBox = { x: cell.x, y: band.y, w: cell.w, h: node };
    const labelBox = {
      x: cell.x,
      y: band.y + node + 0.1,
      w: cell.w,
      h: Math.max(0.7, band.h - node - 0.1),
    };
    if (!(index === lead && marker !== 'number')) {
      planned.push(
        planText(
          ctx,
          String(index + 1).padStart(2, '0'),
          numBox,
          index === lead ? 'stat' : 'label',
          {
            align: 'left',
            min: index === lead ? 28 : undefined,
            max: index === lead ? 40 : 16,
            margin: 0,
            label: `step ${index + 1} index`,
            colorRole: index === lead ? 'primary_accent' : 'secondary_text',
          },
        ),
      );
    }
    planned.push(
      planText(ctx, step, labelBox, index === lead ? 'subtitle' : 'body', {
        align: 'left',
        margin: 0,
        min: index === lead ? sizes.subtitle : sizes.body,
        label: `step ${index + 1}`,
      }),
    );
  });
  const slab = {
    x: cells[lead].x,
    y: band.y,
    w: cells[lead].w,
    h: Math.min(Math.max(1.15, band.h * 0.62), band.h),
  };
  ctx.slide.addShape('roundRect', {
    x: slab.x,
    y: slab.y,
    w: slab.w,
    h: slab.h,
    fill: { color: H.color(ctx.tokens, 'primary_accent'), transparency: 82 },
    line: { color: H.color(ctx.tokens, 'primary_accent'), transparency: 100 },
    rectRadius: 0.06,
  });
  register(ctx, { type: 'shape', role: 'surface', decorative: true, ...slab });
  paint(ctx, planned);
  if (marker !== 'number') drawEmphasisMarker(ctx, cells[lead], marker);
  const spineColor = H.color(ctx.tokens, 'secondary_accent');
  ctx.slide.addShape('line', {
    x: band.x,
    y: spineY,
    w: band.w * 0.92,
    h: 0,
    line: { color: spineColor, width: 1.5 },
  });
  register(ctx, {
    type: 'line',
    x1: band.x,
    y1: spineY,
    x2: band.x + band.w * 0.92,
    y2: spineY,
  });
  register(ctx, { type: 'shape', role: 'visual', decorative: true, ...cells[lead] });
  return { focal: cells[lead] };
}

function renderFigure(ctx, request, canvas) {
  const slots = request.slots || {};
  const visual = slots.visual && typeof slots.visual === 'object' ? slots.visual : null;
  if (!visual) throw layoutFit('figure needs slots.visual');
  const title = String(slots.title || '').trim();
  const claim = String(slots.claim || '').trim();
  const kick = kicker(ctx, canvas, title, claim);
  const top = kick.nextY || canvas.y;
  const band = { x: canvas.x, y: top, w: canvas.w, h: canvas.y + canvas.h - top };
  const gap = H.spacing(ctx.tokens, 4);
  const visualW = band.w * primaryShare(request.params, 0.74);
  const visualBox = { x: band.x, y: band.y, w: visualW, h: band.h };
  const share = (visualBox.w * visualBox.h) / (canvas.w * canvas.h);
  if (share < 0.55) throw layoutFit('figure visual is under 55% of the content area');
  const caption = [claim, ...linesOf(slots.body)].filter(Boolean).join('\n');
  const planned = [...kick.planned];
  if (caption && claim !== title) {
    const cap = {
      x: visualBox.x + visualBox.w + gap,
      y: band.y + band.h * 0.12,
      w: band.w - visualW - gap,
      h: band.h * 0.7,
    };
    planned.push(
      planText(ctx, caption, cap, 'body', {
        align: 'left',
        colorRole: 'secondary_text',
        margin: 0,
        label: 'figure caption',
      }),
    );
  }
  const family = visualComponent(visual);
  if (!family) throw layoutFit('figure visual needs an image or a native chart');
  const asset = flatVisual(visual).asset;
  if (asset) {
    ctx.slide.addImage({
      path: asset,
      ...V.coverImage(asset, visualBox),
      altText: String(flatVisual(visual).alt_text || claim || 'Presentation visual'),
    });
  } else
    V.renderVisual(
      ctx.slide,
      family,
      flatVisual(visual),
      visualBox,
      ctx.tokens,
      ctx.lang || 'chinese',
    );
  register(ctx, { type: 'shape', role: 'visual', ...visualBox });
  paint(ctx, planned);
  return { focal: visualBox };
}

const RENDERERS = {
  thesis: renderThesis,
  weighted: renderWeighted,
  metric: renderMetric,
  proof: renderProof,
  sequence: renderSequence,
  figure: renderFigure,
};

function renderMove(ctx, request = {}) {
  if (!ctx || !ctx.slide || !ctx.tokens)
    throw new Error('renderMove: ctx must carry slide and tokens');
  const move = String(request.move || '').trim();
  const render = RENDERERS[move];
  if (!render) throw new Error(`Unknown move: ${move}. Use one of ${MOVES.join(', ')}.`);
  const full = H.contentArea(ctx.tokens, ctx.pageKind || 'content');
  const slots = request.slots || {};
  const frame = contentFrame(full, slots);
  let drawn;
  try {
    drawn = render(ctx, request, frame.area);
    paintKeyLine(ctx, frame);
  } catch (error) {
    if (error instanceof RangeError) error.layoutFit = true;
    throw error;
  }
  if (ctx.layoutReport && Number.isInteger(ctx.slideNumber)) {
    ctx.layoutReport.push({
      slide: ctx.slideNumber,
      move,
      layout: move,
      family: 'composition',
      silhouette: move,
    });
  }
  return { move, layout: move, family: 'composition', silhouette: move, focal: drawn.focal };
}

module.exports = { MOVES, STYLE_RULES, renderMove, renderStyleRule, renderThesis, renderWeighted };
