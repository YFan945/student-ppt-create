'use strict';

const fs = require('node:fs');
const path = require('node:path');
const H = require('pptx-helpers');
const L = require('pptx-layouts');
const V = require('pptx-visuals');

// 同一 asset 路径在一次 deck 构建里最多被探测 5 次（每页 preflight + render 各一次），
// 网络盘下 IO 放大明显。构建是一次性进程，按绝对路径缓存存在性即可。
const _assetExistsCache = new Map();
function assetExists(asset) {
  const key = path.resolve(String(asset));
  if (!_assetExistsCache.has(key)) _assetExistsCache.set(key, fs.existsSync(key));
  return _assetExistsCache.get(key);
}

const FAMILY_BY_TYPE = Object.freeze({
  chart: 'dashboard',
  data: 'dashboard',
  process: 'process-path',
  timeline: 'timeline',
  comparison: 'comparison',
  architecture: 'architecture',
  system: 'architecture',
  matrix: 'matrix',
  quote: 'quote',
  image: 'visual-dominant',
  illustration: 'visual-dominant',
  summary: 'summary',
  references: 'reference',
  reference: 'reference',
});

function slideText(slideSpec) {
  const value =
    slideSpec.slide_copy ??
    slideSpec.supporting_points ??
    slideSpec.content ??
    slideSpec.claim ??
    '';
  if (Array.isArray(value)) return value.map(String);
  if (value && typeof value === 'object')
    return Object.values(value).filter((item) => typeof item === 'string');
  return String(value || '');
}

function bodyText(slideSpec) {
  if (slideSpec.visual)
    return String(
      slideSpec.claim || (typeof slideSpec.content === 'string' ? slideSpec.content : '') || '',
    );
  return slideText(slideSpec);
}

function bodyRole(slideSpec) {
  return ['cover', 'section-divider', 'closing'].includes(slideSpec.kind) ? 'label' : 'body';
}

function shouldRenderBody(slideSpec) {
  return visualFamily(slideSpec) !== 'summary';
}

function visualFamily(slideSpec) {
  return slideSpec.visual?.layout_family || FAMILY_BY_TYPE[slideSpec.visual?.type] || null;
}

function contextFor(slideSpec, context) {
  const content = slideText(slideSpec);
  const itemCount = Array.isArray(content) ? content.length : content ? 1 : 0;
  const asset = slideSpec.visual?.asset;
  return {
    slideId: slideSpec.id,
    title: slideSpec.title,
    titleChars: [...String(slideSpec.title || '')].length,
    slideKind: slideSpec.kind,
    role: slideSpec.role,
    layout: slideSpec.layout,
    layoutFamily: visualFamily(slideSpec),
    itemCount,
    hasAsset: Boolean(asset && assetExists(asset)),
    hasData: Boolean(slideSpec.visual?.details?.series || slideSpec.visual?.details?.metrics),
    hasQuote: Boolean(slideSpec.visual?.details?.quote || slideSpec.visual?.type === 'quote'),
    seed: context.seed || `${context.topic || 'deck'}:${slideSpec.id}`,
  };
}

function suggestCompositions(slideSpec, context, count = 3) {
  const selected = L.suggestLayouts(
    contextFor(slideSpec, context),
    context.tokens,
    context.history || [],
    count,
  );
  if (!selected.length) throw new RangeError(`No feasible layout for slide ${slideSpec.id}`);
  return selected;
}

function resolveSlideComposition(slideSpec, context) {
  const area =
    context.safeArea ||
    H.safeArea(context.slideW || H.SLIDE_W_IN, context.slideH || H.SLIDE_H_IN, context.tokens, {
      reserveTitle: false,
    });
  const mode = context.compositionMode || 'adaptive-freeform';
  const locked = slideSpec.layout_lock === true;
  if (!locked && mode !== 'deterministic-fallback') {
    return {
      mode: 'adaptive-freeform',
      layout_hint: slideSpec.layout || null,
      safeArea: area,
      suggestions: suggestCompositions(slideSpec, context, context.suggestionCount || 3),
      exact: false,
    };
  }

  let layout;
  if (locked) {
    try {
      layout = L.getLayout(slideSpec.layout);
    } catch (error) {
      throw new RangeError(
        `Slide ${slideSpec.id} locks unknown layout ${slideSpec.layout}: ${error.message}`,
      );
    }
  } else {
    layout = suggestCompositions(slideSpec, context, 1)[0];
  }
  return {
    ...L.resolveLayout(layout.id, area, { mirror: Boolean(context.mirror) }),
    mode: locked ? 'layout-locked' : 'deterministic-fallback',
    exact: true,
  };
}

function suppliedComposition(slideSpec, context) {
  return context.composition || context.compositions?.[slideSpec.id] || null;
}

function actualComposition(slideSpec, context) {
  const resolved = resolveSlideComposition(slideSpec, context);
  if (resolved.exact) return resolved;
  const supplied = suppliedComposition(slideSpec, context);
  if (!supplied) return resolved;
  const body = bodyText(slideSpec);
  const requiredZones = ['title'];
  if (
    shouldRenderBody(slideSpec) &&
    ((Array.isArray(body) && body.length) || (!Array.isArray(body) && body))
  )
    requiredZones.push('body');
  if (slideSpec.visual) requiredZones.push('visual');
  const missingZones = requiredZones.filter((name) => !supplied.zones?.[name]);
  if (missingZones.length) {
    throw new RangeError(
      `Slide ${slideSpec.id} freeform composition is missing zones: ${missingZones.join(', ')}`,
    );
  }
  return {
    ...supplied,
    id: supplied.id || `freeform-${slideSpec.id}`,
    mode: 'adaptive-freeform',
    exact: false,
    safeArea: resolved.safeArea,
    suggestions: resolved.suggestions,
    silhouette: supplied.silhouette || 'custom',
  };
}

function preflightSlide(slideSpec, context) {
  const layout = actualComposition(slideSpec, context);
  const body = bodyText(slideSpec);
  const results = [];
  const errors = [];
  if (!layout.zones) {
    errors.push(
      'adaptive-freeform requires caller-supplied composition zones before rendering; layout suggestions are advisory only',
    );
  } else {
    const slideW = context.slideW || H.SLIDE_W_IN;
    const slideH = context.slideH || H.SLIDE_H_IN;
    for (const [name, box] of Object.entries(layout.zones)) {
      if (
        !Number.isFinite(box.x) ||
        !Number.isFinite(box.y) ||
        !Number.isFinite(box.w) ||
        !Number.isFinite(box.h) ||
        box.x < 0 ||
        box.y < 0 ||
        box.w <= 0 ||
        box.h <= 0 ||
        box.x + box.w > slideW + 1e-6 ||
        box.y + box.h > slideH + 1e-6
      ) {
        errors.push(`${name}: composition zone is outside the slide canvas`);
      }
    }
    results.push(
      H.preflightText(slideSpec.title, layout.zones.title, context.tokens, context.lang, 'title'),
    );
  }
  if (
    shouldRenderBody(slideSpec) &&
    ((Array.isArray(body) && body.length) || (!Array.isArray(body) && body)) &&
    layout.zones
  ) {
    results.push(
      H.preflightText(
        Array.isArray(body) ? body.join('\n') : body,
        layout.zones.body,
        context.tokens,
        context.lang,
        bodyRole(slideSpec),
      ),
    );
  }
  const missingAsset = Boolean(slideSpec.visual?.asset && !assetExists(slideSpec.visual.asset));
  errors.push(
    ...results
      .filter((result) => !result.ok)
      .map((result) => `${result.role}: ${result.resolution}`),
  );
  if (missingAsset && context.imageStrategy !== 'hybrid-adaptive')
    errors.push('visual asset does not exist and no adaptive fallback is enabled');
  return {
    ok: errors.length === 0,
    slide_id: slideSpec.id,
    layout: layout.id || null,
    composition: layout,
    composition_mode: layout.mode,
    suggestions: layout.suggestions?.map((item) => item.id) || [],
    text: results,
    errors,
    missing_asset: missingAsset,
  };
}

function fallbackIllustration(slide, slideSpec, box, context) {
  V.renderVisual(
    slide,
    'hero',
    {
      title: slideSpec.visual?.purpose || slideSpec.claim || 'Key idea',
      subtitle: slideSpec.visual?.alt_text || '',
    },
    box,
    context.tokens,
    context.lang,
  );
}

function renderSlide(slide, slideSpec, context, preflight) {
  // compose 已对全部页跑过 preflight 并携带 composition 结果；外部直调（无第 4 参）
  // 时才自行计算。此前每页重复跑 2 次 preflight、3 次 actualComposition。
  const check = preflight || preflightSlide(slideSpec, context);
  if (!check.ok)
    throw new RangeError(`Slide ${slideSpec.id} preflight failed: ${check.errors.join('; ')}`);
  const layout = check.composition;
  if (!layout)
    throw new RangeError(`Slide ${slideSpec.id} preflight result lacks composition layout`);
  H.addBackground(slide, context.tokens, false);
  H.addFittedText(
    slide,
    slideSpec.title,
    layout.zones.title,
    context.tokens,
    context.lang,
    'title',
    {
      align:
        layout.text_policy === 'display' && layout.silhouette === 'center-focus'
          ? 'center'
          : 'left',
      bold: true,
      label: `幻灯片 ${slideSpec.id} 标题`,
    },
  );
  const body = bodyText(slideSpec);
  if (
    shouldRenderBody(slideSpec) &&
    ((Array.isArray(body) && body.length) || (!Array.isArray(body) && body))
  ) {
    H.addFittedText(
      slide,
      Array.isArray(body) ? body.join('\n') : body,
      layout.zones.body,
      context.tokens,
      context.lang,
      bodyRole(slideSpec),
      { bullet: Array.isArray(body), label: `幻灯片 ${slideSpec.id} 正文` },
    );
  }
  if (slideSpec.visual) {
    const family = visualFamily(slideSpec);
    const assetUsable = !slideSpec.visual.asset || assetExists(slideSpec.visual.asset);
    if (family && assetUsable) {
      const visualBox = family === 'summary' ? layout.zones.body : layout.zones.visual;
      V.renderVisualSpec(slide, slideSpec.visual, family, visualBox, context.tokens, context.lang);
    } else if (layout.mode === 'deterministic-fallback') {
      fallbackIllustration(slide, slideSpec, layout.zones.visual, context);
    }
  } else if (
    layout.mode === 'deterministic-fallback' &&
    !['cover', 'section-divider', 'closing', 'references'].includes(slideSpec.kind)
  ) {
    fallbackIllustration(
      slide,
      { ...slideSpec, visual: { purpose: slideSpec.claim || 'Organize the slide claim' } },
      layout.zones.visual,
      context,
    );
  }
  if (slideSpec.speaker_notes && typeof slide.addNotes === 'function')
    slide.addNotes(slideSpec.speaker_notes);
  context.history.push({ layout: layout.id, silhouette: layout.silhouette });
  return {
    slide_id: slideSpec.id,
    layout: layout.id,
    silhouette: layout.silhouette,
    composition_mode: layout.mode,
  };
}

function renderDeck(pptx, spec, context) {
  const resolved = {
    history: [],
    imageStrategy: spec.meta?.image_source || 'hybrid-adaptive',
    topic: spec.meta?.topic,
    ...context,
  };
  H.applyTokens(pptx, resolved.tokens, resolved.lang);
  const preflight = spec.slides.map((slideSpec) => preflightSlide(slideSpec, resolved));
  const blockers = preflight.filter((item) => !item.ok);
  if (blockers.length)
    // 拼上每页的具体违规项，否则调用方只能看到 slide_id，无法定位违规区域。
    throw new RangeError(
      `Deck preflight failed on slides: ${blockers
        .map((item) => `${item.slide_id}(${(item.errors || []).join('; ')})`)
        .join(', ')}`,
    );
  const rendered = spec.slides.map((slideSpec, index) =>
    renderSlide(pptx.addSlide(), slideSpec, resolved, preflight[index]),
  );
  return { preflight, rendered };
}

module.exports = {
  preflightSlide,
  resolveSlideComposition,
  suggestCompositions,
  renderSlide,
  renderDeck,
};
