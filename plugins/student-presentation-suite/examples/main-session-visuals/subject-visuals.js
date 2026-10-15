'use strict';

// Small auxiliary glyphs, not a default visual system or a content illustration.
function subjectIcon(ctx, kind, box, color) {
  const { slide } = ctx;
  const { x, y, w, h } = box;
  (ctx.visualUsage ||= []).push({
    kind: 'icon',
    key: `example:subject:${kind}`,
    box: { x, y, w, h },
  });
  const line = { color, width: 1.5 };
  const shape = (type, opts) => slide.addShape(type, { decorative: true, ...opts });
  const stroke = (x1, y1, x2, y2) =>
    shape('line', {
      x: Math.min(x1, x2),
      y: Math.min(y1, y2),
      w: Math.abs(x2 - x1),
      h: Math.abs(y2 - y1),
      flipH: x2 < x1,
      flipV: y2 < y1,
      line,
    });
  const person = (cx, top, scale) => {
    shape('ellipse', {
      x: cx - scale / 2,
      y: top,
      w: scale,
      h: scale,
      fill: { color },
      line: { type: 'none' },
    });
    shape('rect', {
      x: cx - scale * 0.65,
      y: top + scale * 1.2,
      w: scale * 1.3,
      h: scale * 1.6,
      fill: { color },
      line: { type: 'none' },
    });
  };
  if (kind === 'information') {
    shape('rect', {
      x: x + w * 0.18,
      y: y + h * 0.08,
      w: w * 0.64,
      h: h * 0.84,
      fill: { color: 'FFFFFF', transparency: 100 },
      line,
    });
    for (const dy of [0.3, 0.48, 0.66]) stroke(x + w * 0.3, y + h * dy, x + w * 0.7, y + h * dy);
  } else if (kind === 'matching') {
    person(x + w * 0.22, y + h * 0.14, Math.min(w, h) * 0.16);
    person(x + w * 0.78, y + h * 0.14, Math.min(w, h) * 0.16);
    stroke(x + w * 0.39, y + h * 0.58, x + w * 0.61, y + h * 0.58);
  } else if (kind === 'practice') {
    shape('rect', {
      x: x + w * 0.15,
      y: y + h * 0.18,
      w: w * 0.7,
      h: h * 0.6,
      fill: { color: 'FFFFFF', transparency: 100 },
      line,
    });
    stroke(x + w * 0.3, y + h * 0.48, x + w * 0.44, y + h * 0.63);
    stroke(x + w * 0.44, y + h * 0.63, x + w * 0.72, y + h * 0.32);
  } else if (kind === 'feedback') {
    shape('rect', {
      x: x + w * 0.1,
      y: y + h * 0.16,
      w: w * 0.8,
      h: h * 0.6,
      fill: { color: 'FFFFFF', transparency: 100 },
      line,
    });
    stroke(x + w * 0.26, y + h * 0.76, x + w * 0.26, y + h * 0.95);
    stroke(x + w * 0.26, y + h * 0.95, x + w * 0.45, y + h * 0.76);
    for (const dx of [0.3, 0.5, 0.7])
      shape('ellipse', {
        x: x + w * dx - 0.025,
        y: y + h * 0.45,
        w: 0.05,
        h: 0.05,
        fill: { color },
        line: { type: 'none' },
      });
  } else {
    throw new RangeError(`Unknown subject icon: ${kind}`);
  }
}

module.exports = { subjectIcon };
