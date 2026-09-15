'use strict';
/** Golden sample slide 2 — hook */
module.exports = function (ctx) {
  const { page, text, title, rect, vrule, footer, pageTitle, ROUND, M, CW, CONTENT_TOP, accent } =
    ctx;
  const { slide, tokens } = page('light');
  pageTitle(slide, tokens, '问题', '为什么一个模型能立刻给出流畅的答案？');

  title(
    slide,
    ['因为它先学会的是', '预测下一个最可能的词，', '而不是先查证事实。'],
    { x: M, y: CONTENT_TOP + 0.16, w: CW * 0.6 },
    tokens,
    26,
    { label: '核心命题', accentLines: [1] },
  );

  const chipX = M + CW * 0.66;
  const chipW = CW * 0.34;
  text(
    slide,
    '两条判断',
    { x: chipX, y: CONTENT_TOP + 0.1, w: chipW, h: 0.26 },
    tokens,
    'caption',
    { margin: 0, colorRole: 'secondary_text', label: '小标题' },
  );
  ['流畅 ≠ 正确', '自信 ≠ 有据'].forEach((label, index) => {
    const y = CONTENT_TOP + 0.46 + index * 0.78;
    rect(slide, { x: chipX, y, w: chipW, h: 0.62 }, accent(tokens), 90, ROUND);
    vrule(slide, chipX, y, 0.62, accent(tokens), 2.5);
    text(
      slide,
      label,
      { x: chipX + 0.24, y: y + 0.1, w: chipW - 0.4, h: 0.42 },
      tokens,
      'caption',
      { margin: 0, fontSize: 15, colorRole: 'primary_accent', label: '判断要点' },
    );
  });
  text(
    slide,
    '后面每个结论都会回到它',
    { x: chipX, y: CONTENT_TOP + 2.14, w: chipW, h: 0.26 },
    tokens,
    'caption',
    { margin: 0, fontSize: 11, colorRole: 'secondary_text', label: '提示' },
  );
  footer(slide, tokens, 'AI 幻觉 · 课程汇报', '02 / 09');
};
