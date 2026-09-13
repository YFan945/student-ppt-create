'use strict';

const pptxgen = require('pptxgenjs');
const H = require('pptx-helpers');
const SHAPE = new pptxgen().ShapeType;

const SUPPORTED_SHAPES = Object.freeze([
  'rect',
  'roundRect',
  'ellipse',
  'pill',
  'hexagon',
  'chevron',
  'parallelogram',
  'arch',
  'bracket',
  'none',
]);

function normalizeShape(shape) {
  const value = String(shape || 'rect');
  if (!SUPPORTED_SHAPES.includes(value)) throw new RangeError(`Unsupported styled shape: ${value}`);
  return value;
}

function safeInsetForShape(shape, box) {
  const value = normalizeShape(shape);
  const unit = Math.min(Number(box.w), Number(box.h));
  const factors = {
    rect: [0.08, 0.08],
    roundRect: [0.09, 0.09],
    pill: [0.18, 0.12],
    ellipse: [0.2, 0.18],
    hexagon: [0.18, 0.08],
    chevron: [0.2, 0.08],
    parallelogram: [0.16, 0.1],
    arch: [0.16, 0.18],
    bracket: [0.12, 0.08],
    none: [0.04, 0.04],
  };
  const [xFactor, yFactor] = factors[value];
  return { x: unit * xFactor, y: unit * yFactor };
}

// ── 填充对比度保护 ────────────────────────────────────────
// 多数风格的 surface 是纯白而 canvas 是近白（F8FAFC / F7F4E9 …），
// 卡片与画布的亮度差极小，投影时卡片边界只剩 1.25pt 描边撑着，分组结构会消失。
// 这里在填充与画布对比度不足时，沿远离画布的方向微调填充。

function parseHex(value) {
  const hex = String(value || '').replace(/^#/, '');
  const full = hex.length === 3 ? hex.replace(/./g, (c) => c + c) : hex;
  if (!/^[0-9a-fA-F]{6}$/.test(full)) return null;
  return {
    r: parseInt(full.slice(0, 2), 16),
    g: parseInt(full.slice(2, 4), 16),
    b: parseInt(full.slice(4, 6), 16),
  };
}

function toHex(rgb) {
  const clamp = (n) => Math.max(0, Math.min(255, Math.round(Number(n) || 0)));
  return [rgb.r, rgb.g, rgb.b]
    .map((n) => clamp(n).toString(16).padStart(2, '0'))
    .join('')
    .toUpperCase();
}

function luminance(value) {
  const rgb = parseHex(value);
  if (!rgb) return null;
  const channel = (n) => {
    const c = n / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(rgb.r) + 0.7152 * channel(rgb.g) + 0.0722 * channel(rgb.b);
}

function contrastRatio(a, b) {
  const la = luminance(a);
  const lb = luminance(b);
  if (la === null || lb === null) return null;
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

function ensureFillContrast(fill, canvas, minRatio = 1.06) {
  const base = parseHex(fill);
  const canvasLum = luminance(canvas);
  if (!base || canvasLum === null) return fill;
  const target = canvasLum > 0.5 ? 0 : 255; // 浅画布上压暗卡片，深画布上提亮卡片
  let candidate = { ...base };
  for (let step = 1; step <= 10; step += 1) {
    const hex = toHex(candidate);
    const ratio = contrastRatio(hex, canvas);
    if (ratio === null || ratio >= minRatio) return hex;
    // 每步向目标方向固定移动 4%（不累进），避免一步跨过头把卡片压成脏灰。
    const delta = 0.04;
    candidate = {
      r: candidate.r + (target - candidate.r) * delta,
      g: candidate.g + (target - candidate.g) * delta,
      b: candidate.b + (target - candidate.b) * delta,
    };
  }
  return toHex(candidate);
}

/**
 * 生成单系列图表的逐点色阶。
 *
 * 单系列柱图若每个 series 只给一种颜色，所有柱子会同色，色彩不承载任何分类信息。
 * 这里以强调色为最重色，其余按"向画布方向递减"的淡化梯度生成，保证同族可区分；
 * highlightIndex 指定时该类目用满色（例如要突出"推荐方案"或"关键数值"）。
 * @param {string} base 强调色 hex
 * @param {string} canvas 画布色 hex（深色页上淡化即为压暗，符合深色场）
 * @param {number} count 数据点数量
 * @param {number} [highlightIndex] 需要用满色的点索引
 * @returns {string[]}
 */
function accentRamp(base, canvas, count, highlightIndex) {
  const total = Math.max(1, Math.floor(Number(count) || 1));
  const baseRgb = parseHex(base);
  const canvasRgb = parseHex(canvas);
  if (!baseRgb || !canvasRgb) return [base];
  const tints = [];
  for (let i = 0; i < total; i += 1) {
    const step = total === 1 ? 0 : i / (total - 1);
    const amount = 0.15 + step * 0.5;
    tints.push(
      toHex({
        r: baseRgb.r + (canvasRgb.r - baseRgb.r) * amount,
        g: baseRgb.g + (canvasRgb.g - baseRgb.g) * amount,
        b: baseRgb.b + (canvasRgb.b - baseRgb.b) * amount,
      }),
    );
  }
  const focus =
    Number.isInteger(highlightIndex) && highlightIndex >= 0 && highlightIndex < total
      ? highlightIndex
      : 0;
  tints[focus] = toHex(baseRgb);
  return tints;
}

function addStyledContainer(slide, shape, box, tokens, options = {}) {
  const value = normalizeShape(shape);
  if (value === 'none') return null;
  const palette = tokens.palette || {};
  const fill = ensureFillContrast(
    options.fill || palette.surface || 'FFFFFF',
    palette.canvas || 'FFFFFF',
  );
  const line = options.line || palette.primary_accent || '2563EB';
  if (value === 'bracket') {
    const width = Math.max(1, Number(options.lineWidth || 1.5));
    const arm = Math.min(box.w * 0.14, 0.2);
    slide.addShape(SHAPE.line, {
      x: box.x,
      y: box.y,
      w: 0,
      h: box.h,
      line: { color: line, width },
    });
    slide.addShape(SHAPE.line, { x: box.x, y: box.y, w: arm, h: 0, line: { color: line, width } });
    slide.addShape(SHAPE.line, {
      x: box.x,
      y: box.y + box.h,
      w: arm,
      h: 0,
      line: { color: line, width },
    });
    return null;
  }
  const mapped = value === 'pill' ? SHAPE.roundRect : value === 'arch' ? SHAPE.arc : SHAPE[value];
  const shapeOptions = {
    ...box,
    fill: { color: fill, transparency: Number(options.fillTransparency || 0) },
    line: {
      color: line,
      width: Number(options.lineWidth || 1.25),
      transparency: Number(options.lineTransparency || 0),
    },
  };
  // 浅色页面板默认带 soft shadow（dark 页 softShadow 返回 null 自动跳过）；
  // options.shadow === false 可显式关闭，传对象则作为 overrides。
  const shadow = H.softShadow(
    tokens,
    options.shadow === false ? { enabled: false } : options.shadow || {},
  );
  if (shadow) shapeOptions.shadow = shadow;
  if (value === 'pill') shapeOptions.radius = Math.min(box.w, box.h) / 2;
  if (value === 'arch') shapeOptions.adjustPoint = 0.25;
  return slide.addShape(mapped, shapeOptions);
}

module.exports = {
  SUPPORTED_SHAPES,
  normalizeShape,
  safeInsetForShape,
  addStyledContainer,
  ensureFillContrast,
  accentRamp,
};
