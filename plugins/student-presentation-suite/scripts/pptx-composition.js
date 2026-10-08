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
  const primaryH = Math.min(maxPrimary, Math.max(minPrimaryH, canvas.h * 0.58));
  const stackH = primaryH + supportH + gapAfter;
  const startY = top + Math.max(0, (avail - stackH) / 2);
  const primaryBox = { x: canvas.x, y: startY, w: canvas.w * 0.9, h: primaryH };
  const share = (primaryBox.w * primaryBox.h) / (canvas.w * canvas.h);
  if (share < 0.4) {
    throw layoutFit('thesis primary region is below 40% of the content area');
  }
  const sizes = H.fontSizeScale(ctx.tokens, ctx.lang || 'chinese');
  const minPrimary = Math.max(44, Math.round(sizes.body * 2.2));
  const planned = [...kick.planned];
  planned.push(
    planText(ctx, primary, primaryBox, 'stat', {
      align: 'left',
      min: minPrimary,
      max: 60,
      margin: 0,
      label: 'thesis',
    }),
  );
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
  const planned = [
    ...kick.planned,
    planText(
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
    ),
  ];
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
  paint(ctx, planned);
  return { focal: primary };
}

function renderMetric(ctx, request, canvas) {
  const slots = request.slots || {};
  const visual = slots.visual && typeof slots.visual === 'object' ? slots.visual : {};
  const figure = String(visual.value || slots.claim || '').trim();
  if (!figure) throw layoutFit('metric needs a number in slots.claim or slots.visual.value');
  const title = String(slots.title || '').trim();
  const note = linesOf(slots.body).join('\n') || String(visual.label || '').trim();
  const kick = kicker(ctx, canvas, title, figure);
  const top = kick.nextY || canvas.y;
  const bandH = canvas.y + canvas.h - top;
  const gap = H.spacing(ctx.tokens, 4);
  const statW = note ? canvas.w * 0.62 : canvas.w * 0.84;
  const statBox = { x: canvas.x, y: top, w: statW, h: bandH * 0.78 };
  const planned = [
    ...kick.planned,
    planText(ctx, figure, statBox, 'stat', {
      align: 'left',
      min: 48,
      max: 60,
      margin: 0,
      label: 'metric',
    }),
  ];
  if (note) {
    const noteBox = {
      x: canvas.x + statW + gap,
      y: top + bandH * 0.28,
      w: canvas.w - statW - gap,
      h: bandH * 0.46,
    };
    if (noteBox.w >= statBox.w)
      throw layoutFit('metric annotation is not narrower than the figure');
    planned.push(
      planText(ctx, note, noteBox, 'body', {
        align: 'left',
        colorRole: 'secondary_text',
        margin: 0,
        label: 'metric note',
      }),
    );
  }
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
  const gap = H.spacing(ctx.tokens, 4);
  const visualW = band.w * primaryShare(request.params, 0.62);
  const textW = band.w - visualW - gap;
  const visualBox = { x: band.x + textW + gap, y: band.y, w: visualW, h: band.h };
  if (visualBox.w * visualBox.h < 2.5 || visualBox.h < 1.2) {
    throw layoutFit('proof evidence region is too small for a real chart or figure');
  }
  const claimBox = { x: band.x, y: band.y, w: textW, h: Math.min(band.h * 0.55, 2.1) };
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
  const weights = steps.map((_, index) => (index === lead ? 3.4 : 1));
  const gap = H.spacing(ctx.tokens, 3);
  const cells = H.weightedColumns(band, steps.length, weights, gap);
  const planned = [...head];
  const sizes = H.fontSizeScale(ctx.tokens, ctx.lang || 'chinese');
  steps.forEach((step, index) => {
    const cell = cells[index];
    const numBox = { x: cell.x, y: cell.y, w: cell.w, h: Math.min(0.72, cell.h * 0.34) };
    const labelBox = {
      x: cell.x,
      y: numBox.y + numBox.h + 0.08,
      w: cell.w,
      h: cell.h - numBox.h - 0.08,
    };
    planned.push(
      planText(ctx, String(index + 1).padStart(2, '0'), numBox, index === lead ? 'stat' : 'label', {
        align: 'left',
        min: index === lead ? 36 : undefined,
        max: index === lead ? 48 : 20,
        margin: 0,
        label: `step ${index + 1} index`,
        colorRole: index === lead ? 'primary_accent' : 'secondary_text',
      }),
    );
    planned.push(
      planText(ctx, step, labelBox, index === lead ? 'subtitle' : 'body', {
        align: 'left',
        margin: 0,
        min: index === lead ? sizes.subtitle : sizes.body,
        label: `step ${index + 1}`,
      }),
    );
  });
  paint(ctx, planned);
  register(ctx, { type: 'shape', role: 'visual', decorative: true, ...cells[lead] });
  const p = H.color(ctx.tokens, 'secondary_accent');
  for (let index = 0; index < cells.length - 1; index += 1) {
    const left = cells[index];
    const y = left.y + 0.36;
    ctx.slide.addShape('line', {
      x: left.x + left.w * 0.72,
      y,
      w: gap + cells[index + 1].w * 0.15,
      h: 0,
      line: { color: p, width: 1.25 },
    });
  }
  return { focal: cells[0] };
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
  const visualW = band.w * primaryShare(request.params, 0.64);
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
  const full = H.safeArea(H.SLIDE_W_IN, H.SLIDE_H_IN, ctx.tokens, { reserveTitle: false });
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

module.exports = { MOVES, renderMove, renderThesis, renderWeighted };
