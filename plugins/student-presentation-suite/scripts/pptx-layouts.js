'use strict';

const registry = require('../skills/sp-deck/references/layout-library.json');

const FAMILY_COMPOSITIONS = Object.freeze({
  cover: {
    composition: 'hero',
    shape_slots: ['accent'],
    text_policy: 'display',
    asset_slots: ['visual'],
  },
  section: {
    composition: 'divider',
    shape_slots: ['anchor'],
    text_policy: 'display',
    asset_slots: ['visual'],
  },
  'claim-text': {
    composition: 'editorial',
    shape_slots: ['focus'],
    text_policy: 'reading',
    asset_slots: ['visual'],
  },
  'visual-image': {
    composition: 'visual-led',
    shape_slots: ['frame'],
    text_policy: 'captioned',
    asset_slots: ['visual'],
  },
  data: {
    composition: 'analytical',
    shape_slots: ['takeaway'],
    text_policy: 'analytical',
    asset_slots: ['visual'],
  },
  comparison: {
    composition: 'paired',
    shape_slots: ['option'],
    text_policy: 'balanced',
    asset_slots: ['body', 'visual'],
  },
  'process-system': {
    composition: 'connected',
    shape_slots: ['node'],
    text_policy: 'node-centered',
    asset_slots: ['visual'],
  },
  'quote-reference-closing': {
    composition: 'reflective',
    shape_slots: ['focus'],
    text_policy: 'contextual',
    asset_slots: ['visual'],
  },
});

const LAYOUT_VARIANTS = Object.freeze({
  'cover-split': ['parallelogram', 'arch'],
  'cover-full-bleed': ['arch', 'ellipse'],
  'cover-editorial': ['parallelogram', 'rect'],
  'cover-minimal': ['ellipse', 'none'],
  'section-number': ['ellipse', 'bracket'],
  'section-statement': ['pill', 'arch'],
  'section-image-band': ['arch', 'parallelogram'],
  'claim-focus': ['ellipse', 'none'],
  'claim-evidence': ['bracket', 'rect'],
  'text-two-column': ['parallelogram', 'rect'],
  'text-sidebar': ['pill', 'rect'],
  'evidence-stack': ['chevron', 'rect'],
  'definition-example': ['hexagon', 'pill'],
  'visual-left': ['arch', 'parallelogram'],
  'visual-right': ['parallelogram', 'arch'],
  'visual-full': ['arch', 'ellipse'],
  'visual-annotated': ['hexagon', 'pill'],
  'visual-collage': ['parallelogram', 'ellipse'],
  'data-chart-takeaway': ['bracket', 'pill'],
  'data-chart-sidebar': ['rect', 'hexagon'],
  'data-kpi-row': ['ellipse', 'pill'],
  'data-table-highlight': ['chevron', 'rect'],
  'data-small-multiples': ['hexagon', 'rect'],
  'compare-balanced': ['pill', 'parallelogram'],
  'compare-before-after': ['chevron', 'parallelogram'],
  'compare-criteria': ['hexagon', 'rect'],
  'compare-quadrant': ['ellipse', 'bracket'],
  'process-horizontal': ['chevron', 'pill'],
  'process-vertical': ['hexagon', 'pill'],
  'timeline-roadmap': ['ellipse', 'arch'],
  'architecture-layered': ['parallelogram', 'hexagon'],
  'quote-focus': ['ellipse', 'none'],
  'quote-analysis': ['arch', 'rect'],
  'references-clean': ['bracket', 'rect'],
  'closing-takeaway': ['pill', 'ellipse'],
  'closing-question': ['arch', 'ellipse'],
});

function executableLayout(layout) {
  const family = FAMILY_COMPOSITIONS[layout.family] || FAMILY_COMPOSITIONS['claim-text'];
  const shapes = LAYOUT_VARIANTS[layout.id] || ['rect', 'ellipse'];
  return {
    ...layout,
    composition: `${family.composition}:${layout.silhouette}`,
    // 注意：当前 8 个 family 的 shape_slots 均只有 1 个槽位，LAYOUT_VARIANTS 的
    // 第二个形状（备用风格）不会被消费；未来引入双槽 family 时此映射自动生效。
    shape_slots: family.shape_slots.map((role, index) => ({
      role,
      shape: shapes[index % shapes.length],
    })),
    text_policy: family.text_policy,
    asset_slots: family.asset_slots.filter((name) => layout.zones && layout.zones[name]),
    corner_decoration: 'optional-toolbox-reference',
    variant_fallbacks: [layout.fallback].filter(Boolean),
  };
}

const layoutsById = new Map(registry.layouts.map((layout) => [layout.id, layout]));

function getLayout(id) {
  const layout = layoutsById.get(id);
  if (!layout) throw new Error(`Unknown layout: ${id}`);
  return JSON.parse(JSON.stringify(executableLayout(layout)));
}

function stableHash(value) {
  let hash = 2166136261;
  for (const char of String(value)) {
    hash ^= char.charCodeAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function includesOrWildcard(values, value) {
  return !value || !Array.isArray(values) || values.length === 0 || values.includes(value);
}

const KIND_ALIASES = Object.freeze({
  'section-divider': 'section',
  quotation: 'quote',
});

const VISUAL_ALIASES = Object.freeze({
  hero: 'image',
  'visual-dominant': 'image',
  'process-path': 'process',
  dashboard: 'data',
  reference: 'text',
  summary: 'none',
});

const VISUAL_KIND_HINTS = Object.freeze({
  architecture: 'architecture',
  comparison: 'comparison',
  dashboard: 'data',
  matrix: 'analysis',
  'process-path': 'process',
  quote: 'quote',
  reference: 'references',
  summary: 'summary',
  timeline: 'timeline',
  'visual-dominant': 'image',
});

const VISUAL_FAMILY_HINTS = Object.freeze({
  architecture: 'process-system',
  comparison: 'comparison',
  dashboard: 'data',
  matrix: 'comparison',
  'process-path': 'process-system',
  quote: 'quote-reference-closing',
  reference: 'quote-reference-closing',
  summary: 'quote-reference-closing',
  timeline: 'process-system',
  'visual-dominant': 'visual-image',
});

function normalizedContext(context) {
  const rawKind = context.slideKind || context.kind;
  const rawVisual = context.visualFamily || context.layoutFamily;
  const kinds = new Set();
  for (const value of [rawKind, context.role, VISUAL_KIND_HINTS[rawVisual]]) {
    if (value) kinds.add(KIND_ALIASES[value] || value);
  }
  const visualFamily = VISUAL_ALIASES[rawVisual] || rawVisual;
  return { kinds: [...kinds], visualFamily };
}

function matchesAny(values, candidates) {
  return (
    !Array.isArray(values) ||
    values.length === 0 ||
    candidates.length === 0 ||
    candidates.some((candidate) => values.includes(candidate))
  );
}

function rangeContains(range, value) {
  return !Array.isArray(range) || value === null || (value >= range[0] && value <= range[1]);
}

function titleZoneCanFit(layout, context, titleChars) {
  if (titleChars === null || titleChars === 0) return true;
  const zone = layout.zones && layout.zones.title;
  if (!Array.isArray(zone)) return true;
  const title = typeof context.title === 'string' ? context.title : '';
  const cjk = /[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]/u.test(title);
  const charsPerFullLine = cjk ? 26 : 48;
  const charsPerLine = Math.max(1, Math.floor(charsPerFullLine * zone[2]));
  const estimatedLines = Math.ceil(titleChars / charsPerLine);
  const requiredNormalizedHeight = estimatedLines * (cjk ? 0.1 : 0.085);
  return requiredNormalizedHeight <= zone[3];
}

function isFeasible(layout, context) {
  const normalized = normalizedContext(context);
  if (!matchesAny(layout.eligible_kinds, normalized.kinds)) return false;
  if (!includesOrWildcard(layout.visual_families, normalized.visualFamily)) return false;

  const requirements = layout.requirements || {};
  if (requirements.asset === 'required' && !context.hasAsset) return false;
  if (requirements.data === 'required' && !context.hasData) return false;
  if (requirements.quote === 'required' && !context.hasQuote) return false;

  const itemCount = Number.isFinite(context.itemCount) ? context.itemCount : null;
  if (itemCount !== null && Array.isArray(requirements.items)) {
    if (itemCount < requirements.items[0] || itemCount > requirements.items[1]) return false;
  }
  const capacity = layout.capacity || {};
  const titleChars = Number.isFinite(context.titleChars)
    ? context.titleChars
    : typeof context.title === 'string'
      ? [...context.title].length
      : null;
  if (!rangeContains(capacity.title_chars, titleChars)) return false;
  if (!titleZoneCanFit(layout, context, titleChars)) return false;
  if (!rangeContains(capacity.body_items, itemCount)) return false;

  const activeContraindications = new Set([
    ...(context.contraindications || []),
    ...(context.constraints || []),
  ]);
  if ((layout.contraindications || []).some((condition) => activeContraindications.has(condition)))
    return false;
  return true;
}

function historySilhouettes(history) {
  return (history || [])
    .map((entry) => {
      if (typeof entry === 'string' && layoutsById.has(entry))
        return layoutsById.get(entry).silhouette;
      return (
        entry && (entry.silhouette || (entry.layout && layoutsById.get(entry.layout)?.silhouette))
      );
    })
    .filter(Boolean);
}

function scoreLayout(layout, context, _tokens, history) {
  let score = 0;
  if (context.density && context.density === layout.density) score += 5;
  if ((context.layout || context.layoutId) === layout.id) score += 40;
  const rawVisual = context.visualFamily || context.layoutFamily;
  if (VISUAL_FAMILY_HINTS[rawVisual] === layout.family) score += 24;

  const silhouettes = historySilhouettes(history);
  const last = silhouettes.at(-1);
  const previous = silhouettes.at(-2);
  if (layout.silhouette === last) score -= 12;
  if (layout.silhouette === last && layout.silhouette === previous) score -= 1000;

  const seed = context.seed || `${context.slideId || 'slide'}:${context.title || ''}`;
  score += (stableHash(`${seed}:${layout.id}`) % 1000) / 10000;
  return score;
}

function suggestLayouts(context = {}, tokens = {}, history = [], count = 3) {
  const requestedCount = Math.max(1, Number(count) || 3);
  let candidates = registry.layouts.filter((layout) => isFeasible(layout, context));

  if (candidates.length === 0 && context.layout && layoutsById.has(context.layout)) {
    let requested = layoutsById.get(context.layout);
    const visited = new Set();
    while (requested && !visited.has(requested.id)) {
      visited.add(requested.id);
      if (isFeasible(requested, context)) {
        candidates = [requested];
        break;
      }
      requested = layoutsById.get(requested.fallback);
    }
  }
  if (candidates.length === 0) {
    const normalized = normalizedContext(context);
    const roots = registry.layouts.filter(
      (layout) =>
        matchesAny(layout.eligible_kinds, normalized.kinds) &&
        includesOrWildcard(layout.visual_families, normalized.visualFamily),
    );
    const fallbackCandidates = new Map();
    for (const root of roots) {
      let current = root;
      const visited = new Set();
      while (current && !visited.has(current.id)) {
        visited.add(current.id);
        if (isFeasible(current, context)) {
          fallbackCandidates.set(current.id, current);
          break;
        }
        current = layoutsById.get(current.fallback);
      }
    }
    candidates = [...fallbackCandidates.values()];
  }
  if (candidates.length === 0) {
    const relaxed = { ...context, visualFamily: undefined, layoutFamily: undefined };
    candidates = registry.layouts.filter((layout) => isFeasible(layout, relaxed));
  }
  if (candidates.length < requestedCount) {
    const relaxed = { ...context, visualFamily: undefined, layoutFamily: undefined };
    const existing = new Set(candidates.map((layout) => layout.id));
    for (const layout of registry.layouts) {
      if (!existing.has(layout.id) && isFeasible(layout, relaxed)) {
        candidates.push(layout);
        existing.add(layout.id);
      }
    }
  }

  return candidates
    .map((layout) => ({
      ...getLayout(layout.id),
      score: scoreLayout(layout, context, tokens, history),
      usage: 'inspiration',
      adaptable: true,
      editable_axes: ['proportions', 'position', 'zones', 'shapes', 'media-crop'],
    }))
    .sort((a, b) => b.score - a.score || a.id.localeCompare(b.id))
    .slice(0, requestedCount);
}

// Backwards-compatible name. Two modes live side by side since v0.18:
// - suggestion mode (suggestLayouts/selectLayouts): ranked inspiration for the
//   composition evidence step;
// - execution mode (renderArchetype): zones are compiled to pptxgenjs calls and
//   builders fill slots instead of hand-placing coordinates.
function selectLayouts(context = {}, tokens = {}, history = [], count = 3) {
  return suggestLayouts(context, tokens, history, count);
}

// ── Archetype execution engine (v0.18) ────────────────────────────────────
//
// resolveLayout 之上的建议模式保留给 composition 证据；renderArchetype 是执行端：
// 版式库的 normalized zones → 安全区英寸几何 → pptxgenjs 调用。builder 的自由度
// 收敛为：选 archetype（context 自动选或 request.layout.id 指定）、填槽
// （slots.title/claim/body/visual）、调参数（mirror/density）。自由坐标只存在于
// builder 完全手写页面的 custom 逃生舱（design grammar 允许，但必须过全部几何门）。

// scripts/ 目录的模块互相用裸名 require（生产由 run_with_pptxgenjs 注入
// NODE_PATH）。引擎要在没有 NODE_PATH 的环境（单测、独立调用）也可用：
// 安装一次受控回退——仅当裸名 pptx-* 解析失败时，重试本目录下的同名文件。
const _SIBLING_DIR = __dirname;
function _installSiblingResolver() {
  const Module = require('node:module');
  const nodePath = require('node:path');
  if (Module.__pptxSiblingResolver) return;
  Module.__pptxSiblingResolver = true;
  const original = Module._resolveFilename;
  Module._resolveFilename = function patched(request, ...rest) {
    try {
      return original.call(this, request, ...rest);
    } catch (error) {
      const resolvable =
        error && error.code === 'MODULE_NOT_FOUND' && /^pptx-[a-z-]+$/.test(String(request));
      if (!resolvable || !nodePath.join(_SIBLING_DIR, `${request}.js`)) throw error;
      return original.call(this, nodePath.join(_SIBLING_DIR, `${request}.js`), ...rest);
    }
  };
}

function _sibling(name) {
  _installSiblingResolver();
  return require(name);
}

// family → 视觉组件映射；visual.type/形状字段可进一步细化。
const FAMILY_COMPONENTS = Object.freeze({
  cover: { withVisual: 'visual-dominant' },
  section: { withVisual: 'visual-dominant' },
  'visual-image': { withVisual: 'visual-dominant' },
  data: { withVisual: 'dashboard', table: 'table' },
  comparison: { withVisual: 'comparison' },
  'process-system': {
    withVisual: 'process-path',
    timeline: 'timeline',
    architecture: 'architecture',
    matrix: 'matrix',
  },
  'quote-reference-closing': {
    withVisual: 'quote',
    reference: 'reference',
    summary: 'summary',
    quote: 'quote',
  },
  'claim-text': { withVisual: 'visual-dominant', comparison: 'comparison', dashboard: 'dashboard' },
});

function visualComponentFor(family, visual) {
  if (!visual || typeof visual !== 'object' || Object.keys(visual).length === 0) return null;
  if (typeof visual.component === 'string' && visual.component) return visual.component;
  const spec = FAMILY_COMPONENTS[family] || { withVisual: 'visual-dominant' };
  const type = String(visual.type || '').toLowerCase();
  if (type && spec[type] !== undefined) return spec[type];
  if (Array.isArray(visual.series) && visual.series.length) return 'dashboard';
  if (Array.isArray(visual.rows) && visual.rows.length) return 'table';
  if (Array.isArray(visual.stages) && visual.stages.length) return 'timeline';
  if (Array.isArray(visual.nodes) && visual.nodes.length) return 'architecture';
  if (type === 'quote') return 'quote';
  if (visual.asset || type === 'image' || type === 'illustration' || type === 'screenshot') {
    return 'visual-dominant';
  }
  return spec.withVisual || null;
}

function isDisplayFamily(family) {
  return family === 'cover' || family === 'section' || family === 'quote-reference-closing';
}

/**
 * slots.visual 的有效载荷：spec visual 把数据放在 details 子对象里，
 * 组件库要的是扁平载荷——details 展开合并（顶层键优先）。
 */
function resolveVisualPayload(visual) {
  if (!visual || typeof visual !== 'object') return {};
  const details = visual.details && typeof visual.details === 'object' ? visual.details : {};
  const top = Object.fromEntries(Object.entries(visual).filter(([key]) => key !== 'details'));
  return { ...details, ...top };
}

/**
 * 按 context 自动选一个可行 archetype（suggestLayouts 的单结果便捷封装）。
 */
function pickLayout(context = {}, tokens = {}, history = []) {
  const picked = suggestLayouts(context, tokens, history, 1);
  return picked[0] || null;
}

function _fitError(message) {
  const error = new RangeError(message);
  error.layoutFit = true; // renderArchetype 据此沿 fallback 链换版式重试
  return error;
}

/**
 * 一次性探针 slide：渲染路径的任何方法调用都吞掉、任何属性赋值都放行，
 * 用于 fallback 链的干跑（失败的尝试不落真迹）。
 */
function _probeSlide() {
  return new Proxy(
    {},
    {
      get(target, prop) {
        if (typeof prop === 'symbol') return undefined;
        if (!(prop in target)) target[prop] = () => ({});
        return target[prop];
      },
      set(target, prop, value) {
        target[prop] = value;
        return true;
      },
    },
  );
}

/**
 * 正文绘制：addBody 的容量失败（裸 RangeError）必须包装成 layoutFit 参与
 * fallback 链，否则直接炸掉 deck——与 visual 组件的 RangeError 同一待遇。
 * 2026-09-28 live：claim-focus 单栏剩余区装不下两条正文，未包装的失败
 * 终止了整条链。
 */
function _addBodyWithFit(ctx, layoutId, items, box, tokens, lang, options) {
  const H = _sibling('pptx-helpers');
  try {
    H.addBody(ctx.slide, items, box, tokens, lang, options);
  } catch (error) {
    if (error instanceof RangeError) {
      throw _fitError(
        `slide ${Number.isInteger(ctx.slideNumber) ? ctx.slideNumber : 0}: ` +
          `body copy does not fit archetype "${layoutId}" — ${error.message}`,
      );
    }
    throw error;
  }
}

/**
 * 执行一个版式 archetype：背景之外的整页几何（标题/claim/正文/视觉组件）。
 *
 * @param {object} ctx - deck.js 传入的 { slide, tokens, registry, lang?, slideNumber?, layoutReport? }
 * @param {object} request
 * @param {object} [request.context]   选版式用的 slide 上下文（slideKind/role/visualFamily/...）
 * @param {object} [request.layout]    { id } 直接指定 archetype（跳过自动选择）
 * @param {object} [request.slots]     { title, claim, body, visual } 内容槽
 * @param {object} [request.params]    { mirror } 版式参数
 * @returns {{ layout: string, family: string, silhouette: string, zones: object }}
 */
function renderArchetype(ctx, request = {}) {
  const H = _sibling('pptx-helpers');
  const { tokens } = ctx;
  if (!ctx.slide || !tokens) throw new Error('renderArchetype: ctx must carry slide and tokens');
  const area = H.safeArea(H.SLIDE_W_IN, H.SLIDE_H_IN, tokens, { reserveTitle: false });

  let firstId;
  if (request.layout && request.layout.id) {
    firstId = String(request.layout.id);
    if (!layoutsById.has(firstId)) throw new Error(`Unknown layout: ${firstId}`);
  } else {
    let picked = pickLayout(request.context || {}, tokens, request.history || []);
    if (!picked) {
      // 容量约束（如超短标题触发 title_chars 下限）不该让整页失败：
      // 放开标题容量约束再选一次（title 键必须整个删除——空字符串会被
      // 当成 0 字标题，titleChars 缺省时又会从 title 重新推导）。
      const { title: _ignoredTitle, ...relaxed } = request.context || {};
      void _ignoredTitle;
      picked = pickLayout({ ...relaxed, titleChars: null }, tokens, request.history || []);
    }
    if (!picked) {
      throw new Error(
        'renderArchetype: no feasible layout for the given context — widen the context or pass request.layout.id',
      );
    }
    firstId = picked.id;
  }

  // fallback 链：版式装不下当前内容时沿库内 fallback 换版式重试。
  const chain = [];
  const seen = new Set();
  let cursor = layoutsById.get(firstId);
  while (cursor && !seen.has(cursor.id)) {
    seen.add(cursor.id);
    chain.push(cursor.id);
    cursor = cursor.fallback ? layoutsById.get(cursor.fallback) : null;
  }
  const failures = [];
  // 失败的尝试绝不能在真实 slide 上留下半成品：标题等"先画后炸"的元素会与
  // 后续尝试的输出重叠——2026-09-28 live：页 2 沿链试到第 4 个候选才落定，
  // slide 上留下 4 份标题，registry 以 text_overlap 拒绝整副 deck。因此先在
  // 一次性探针 slide 上试跑（registry/layoutReport 一并屏蔽），成功才把该
  // 候选真正画到 ctx.slide 上。
  const probeCtx = { ...ctx, slide: _probeSlide(), registry: undefined, layoutReport: undefined };
  for (const layoutId of chain) {
    try {
      _renderOnLayout(probeCtx, request, layoutId, area);
    } catch (error) {
      if (error && error.layoutFit) {
        failures.push(`${layoutId}: ${error.message}`);
        continue;
      }
      throw error;
    }
    return _renderOnLayout(ctx, request, layoutId, area);
  }
  // 链耗尽必须点名"钉住/选中的版式 + 整条链 + 每条候选各自的失败原因"：只剩链尾
  // archetype 名会被误读成 request.layout.id 没生效（2026-09-28 live：cover-split
  // 沿链退到 cover-minimal），一次只报一条规则又让 builder 一轮只能修一条。
  const detail = failures.length ? failures.join(' | ') : 'no layout produced a fit';
  const pinned = Boolean(request.layout && request.layout.id);
  const exhausted = new RangeError(
    `${pinned ? 'pinned' : 'selected'} layout "${firstId}" and its fallback chain ` +
      `[${chain.join(' -> ')}] all failed — ${detail}`,
  );
  exhausted.layoutFit = true;
  throw exhausted;
}

function _renderOnLayout(ctx, request, layoutId, area) {
  const H = _sibling('pptx-helpers');
  const V = _sibling('pptx-visuals');
  const { slide, tokens } = ctx;
  const lang = request.lang || ctx.lang || 'chinese';
  const slots = request.slots || {};
  const params = request.params || {};
  const selection = getLayout(layoutId);
  const resolved = resolveLayout(selection.id, area, { mirror: params.mirror === true });
  const zones = resolved.zones;
  if (ctx.layoutReport && Number.isInteger(ctx.slideNumber)) {
    ctx.layoutReport.push({
      slide: ctx.slideNumber,
      layout: selection.id,
      family: selection.family,
      mirror: params.mirror === true,
    });
  }

  const n = Number.isInteger(ctx.slideNumber) ? ctx.slideNumber : 0;
  const register = (element) => {
    if (ctx.registry && n) ctx.registry.register(n, element);
  };
  const sizes = H.fontSizeScale(tokens, lang);
  const fonts = H.fontFamily(tokens);

  // 1. 标题：角色字号表 + role 写进 registry（启用 D1 强调线门）。
  if (slots.title && zones.title) {
    const box = { ...zones.title, h: Math.max(zones.title.h, (sizes.title * 1.4) / 72 / 0.8) };
    const fit = H.fitText(String(slots.title), box, {
      min: sizes.title,
      max: sizes.titleMax,
      margin: 0,
      role: 'title',
    });
    if (!fit.fits) {
      throw _fitError(
        `slide ${n}: title does not fit archetype "${selection.id}" title zone at ${sizes.title}pt — shorten the title or pick an archetype with a wider title zone`,
      );
    }
    H.addFittedText(slide, slots.title, box, tokens, lang, 'title', {
      bold: true,
      margin: 0,
      fontFace: fonts.title,
      label: `S${n} 标题`,
    });
    register({
      type: 'text',
      role: 'title',
      text: slots.title,
      x: box.x,
      y: box.y,
      w: box.w,
      h: box.h,
      fontSize: fit.fontSize,
      fontFace: fonts.title,
    });
  }

  // 2. 视觉组件：zones.visual 交给 pptx-visuals 的组件库（自带适配/配色纪律）。
  //    用 renderVisual 直通有效载荷（details 展开合并）；组件层 RangeError
  //    视为"载荷装不下这个 archetype"，走 fallback 链而不是直接炸整副 deck。
  const visual = resolveVisualPayload(slots.visual);
  const component = visualComponentFor(selection.family, visual);
  if (component && zones.visual) {
    try {
      V.renderVisual(slide, component, visual, zones.visual, tokens, lang);
    } catch (error) {
      if (error instanceof RangeError) {
        throw _fitError(
          `slide ${n}: payload does not fit archetype "${selection.id}" ` +
            `(${component}): ${error.message}`,
        );
      }
      throw error;
    }
  }

  // 3. claim + 正文。body zone 只装得下 claim 时它独占该区（如 data-chart-takeaway
  //    的一行导语条）；两者都要时按 fitText 同口径（行高/0.85）精确分配高度。
  //    展示页（cover/section/quote）的 claim 走 body 角色（22-26pt）——subtitle 的
  //    26pt 下限在窄列 cover 上会把合法长句卡死，而 cover 上 title 本身就是层级锚。
  const gap = H.spacing(tokens, 3);
  const bodyItems = Array.isArray(slots.body)
    ? slots.body.filter(Boolean)
    : slots.body
      ? [String(slots.body)]
      : [];
  // 双栏的第二列借用 zones.visual，两列都会按 claimBottom 对齐——这只有在
  // 两个 zone 横向不相交（真正的"侧栏"形态，如 text-two-column / text-sidebar）
  // 时才安全。claim-focus / claim-evidence 的 visual 区在 body 区投影范围内，
  // 借作第二列会与第一列文本重叠（2026-09-28 live：页 2 残留 1 处
  // text_overlap）；这类版式走单栏堆叠，装不下就交给 fallback 链。
  const sideColumn =
    Boolean(zones.body) &&
    Boolean(zones.visual) &&
    (zones.visual.x >= zones.body.x + zones.body.w - 1e-6 ||
      zones.body.x >= zones.visual.x + zones.visual.w - 1e-6);
  const twoColumn =
    selection.family === 'claim-text' && !component && bodyItems.length >= 2 && sideColumn;
  let bodyArea = zones.body;
  let columnB = zones.visual;
  if (slots.claim && zones.body) {
    const claimRole = isDisplayFamily(selection.family) ? 'body' : 'subtitle';
    // 双栏模式下 claim 横跨两栏，两列从 claim 底部对齐起步。
    const claimBox = twoColumn
      ? {
          x: Math.min(zones.body.x, zones.visual.x),
          w:
            Math.max(zones.body.x + zones.body.w, zones.visual.x + zones.visual.w) -
            Math.min(zones.body.x, zones.visual.x),
        }
      : { x: zones.body.x, w: zones.body.w };
    // balance: false——balancedBox 允许比预估多排一行，会让实际文本超出
    // 下面 claimH 的精确分配、与正文重叠（v0.18 自测抓到的真实缺陷）。
    const claimFit = H.fitText(
      String(slots.claim),
      { w: claimBox.w, h: zones.body.h },
      {
        min: claimRole === 'body' ? Math.max(20, sizes.body - 2) : sizes.subtitle,
        max: sizes.bodyMax,
        margin: 0,
        role: claimRole,
        balance: false,
      },
    );
    if (!claimFit.fits) {
      throw _fitError(
        `slide ${n}: claim does not fit archetype "${selection.id}" body zone — shorten the claim`,
      );
    }
    const claimNeeded = (claimFit.lines * claimFit.fontSize * 1.18) / 72 / 0.85;
    const withBody = bodyItems.length > 0;
    if (withBody && claimNeeded + gap + 0.5 > zones.body.h + 0.01) {
      throw _fitError(
        `slide ${n}: archetype "${selection.id}" body zone (${zones.body.h.toFixed(2)}in) is too ` +
          'small for claim + body copy — pick an archetype with a larger body zone (see fallback chain) or trim the body',
      );
    }
    // 展示页（cover/section/quote/closing）只有 claim 时垂直居中——
    // 大 zone 顶部贴一句会留下头重脚轻的死区（v0.19 solveStack）。
    const claimStack = H.solveStack(
      zones.body,
      [{ key: 'claim', height: Math.min(claimNeeded, zones.body.h) }],
      {
        gap: 0,
        justify: !withBody && isDisplayFamily(selection.family) ? 'center' : 'start',
      },
    );
    const claimSlot = claimStack.boxes.claim;
    const claimH = claimSlot.h;
    H.addFittedText(
      slide,
      slots.claim,
      {
        x: claimBox.x,
        y: claimSlot.y,
        w: claimBox.w,
        h: claimH,
      },
      tokens,
      lang,
      claimRole,
      { margin: 0, label: `S${n} claim`, balance: false },
    );
    register({
      type: 'text',
      role: 'subtitle',
      text: slots.claim,
      x: claimBox.x,
      y: claimSlot.y,
      w: claimBox.w,
      h: claimH,
      fontSize: claimFit.fontSize,
    });
    const claimBottom = claimSlot.y + claimH + (withBody ? gap : 0);
    bodyArea = withBody
      ? {
          x: zones.body.x,
          y: claimBottom,
          w: zones.body.w,
          h: zones.body.y + zones.body.h - claimBottom,
        }
      : null;
    if (twoColumn) {
      columnB = {
        x: zones.visual.x,
        y: claimBottom,
        w: zones.visual.w,
        h: zones.visual.y + zones.visual.h - claimBottom,
      };
    }
  }

  if (twoColumn) {
    // 双栏文本：claim-text 家族在无视觉载荷时把 visual zone 用作第二文本列。
    // 第一列从 claim 之下的剩余区开始（bodyArea），不能整占 zones.body。
    const columnA = bodyArea || zones.body;
    const half = Math.ceil(bodyItems.length / 2);
    _addBodyWithFit(ctx, selection.id, bodyItems.slice(0, half), columnA, tokens, lang, {
      bullet: false,
    });
    _addBodyWithFit(ctx, selection.id, bodyItems.slice(half), columnB, tokens, lang, {
      bullet: false,
    });
    register({
      type: 'text',
      role: 'body',
      text: bodyItems.slice(0, half).join('\n'),
      ...columnA,
    });
    register({
      type: 'text',
      role: 'body',
      text: bodyItems.slice(half).join('\n'),
      ...columnB,
    });
  } else if (bodyItems.length && bodyArea && bodyArea.h > 0.25) {
    _addBodyWithFit(ctx, selection.id, bodyItems, bodyArea, tokens, lang, {
      bullet: bodyItems.length > 1,
    });
    register({ type: 'text', role: 'body', text: bodyItems.join('\n'), ...bodyArea });
  } else if (bodyItems.length && !zones.body) {
    throw _fitError(
      `slide ${n}: archetype "${selection.id}" has no body zone but slots.body was supplied — drop the body copy or let the fallback chain pick an archetype with a body zone`,
    );
  }

  return {
    layout: selection.id,
    family: selection.family,
    silhouette: selection.silhouette,
    zones,
  };
}

function resolveLayout(id, safeArea, options = {}) {
  const layout = getLayout(id);
  const area = {
    x: Number(safeArea?.x ?? 0),
    y: Number(safeArea?.y ?? 0),
    w: Number(safeArea?.w ?? safeArea?.width ?? 1),
    h: Number(safeArea?.h ?? safeArea?.height ?? 1),
  };
  if (!(area.w > 0 && area.h > 0)) throw new Error('safeArea width and height must be positive');

  const mirror = Boolean(options.mirror);
  const zones = {};
  // executableLayout 用 `layout.zones &&` 做空值防御，这里却直接 Object.entries，
  // 两处假设矛盾；外部版式源缺 zones 时会抛 TypeError。统一为"缺失即空分区"。
  for (const [name, normalized] of Object.entries(layout.zones || {})) {
    if (!Array.isArray(normalized) || normalized.length < 4) continue;
    const [nx, ny, nw, nh] = normalized;
    const resolvedX = mirror ? 1 - nx - nw : nx;
    zones[name] = {
      x: area.x + resolvedX * area.w,
      y: area.y + ny * area.h,
      w: nw * area.w,
      h: nh * area.h,
    };
  }
  return { ...layout, safeArea: area, mirrored: mirror, zones };
}

module.exports = {
  getLayout,
  suggestLayouts,
  selectLayouts,
  pickLayout,
  resolveLayout,
  renderArchetype,
  visualComponentFor,
  registry,
};
