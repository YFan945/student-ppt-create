'use strict';
/** Golden sample slide 4 — mechanism */
module.exports = function (ctx) {
  const {
    page,
    text,
    rect,
    hrule,
    footer,
    pageTitle,
    TOKENS,
    H,
    LINE,
    NAVY,
    ROUND,
    S_W,
    M,
    CW,
    CONTENT_TOP,
    muted,
  } = ctx;
  const { slide, tokens } = page('light');
  const dark = H.paletteMode(TOKENS, 'dark');
  pageTitle(slide, tokens, '机制', '三类因素在放大「合理但未核实」');

  const causes = ['训练目标：最大化似然', '数据噪声：真假混杂', '知识边界：不知道就猜'];
  const cellW = (CW - 0.5) / 3;
  const topY = CONTENT_TOP + 0.24;
  causes.forEach((label, index) => {
    const x = M + index * (cellW + 0.25);
    hrule(slide, x, topY, cellW * 0.45, H.color(tokens, 'primary_accent'), 2);
    text(slide, label, { x, y: topY + 0.16, w: cellW, h: 0.5 }, tokens, 'caption', {
      margin: 0,
      fontSize: 14,
      colorRole: 'primary_text',
      label: `因素 ${index + 1}`,
    });
  });

  // Connectors converge into the dominant conclusion panel.
  const mergeX = S_W / 2;
  const mergeY = topY + 0.9;
  causes.forEach((_, index) => {
    const x = M + index * (cellW + 0.25) + cellW / 2;
    slide.addShape(LINE, {
      x: Math.min(x, mergeX),
      y: topY + 0.72,
      w: Math.abs(mergeX - x),
      h: mergeY - (topY + 0.72),
      line: { color: muted(tokens), width: 1.25 },
    });
  });

  const panel = { x: M, y: mergeY + 0.12, w: CW, h: 1.56 };
  rect(slide, panel, NAVY, 0, ROUND);
  text(
    slide,
    '都在放大同一种失败模式：\n输出「合理但未核实」',
    { x: panel.x + 0.44, y: panel.y + 0.3, w: panel.w - 0.88, h: 1.14 },
    dark,
    'quote',
    { min: 22, max: 24, margin: 0, bold: true, align: 'left', label: '共同结果' },
  );
  footer(slide, tokens, 'AI 幻觉 · 课程汇报', '04 / 09');
};
