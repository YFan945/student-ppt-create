'use strict';

/**
 * Actual element registry for model-authored PptxGenJS decks.
 *
 * Goal: inspect the same geometry that is actually sent to PptxGenJS rather
 * than only checking an advisory composition plan. The registry is intentionally
 * renderer-agnostic: callers register text/shapes/images/charts/lines when they
 * add them to a slide, then run analyzeSlide() before writing the PPTX.
 */

const DEFAULTS = {
  // 与 pptx-helpers.js SLIDE_W_IN/SLIDE_H_IN（10×5.625in，STUDENT_WIDE 版式）一致；
  // 越界判定必须与真实产物同基准。tests/test_stack_contract.py 锁定两侧一致。
  slideW: 10,
  slideH: 5.625,
  safeMargin: 0.12,
  overlapTolerance: 0.015,
  minTextW: 0.05,
  minTextH: 0.05,
  // Generators set footerTop to the y of the source line; content crossing it
  // used to survive until the rendered check, which costs a full build+render.
  footerTop: null,
  // requiredH / boxH above this ratio is a real overflow, not a "may overflow".
  textOverflowErrorRatio: 1.2,
  // 同行左缘近失对齐：差值小于公差算对齐，大于 0.30in 算有意错位，
  // 落在 (公差, 0.30in] 区间的是"看起来想对齐但没对上"的真实缺陷。
  alignmentTolerance: 0.045,
  nearMissBand: 0.3,
};

function finite(v) {
  return typeof v === 'number' && Number.isFinite(v);
}

function bboxOf(el) {
  if (!el || !finite(el.x) || !finite(el.y) || !finite(el.w) || !finite(el.h)) return null;
  return { x: el.x, y: el.y, w: el.w, h: el.h, r: el.x + el.w, b: el.y + el.h };
}

function overlapArea(a, b, tolerance = DEFAULTS.overlapTolerance) {
  const x = Math.max(0, Math.min(a.r, b.r) - Math.max(a.x, b.x) - tolerance);
  const y = Math.max(0, Math.min(a.b, b.b) - Math.max(a.y, b.y) - tolerance);
  return x * y;
}

function occupiedRegions(el, fallback) {
  if (el.type !== 'text') return [fallback];
  if (!Array.isArray(el.lineGeometry) || !el.lineGeometry.length) return null;
  const regions = [];
  for (const line of el.lineGeometry) {
    const box = bboxOf(line);
    if (!box || box.w < 0 || box.h <= 0) return null;
    if (box.w === 0 && (typeof line.text !== 'string' || line.text.trim())) return null;
    // Empty lines have height but no ink and must not cause overlap errors.
    if (box.w > 0) regions.push(box);
  }
  return regions;
}

function isDecorative(el) {
  return Boolean(el.decorative || el.allowOverlap || el.type === 'background');
}

function solidColor(fill) {
  if (!fill || fill.type === 'none' || Number(fill.transparency || 0) !== 0) return null;
  const value = typeof fill === 'string' ? fill : fill.color;
  return typeof value === 'string' && /^[0-9a-f]{6}$/i.test(value) ? value : null;
}

function contrastRatio(first, second) {
  const luminance = (hex) => {
    const channels = [0, 2, 4].map((offset) => {
      const value = parseInt(hex.slice(offset, offset + 2), 16) / 255;
      return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
    });
    return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
  };
  const a = luminance(first);
  const b = luminance(second);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

function overlaps(a, b) {
  return Math.min(a.r, b.r) > Math.max(a.x, b.x) && Math.min(a.b, b.b) > Math.max(a.y, b.y);
}

function encloses(a, b) {
  return a.x <= b.x && a.y <= b.y && a.r >= b.r && a.b >= b.b;
}

/**
 * 非安全字体的字宽余量。优先复用 pptx-helpers 的白名单（单一事实源）；
 * registry 需要保持可独立使用：裸名解析失败时回退同目录文件，再失败按 1
 * （只损失余量精度，不影响其余检查）。
 */
function fontWidthFactorFor(fontFace) {
  if (!fontFace) return 1;
  try {
    const H = require('./pptx-helpers.js');
    if (typeof H.fontWidthFactor === 'function') return H.fontWidthFactor(fontFace);
  } catch {
    try {
      const H = require('node:path').join(__dirname, 'pptx-helpers.js');
      const loaded = require(H);
      if (typeof loaded.fontWidthFactor === 'function') return loaded.fontWidthFactor(fontFace);
    } catch {
      /* standalone fallback below */
    }
  }
  return 1;
}

function estimateTextFit(el) {
  const text = String(el.text || '');
  const fontSize = finite(el.fontSize) ? el.fontSize : 18;
  const box = bboxOf(el);
  if (!box || !text) return { ok: true, estimatedLines: 0, capacity: Infinity };
  if (Array.isArray(el.lineGeometry)) {
    const requiredH = el.lineGeometry.reduce((sum, line) => sum + line.h, 0);
    return {
      ok: requiredH <= box.h * 1.03 && el.lineGeometry.every((line) => line.w <= box.w),
      estimatedLines: el.lineGeometry.length,
      requiredH,
      boxH: box.h,
    };
  }

  const cjk = (text.match(/[\u3400-\u9fff\uf900-\ufaff]/g) || []).length;
  const latin = Math.max(0, text.length - cjk);
  // Must match copy_fit_preflight.py (CJK_EM=1.0, LATIN_EM=0.58) and
  // pptx-helpers.js. KaiTi/DengXian advance is a full em; 0.92 leaked wraps.
  // 非安全字体再乘 +10% 宽度余量（LibreOffice 会换宽度不同的字体渲染 QA）。
  const estimatedWidth =
    ((cjk * fontSize * 1.0 + latin * fontSize * 0.58) / 72) * fontWidthFactorFor(el.fontFace);
  const usableW = Math.max(DEFAULTS.minTextW, box.w - (el.paddingX || 0));
  const estimatedLines = Math.max(1, Math.ceil(estimatedWidth / usableW));
  // pptxgenjs `lineSpacing` is POINTS. Values <= 4 are treated as a legacy
  // multiplier so older generators that passed 1.18 still analyze. Helpers
  // now emit fontSize * 1.18 points.
  const spacing = el.lineSpacing;
  const lineHeightPt =
    finite(spacing) && spacing > 4 ? spacing : (finite(spacing) ? spacing : 1.18) * fontSize;
  const lineHeight = lineHeightPt / 72;
  const requiredH = estimatedLines * lineHeight + (el.paddingY || 0);
  return {
    ok: requiredH <= box.h * 1.03,
    estimatedLines,
    requiredH,
    boxH: box.h,
  };
}

function lineIntersectsBox(line, box) {
  if (![line.x1, line.y1, line.x2, line.y2].every(finite)) return false;
  const minX = Math.min(line.x1, line.x2);
  const maxX = Math.max(line.x1, line.x2);
  const minY = Math.min(line.y1, line.y2);
  const maxY = Math.max(line.y1, line.y2);
  if (maxX < box.x || minX > box.r || maxY < box.y || minY > box.b) return false;
  // Approximation is deliberate: false positives are preferable to missed text crossings.
  return true;
}

class SlideElementRegistry {
  constructor(options = {}) {
    this.options = { ...DEFAULTS, ...options };
    this.slides = new Map();
    this.backgrounds = new Map();
  }

  _slide(index) {
    if (!this.slides.has(index)) this.slides.set(index, []);
    return this.slides.get(index);
  }

  register(slideIndex, element) {
    if (!Number.isInteger(slideIndex) || slideIndex < 1) throw new Error('slideIndex must be >= 1');
    if (this.options.capture && element.type === 'text')
      element = { ...element, decorative: false, allowOverlap: false };
    if (this.options.capture) {
      const logical = this._slide(slideIndex).find(
        (item) =>
          item.type === element.type &&
          item.logicalText === element.text &&
          item.logicalBox &&
          ['x', 'y', 'w', 'h'].every((key) => Math.abs(item.logicalBox[key] - element[key]) < 1e-6),
      );
      if (logical) {
        if (element.role) logical.role = element.role;
        return logical; // A manual parent registration refers to captured spans.
      }
      const prior = this._slide(slideIndex).find(
        (item) =>
          item.type === element.type &&
          item.text === element.text &&
          ['x', 'y', 'w', 'h'].every(
            (key) => Math.abs((bboxOf(item)?.[key] ?? 0) - (bboxOf(element)?.[key] ?? 0)) < 1e-6,
          ),
      );
      if (prior) {
        Object.assign(prior, element);
        return prior;
      }
    }
    const normalized = {
      id: element.id || `s${slideIndex}-e${this._slide(slideIndex).length + 1}`,
      type: element.type || 'shape',
      ...element,
    };
    this._slide(slideIndex).push(normalized);
    return normalized;
  }

  text(slideIndex, text, opts = {}) {
    return this.register(slideIndex, { type: 'text', text, ...opts });
  }

  shape(slideIndex, opts = {}) {
    return this.register(slideIndex, { type: 'shape', ...opts });
  }

  image(slideIndex, opts = {}) {
    return this.register(slideIndex, { type: 'image', ...opts });
  }

  chart(slideIndex, opts = {}) {
    return this.register(slideIndex, { type: 'chart', ...opts });
  }

  line(slideIndex, opts = {}) {
    return this.register(slideIndex, { type: 'line', ...opts });
  }

  analyzeSlide(slideIndex) {
    const elements = this._slide(slideIndex);
    const errors = [];
    const warnings = [];
    const { slideW, slideH, safeMargin } = this.options;

    // Only known solid surfaces are deterministic. Images, gradients, partial
    // coverage and rotated shapes need inspection; do not guess their pixels.
    let contrastChecked = 0;
    let contrastUnresolved = 0;
    if (this.options.capture) {
      for (const [index, el] of elements.entries()) {
        if (el.type !== 'text' || !String(el.text || '').trim()) continue;
        const box = bboxOf(el);
        if (!box) continue;
        let background = solidColor(this.backgrounds.get(slideIndex));
        for (const lower of elements.slice(0, index)) {
          const lowerBox = bboxOf(lower);
          if (
            !lowerBox ||
            lower.type === 'text' ||
            lower.type === 'line' ||
            !overlaps(lowerBox, box)
          )
            continue;
          if (lower.fill?.transparency === 100 || lower.fill?.type === 'none') continue;
          background =
            lower.type === 'shape' &&
            lower.shapeType === 'rect' &&
            !lower.rotate &&
            encloses(lowerBox, box)
              ? solidColor(lower.fill)
              : null;
        }
        if (el.fill && el.fill.transparency !== 100) background = solidColor(el.fill);
        const colors = el.textColors || [el.color];
        if (
          !background ||
          el.transparency ||
          !colors.length ||
          colors.some((color) => !solidColor({ color }))
        ) {
          contrastUnresolved += 1;
          continue;
        }
        contrastChecked += 1;
        const ratio = Math.min(...colors.map((color) => contrastRatio(color, background)));
        if (ratio < 3)
          errors.push({
            code: 'text_low_contrast',
            element: el.id,
            ratio: Number(ratio.toFixed(2)),
            background,
            message:
              'Text on a known solid surface has contrast below 3:1; change foreground/background and inspect the render.',
          });
        else if (ratio < 4.5)
          warnings.push({
            code: 'text_contrast_review',
            element: el.id,
            ratio: Number(ratio.toFixed(2)),
            background,
            message: 'Contrast is below 4.5:1; inspect text size, weight and viewing conditions.',
          });
      }
    }

    for (const el of elements) {
      if (el.type === 'line') continue;
      const box = bboxOf(el);
      if (!box) {
        errors.push({
          code: 'invalid_bbox',
          element: el.id,
          message: 'Element has invalid x/y/w/h.',
        });
        continue;
      }
      if (box.w <= 0 || box.h <= 0) {
        errors.push({
          code: 'non_positive_size',
          element: el.id,
          message: 'Element width/height must be positive.',
        });
      }
      if (
        (box.x < -safeMargin ||
          box.y < -safeMargin ||
          box.r > slideW + safeMargin ||
          box.b > slideH + safeMargin) &&
        !(el.bleed === true && isDecorative(el) && el.type === 'shape')
      ) {
        errors.push({
          code: 'out_of_canvas',
          element: el.id,
          bbox: box,
          message: 'Element exceeds slide canvas.',
        });
      }
      const footerTop = this.options.footerTop;
      if (
        footerTop !== null &&
        footerTop !== undefined &&
        !isDecorative(el) &&
        box.b > footerTop + this.options.overlapTolerance
      ) {
        errors.push({
          code: 'content_overflow_bottom',
          element: el.id,
          bbox: box,
          footerTop,
          message: 'Element crosses the footer/source line.',
        });
      }
      if (el.type === 'text') {
        const fit = estimateTextFit(el);
        if (!fit.ok) {
          const severe =
            fit.boxH > 0 && fit.requiredH > fit.boxH * this.options.textOverflowErrorRatio;
          const issue = {
            code: severe ? 'text_overflow' : 'text_may_overflow',
            element: el.id,
            ...fit,
          };
          (severe ? errors : warnings).push(issue);
        }
      }
    }

    const boxes = elements
      .filter((el) => el.type !== 'line')
      .map((el) => ({ el, box: bboxOf(el) }))
      .filter((x) => x.box);
    for (let i = 0; i < boxes.length; i += 1) {
      for (let j = i + 1; j < boxes.length; j += 1) {
        const a = boxes[i];
        const b = boxes[j];
        // Captured calls retain drawing order: a background painted before
        // text cannot occlude that later text. Do not require a decoration tag.
        if (this.options.capture && a.el.type !== 'text' && b.el.type === 'text') continue;
        if (isDecorative(a.el) || isDecorative(b.el)) {
          // Decorative describes purpose, never permission to hide earlier text.
          const foregroundMask =
            this.options.capture &&
            a.el.type === 'text' &&
            b.el.type !== 'text' &&
            (b.el.type === 'image' || Boolean(solidColor(b.el.fill)));
          if (!foregroundMask) continue;
        }
        // Measured text occupies its rendered lines, not all empty space in
        // its authoring box. Keep conservative box checks when unmeasured.
        const aInk = occupiedRegions(a.el, a.box);
        const bInk = occupiedRegions(b.el, b.box);
        const aRegions = aInk && bInk ? aInk : [a.box];
        const bRegions = aInk && bInk ? bInk : [b.box];
        let ratio = 0;
        for (const ar of aRegions) {
          for (const br of bRegions) {
            const area = overlapArea(ar, br, this.options.overlapTolerance);
            const minArea = Math.min(ar.w * ar.h, br.w * br.h);
            if (minArea > 0) ratio = Math.max(ratio, area / minArea);
          }
        }
        if (ratio <= 0) continue;
        const involvesText = a.el.type === 'text' || b.el.type === 'text';
        const issue = {
          code: involvesText ? 'text_overlap' : 'element_overlap',
          a: a.el.id,
          b: b.el.id,
          overlapRatio: ratio,
        };
        if (involvesText && ratio > 0.04) errors.push(issue);
        else if (ratio > 0.12) warnings.push(issue);
      }
    }

    const textBoxes = boxes.filter((x) => x.el.type === 'text');
    for (const line of elements.filter((el) => el.type === 'line' && !el.allowTextCrossing)) {
      for (const text of textBoxes) {
        const regions =
          this.options.capture && text.el.lineGeometry?.length
            ? text.el.lineGeometry.map((geometry) => bboxOf(geometry)).filter(Boolean)
            : [text.box];
        if (regions.some((region) => lineIntersectsBox(line, region))) {
          warnings.push({ code: 'line_crosses_text', line: line.id, text: text.el.id });
        }
      }
    }

    if (!this.options.designPreferencesAdvisory) {
      this._checkDesignGrammar(elements, boxes, errors, warnings);
      this._checkAlignment(boxes, errors);
      this._checkDeadZone(boxes, warnings);
    }

    return {
      slideIndex,
      ok: errors.length === 0,
      errors,
      warnings,
      elementCount: elements.length,
      contrast: {
        checked: contrastChecked,
        unresolved: contrastUnresolved,
        scope: 'known solid surfaces; unresolved requires rendered inspection',
      },
    };
  }

  /**
   * Design grammar 硬规则的几何执行端（references/pptx-design-grammar.md D1/D2/D9）。
   * 只拦"注册了 role 的标题 + 细长形状/横线"这类可确定性判定的问题；
   * 抽象判断（是否真装饰）交给独立 critic，不在这里猜。
   */
  _checkDesignGrammar(elements, boxes, errors, warnings) {
    const titleBoxes = boxes.filter((x) => x.el.type === 'text' && x.el.role === 'title');
    const thinShapes = boxes
      .filter((x) => x.el.type !== 'line' && !isDecorative(x.el))
      .filter((x) => {
        const min = Math.min(x.box.w, x.box.h);
        const max = Math.max(x.box.w, x.box.h);
        return min <= 0.09 && max >= min * 5;
      });
    const flagged = new Set();
    for (const title of titleBoxes) {
      for (const bar of thinShapes) {
        const below = bar.box.y >= title.box.b - 0.02 && bar.box.y <= title.box.b + 0.45;
        const xOverlap = Math.min(title.box.r, bar.box.r) - Math.max(title.box.x, bar.box.x);
        if (below && xOverlap >= Math.min(title.box.w * 0.4, bar.box.w * 0.6)) {
          flagged.add(bar.el.id);
          errors.push({
            code: 'accent_line_under_title',
            element: bar.el.id,
            title: title.el.id,
            message:
              'Design grammar D1: decorative emphasis line under the title. Separate title and content with whitespace, not a rule.',
          });
        }
      }
      for (const line of elements.filter((el) => el.type === 'line' && el.role !== 'style_rule')) {
        const lx = Math.min(line.x1, line.x2);
        const rx = Math.max(line.x1, line.x2);
        const ltop = Math.min(line.y1, line.y2);
        if (!Number.isFinite(lx) || !Number.isFinite(ltop)) continue;
        const below = ltop >= title.box.b - 0.02 && ltop <= title.box.b + 0.45;
        const xOverlap = Math.min(title.box.r, rx) - Math.max(title.box.x, lx);
        const length = rx - lx;
        if (below && length >= 0.5 && xOverlap >= Math.min(title.box.w * 0.4, length * 0.6)) {
          errors.push({
            code: 'accent_line_under_title',
            element: line.id,
            title: title.el.id,
            message:
              'Design grammar D1: decorative emphasis line under the title. Separate title and content with whitespace, not a rule.',
          });
        }
      }
    }
    for (const bar of thinShapes) {
      if (flagged.has(bar.el.id)) continue;
      warnings.push({
        code: 'decorative_stripe',
        element: bar.el.id,
        message:
          'Design grammar D2: thin decorative bar/stripe. Prefer whitespace, hairline rules (registered as line, <=1pt) or full panels.',
      });
    }
    for (const line of elements.filter((el) => el.type === 'line')) {
      const dx = Math.abs(line.x2 - line.x1);
      const dy = Math.abs(line.y2 - line.y1);
      if (Number.isFinite(dx) && Number.isFinite(dy) && dx > 0.02 && dy > 0.02) {
        warnings.push({
          code: 'non_orthogonal_connector',
          line: line.id,
          message:
            'tokens.lines.connector_style is orthogonal: diagonal connectors read as accidental. Route horizontally/vertically or mark allowTextCrossing-intent explicitly.',
        });
      }
    }
  }

  /**
   * 左缘近失对齐（v0.18 美学门）。
   *
   * 抓的是"水平方向明显重叠（堆叠内容块）、左缘却差出 0.045-0.30in"的 pair——
   * 这是手算坐标最典型的漂移形态。左右并排的列块水平重叠低，天然不触发；
   * 容器与其内嵌标签（面板 + 内缩文字）通过包含关系排除。
   */
  _checkAlignment(boxes, errors) {
    const { alignmentTolerance, nearMissBand } = this.options;
    const contains = (outer, inner) =>
      outer.x <= inner.x + alignmentTolerance &&
      outer.r >= inner.r - alignmentTolerance &&
      outer.y <= inner.y + alignmentTolerance &&
      outer.b >= inner.b - alignmentTolerance;
    const logical = new Map();
    const content = boxes
      .filter((x) => !isDecorative(x.el))
      .map((item) => {
        if (!item.el.logicalBox) return item;
        const key = JSON.stringify(item.el.logicalBox);
        if (logical.has(key)) return null;
        logical.set(key, true);
        return { el: item.el, box: bboxOf(item.el.logicalBox) };
      })
      .filter(Boolean);
    for (let i = 0; i < content.length; i += 1) {
      for (let j = i + 1; j < content.length; j += 1) {
        const a = content[i];
        const b = content[j];
        const overlapX = Math.min(a.box.r, b.box.r) - Math.max(a.box.x, b.box.x);
        const minW = Math.min(a.box.w, b.box.w);
        if (minW <= 0 || overlapX < minW * 0.5) continue;
        if (contains(a.box, b.box) || contains(b.box, a.box)) continue;
        const dx = Math.abs(a.box.x - b.box.x);
        if (dx > alignmentTolerance && dx <= nearMissBand) {
          errors.push({
            code: 'near_miss_alignment',
            a: a.el.id,
            b: b.el.id,
            delta: Math.round(dx * 1000) / 1000,
            message:
              `Overlapping-content blocks differ in left edge by ${dx.toFixed(3)}in ` +
              `(tolerance ${alignmentTolerance}in): align both edges or separate them deliberately (>0.3in).`,
          });
        }
      }
    }
  }

  /** 内容死区（whitespace 维度的几何近似）：内容整体挤在半幅以内时提醒。 */
  _checkDeadZone(boxes, warnings) {
    const { slideW } = this.options;
    const content = boxes.filter((x) => !isDecorative(x.el));
    if (!content.length) return;
    const minX = Math.min(...content.map((x) => x.box.x));
    const maxR = Math.max(...content.map((x) => x.box.r));
    const freeSide = Math.max(minX, slideW - maxR);
    const width = maxR - minX;
    if (freeSide > 2.2 && width < slideW * 0.7) {
      warnings.push({
        code: 'content_dead_zone',
        message: `Content spans only ${width.toFixed(2)}in while one side keeps ${freeSide.toFixed(2)}in empty: rebalance columns or widen the composition.`,
      });
    }
  }

  analyzeDeck() {
    const slides = [...this.slides.keys()]
      .sort((a, b) => a - b)
      .map((index) => this.analyzeSlide(index));
    const errors = slides.flatMap((s) => s.errors.map((e) => ({ slide: s.slideIndex, ...e })));
    const warnings = slides.flatMap((s) => s.warnings.map((e) => ({ slide: s.slideIndex, ...e })));
    return { ok: errors.length === 0, errors, warnings, slides };
  }

  assertSafe() {
    const report = this.analyzeDeck();
    if (!report.ok) {
      const summary = report.errors
        .map((e) => `slide ${e.slide}: ${e.code} (${e.element || `${e.a}/${e.b}`})`)
        .join('\n');
      throw new Error(`Actual slide geometry preflight failed:\n${summary}`);
    }
    return report;
  }

  /**
   * 把完整分析写进 `<pptx>.registry-report.json` sidecar。
   *
   * assertSafe 只在 error 上抛错；warning（decorative_stripe /
   * non_orthogonal_connector / content_dead_zone）以前被静默丢弃。
   * sidecar 让确定性 QA（pptx_rendered_check）把几何层面的美学提醒
   * 带进 repair packet，而不需要重新解析几何。
   */
  writeReport(outputPath) {
    const nodeFs = require('node:fs');
    const report = this.analyzeDeck();
    const payload = {
      pptx: String(outputPath),
      ok: report.ok,
      error_count: report.errors.length,
      warning_count: report.warnings.length,
      errors: report.errors,
      warnings: report.warnings,
      font_substitutions: [
        ...new Map(
          [...this.slides.values()]
            .flatMap((elements) =>
              elements.flatMap((element) => element._textLayout?.substitutions || []),
            )
            .map((item) => [item.requested, item]),
        ).values(),
      ],
      slides: report.slides.map((slide) => ({
        slide: slide.slideIndex,
        element_count: slide.elementCount,
        warnings: slide.warnings,
        contrast: slide.contrast,
        elements: this._slide(slide.slideIndex).map((element) =>
          Object.fromEntries(
            [
              'id',
              'type',
              'role',
              'text',
              'logicalGroup',
              'logicalText',
              'logicalBox',
              'x',
              'y',
              'w',
              'h',
              'fontSize',
              'fontFace',
              'lineGeometry',
              'decorative',
            ]
              .filter((key) => element[key] !== undefined)
              .map((key) => [key, element[key]]),
          ),
        ),
      })),
    };
    nodeFs.writeFileSync(
      `${outputPath}.registry-report.json`,
      `${JSON.stringify(payload, null, 2)}\n`,
      'utf8',
    );
    return payload;
  }
}

module.exports = {
  SlideElementRegistry,
  bboxOf,
  estimateTextFit,
};
