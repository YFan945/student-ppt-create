'use strict';
/** Golden sample slide 9 — closing */
module.exports = function (ctx) {
  const { page, text, title, rect, hrule, footer, H, NAVY, S_W, S_H, M, CW, accent } = ctx;
  const { slide, tokens } = page('dark');
  rect(slide, { x: 0, y: 0, w: S_W, h: S_H }, NAVY);
  rect(slide, { x: M, y: 1.0, w: 1.4, h: 0.06 }, accent(tokens));

  title(slide, ['流畅是能力，', '忠实是选择。'], { x: M, y: 1.36, w: CW * 0.9 }, tokens, 38, {
    label: '结语',
    accentLines: [1],
  });
  text(
    slide,
    '把「查证」放进流程，而不是指望模型自觉。',
    { x: M, y: 3.24, w: CW * 0.8, h: 0.34 },
    tokens,
    'caption',
    { margin: 0, fontSize: 13, colorRole: 'secondary_text', label: '结语补充' },
  );

  hrule(slide, M, 3.86, CW, H.color(tokens, 'secondary_accent'), 0.75);
  text(
    slide,
    '参考：Ji et al., Survey of Hallucination in Natural Language Generation, ACM Computing Surveys, 2023；本汇报作者，课堂示意数据（2026，非已发表统计）。',
    { x: M, y: 3.96, w: CW, h: 0.92 },
    tokens,
    'caption',
    { margin: 0, fontSize: 11, colorRole: 'secondary_text', label: '参考来源' },
  );
  footer(slide, tokens, '谢谢 · Q&A', '09 / 09');
};
