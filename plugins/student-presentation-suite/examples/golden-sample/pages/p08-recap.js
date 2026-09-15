'use strict';
/** Golden sample slide 8 — recap */
module.exports = function (ctx) {
  const {
    page,
    text,
    hrule,
    footer,
    pageTitle,
    H,
    DOT,
    M,
    CW,
    CONTENT_TOP,
    muted,
    accent,
  } = ctx;
  const { slide, tokens } = page('light');
  pageTitle(slide, tokens, '回顾', '回到这条推理链');

  const steps = ['幻觉源于优化目标', '流畅不等于忠实', '先取证，再回答'];
  const cellW = (CW - 0.6) / 3;
  const spineY = CONTENT_TOP + 0.8;

  hrule(slide, M + cellW / 2, spineY, CW - cellW, accent(tokens), 1.25);

  steps.forEach((label, index) => {
    const x = M + index * (cellW + 0.3);
    const cx = x + cellW / 2;
    const last = index === steps.length - 1;
    const radius = last ? 0.3 : 0.22;
    slide.addShape(DOT, {
      x: cx - radius,
      y: spineY - radius,
      w: radius * 2,
      h: radius * 2,
      fill: { color: last ? accent(tokens) : H.color(tokens, 'canvas') },
      line: { color: accent(tokens), width: last ? 0 : 1.5 },
    });
    text(
      slide,
      String(index + 1),
      { x: cx - radius, y: spineY - radius, w: radius * 2, h: radius * 2 },
      tokens,
      'caption',
      {
        margin: 0,
        fontSize: last ? 15 : 13,
        align: 'center',
        valign: 'mid',
        colorRole: last ? 'canvas' : 'primary_accent',
        label: `步骤 ${index + 1} 序号`,
      },
    );
    text(slide, label, { x, y: spineY + 0.46, w: cellW, h: 0.78 }, tokens, 'caption', {
      margin: 0,
      fontSize: last ? 17 : 14,
      align: 'center',
      colorRole: last ? 'primary_accent' : 'primary_text',
      label: `步骤 ${index + 1} 说明`,
    });
  });

  hrule(slide, M, CONTENT_TOP + 2.42, CW, muted(tokens), 0.75);
  text(
    slide,
    '这三步是有先后的推理链，不是三个并列要点。',
    { x: M, y: CONTENT_TOP + 2.54, w: CW, h: 0.3 },
    tokens,
    'caption',
    { margin: 0, fontSize: 11, colorRole: 'secondary_text', label: '回顾提示' },
  );
  footer(slide, tokens, 'AI 幻觉 · 课程汇报', '08 / 09');
};
