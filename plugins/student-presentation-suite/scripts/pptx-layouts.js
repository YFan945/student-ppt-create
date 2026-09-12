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

// Backwards-compatible name. Selecting a layout returns ranked inspiration; it
// does not authorize callers to resolve or render exact coordinates.
function selectLayouts(context = {}, tokens = {}, history = [], count = 3) {
  return suggestLayouts(context, tokens, history, count);
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
  resolveLayout,
  registry,
};
