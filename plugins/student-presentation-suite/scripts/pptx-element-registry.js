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
  slideW: 13.333,
  slideH: 7.5,
  safeMargin: 0.12,
  overlapTolerance: 0.015,
  minTextW: 0.05,
  minTextH: 0.05,
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

function isDecorative(el) {
  return Boolean(el.decorative || el.allowOverlap || el.type === 'background');
}

function estimateTextFit(el) {
  const text = String(el.text || '');
  const fontSize = finite(el.fontSize) ? el.fontSize : 18;
  const box = bboxOf(el);
  if (!box || !text) return { ok: true, estimatedLines: 0, capacity: Infinity };

  const cjk = (text.match(/[\u3400-\u9fff\uf900-\ufaff]/g) || []).length;
  const latin = Math.max(0, text.length - cjk);
  // Conservative average character widths in inches at 72pt/in.
  const estimatedWidth = (cjk * fontSize * 0.92 + latin * fontSize * 0.52) / 72;
  const usableW = Math.max(DEFAULTS.minTextW, box.w - (el.paddingX || 0));
  const estimatedLines = Math.max(1, Math.ceil(estimatedWidth / usableW));
  const lineHeight = ((el.lineSpacing || 1.18) * fontSize) / 72;
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
  }

  _slide(index) {
    if (!this.slides.has(index)) this.slides.set(index, []);
    return this.slides.get(index);
  }

  register(slideIndex, element) {
    if (!Number.isInteger(slideIndex) || slideIndex < 1) throw new Error('slideIndex must be >= 1');
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

    for (const el of elements) {
      if (el.type === 'line') continue;
      const box = bboxOf(el);
      if (!box) {
        errors.push({ code: 'invalid_bbox', element: el.id, message: 'Element has invalid x/y/w/h.' });
        continue;
      }
      if (box.w <= 0 || box.h <= 0) {
        errors.push({ code: 'non_positive_size', element: el.id, message: 'Element width/height must be positive.' });
      }
      if (box.x < -safeMargin || box.y < -safeMargin || box.r > slideW + safeMargin || box.b > slideH + safeMargin) {
        errors.push({ code: 'out_of_canvas', element: el.id, bbox: box, message: 'Element exceeds slide canvas.' });
      }
      if (el.type === 'text') {
        const fit = estimateTextFit(el);
        if (!fit.ok) warnings.push({ code: 'text_may_overflow', element: el.id, ...fit });
      }
    }

    const boxes = elements.filter((el) => el.type !== 'line').map((el) => ({ el, box: bboxOf(el) })).filter((x) => x.box);
    for (let i = 0; i < boxes.length; i += 1) {
      for (let j = i + 1; j < boxes.length; j += 1) {
        const a = boxes[i];
        const b = boxes[j];
        if (isDecorative(a.el) || isDecorative(b.el)) continue;
        const area = overlapArea(a.box, b.box, this.options.overlapTolerance);
        if (area <= 0) continue;
        const minArea = Math.min(a.box.w * a.box.h, b.box.w * b.box.h);
        const ratio = minArea > 0 ? area / minArea : 0;
        const involvesText = a.el.type === 'text' || b.el.type === 'text';
        const issue = { code: involvesText ? 'text_overlap' : 'element_overlap', a: a.el.id, b: b.el.id, overlapRatio: ratio };
        if (involvesText && ratio > 0.04) errors.push(issue);
        else if (ratio > 0.12) warnings.push(issue);
      }
    }

    const textBoxes = boxes.filter((x) => x.el.type === 'text');
    for (const line of elements.filter((el) => el.type === 'line' && !el.allowTextCrossing)) {
      for (const text of textBoxes) {
        if (lineIntersectsBox(line, text.box)) {
          warnings.push({ code: 'line_crosses_text', line: line.id, text: text.el.id });
        }
      }
    }

    return { slideIndex, ok: errors.length === 0, errors, warnings, elementCount: elements.length };
  }

  analyzeDeck() {
    const slides = [...this.slides.keys()].sort((a, b) => a - b).map((index) => this.analyzeSlide(index));
    const errors = slides.flatMap((s) => s.errors.map((e) => ({ slide: s.slideIndex, ...e })));
    const warnings = slides.flatMap((s) => s.warnings.map((e) => ({ slide: s.slideIndex, ...e })));
    return { ok: errors.length === 0, errors, warnings, slides };
  }

  assertSafe() {
    const report = this.analyzeDeck();
    if (!report.ok) {
      const summary = report.errors.map((e) => `slide ${e.slide}: ${e.code} (${e.element || `${e.a}/${e.b}`})`).join('\n');
      throw new Error(`Actual slide geometry preflight failed:\n${summary}`);
    }
    return report;
  }
}

module.exports = {
  SlideElementRegistry,
  bboxOf,
  estimateTextFit,
};
