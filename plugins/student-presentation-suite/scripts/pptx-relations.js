'use strict';

// Optional information relationships. The author supplies content, region and
// type size; these functions never choose a deck layout or invent data.
function text(ctx, value, box, options) {
  if (!Number.isFinite(options.fontSize) || options.fontSize <= 0)
    throw new RangeError('Relationship text requires an author-selected fontSize');
  return ctx.H.addFittedText(ctx.slide, value, box, ctx.tokens, 'chinese', 'body', {
    margin: 0,
    color: ctx.tokens.palette.primary_text,
    ...options,
  });
}

function rule(ctx, x, y, w, color) {
  ctx.slide.addShape('line', { x, y, w, h: 0, line: { color, width: 0.7 } });
}

function metric(ctx, fact, box, options) {
  if (!fact.label || !fact.value) throw new Error('metric needs a label and exact string value');
  const quantity = String(fact.value) + (fact.unit || '');
  const runs = [
    { text: `${fact.label}\n`, options: { fontSize: options.labelSize || options.fontSize } },
    {
      text: quantity,
      options: {
        fontSize: options.fontSize,
        bold: true,
        color: options.color || ctx.tokens.palette.primary_accent,
      },
    },
  ];
  if (fact.context)
    runs.push({
      text: `\n${fact.context}`,
      options: { fontSize: options.labelSize || options.fontSize },
    });
  // One real rich-text object binds label and quantity, even when visually
  // separated by line breaks. Keep editable type and exact readback together.
  return text(ctx, runs, box, { ...options, positionMixedText: false });
}

function evidenceRows(ctx, rows, box, options) {
  if (!rows.length) throw new Error('evidenceRows needs supported evidence rows');
  const gap = options.rowGap ?? options.gap ?? 0.16;
  const labelWidth = options.labelWidth ?? box.w * 0.24;
  const height = box.h / rows.length;
  const color = options.ruleColor || ctx.tokens.palette.secondary_accent;
  rows.forEach((row, index) => {
    const y = box.y + index * height;
    text(
      ctx,
      row.label,
      { x: box.x, y, w: labelWidth, h: height - gap },
      { ...options, bold: true },
    );
    text(
      ctx,
      row.detail,
      { x: box.x + labelWidth + gap, y, w: box.w - labelWidth - gap, h: height - gap },
      options,
    );
    if (index < rows.length - 1) rule(ctx, box.x, y + height - gap / 2, box.w, color);
  });
}

function processSteps(ctx, steps, box, options) {
  if (!steps.length) throw new Error('processSteps needs actual steps');
  const gap = options.gap ?? 0.28;
  const width = (box.w - gap * (steps.length - 1)) / steps.length;
  const titleHeight = options.titleHeight ?? box.h * 0.2;
  const color = options.color || ctx.tokens.palette.primary_accent;
  steps.forEach((step, index) => {
    const x = box.x + index * (width + gap);
    text(
      ctx,
      step.title,
      { x, y: box.y, w: width, h: titleHeight },
      { ...options, bold: true, color },
    );
    evidenceRows(
      ctx,
      step.rows,
      { x, y: box.y + titleHeight, w: width, h: box.h - titleHeight },
      {
        ...options,
        rowGap: options.rowGap ?? 0.12,
        labelWidth: options.labelWidth ?? width * 0.23,
      },
    );
    if (index < steps.length - 1)
      ctx.slide.addShape('line', {
        x: x + width + 0.02,
        y: box.y + titleHeight / 2,
        w: gap - 0.04,
        h: 0,
        line: { color, width: 1.3, endArrowType: 'triangle' },
      });
  });
}

function annotatedImage(ctx, asset, marks, box, options) {
  ctx.H.addPlannedImage(ctx.slide, asset, box, ctx.pptx);
  marks.forEach((mark, index) => {
    if (![mark.x, mark.y].every((value) => Number.isFinite(value) && value >= 0 && value <= 1))
      throw new RangeError('Annotation coordinates are normalized to the visible image region');
    // Use only on an image region whose aspect ratio matches the supplied
    // asset. Otherwise letterboxing changes anchor positions.
    if (Math.abs(box.w / box.h - asset.width / asset.height) > 0.02)
      throw new RangeError('Annotated image box must preserve the asset aspect ratio');
    const size = options.markerSize ?? 0.24;
    const x = box.x + mark.x * box.w - size / 2;
    const y = box.y + mark.y * box.h - size / 2;
    ctx.slide.addShape('ellipse', {
      x,
      y,
      w: size,
      h: size,
      fill: { color: options.color || ctx.tokens.palette.primary_accent },
      line: { color: 'FFFFFF', width: 1 },
    });
    text(
      ctx,
      String(index + 1),
      { x, y: y + size * 0.1, w: size, h: size * 0.8 },
      { fontSize: options.markerFontSize, color: 'FFFFFF', align: 'center', bold: true },
    );
  });
}

module.exports = { metric, evidenceRows, processSteps, annotatedImage };
