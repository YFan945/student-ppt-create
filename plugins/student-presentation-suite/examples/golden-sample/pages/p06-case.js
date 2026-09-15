'use strict';
/** Golden sample slide 6 — case */
module.exports = function (ctx) {
  const { page, text, rect, hrule, vrule, footer, pageTitle, H, M, CW, CONTENT_TOP, muted, accent } =
    ctx;
  const { slide, tokens } = page('light');
  pageTitle(slide, tokens, '案例', '案例：一条检索不到的「文献」');

  const left = { x: M, y: CONTENT_TOP, w: CW * 0.58, h: 2.62 };
  rect(slide, left, H.color(tokens, 'surface'));
  hrule(slide, left.x, left.y, left.w, muted(tokens), 0.75);
  vrule(slide, left.x, left.y, 0.9, accent(tokens), 3);
  text(
    slide,
    '模型给出的引用 · 格式自洽，却检索不到',
    { x: left.x + 0.36, y: left.y + 0.26, w: left.w - 0.66, h: 0.3 },
    tokens,
    'caption',
    { margin: 0, fontSize: 12, colorRole: 'primary_accent', label: '证据标题' },
  );
  text(
    slide,
    'Wang, L., & Chen, R. (2021).\nFaithfulness in Neural\nSummarization. Journal of\nLanguage Modelling, 12(3),\n245-263.',
    { x: left.x + 0.36, y: left.y + 0.72, w: left.w - 0.66, h: 1.7 },
    tokens,
    'caption',
    { min: 12, max: 14, margin: 0, align: 'left', colorRole: 'primary_text', label: '示例引用' },
  );

  const rightX = M + CW * 0.64;
  const rightW = CW * 0.36;
  const rowH = 0.78;
  ['作者与年份格式自洽', '期刊名真实存在', '组合后检索不到'].forEach((label, index) => {
    const y = CONTENT_TOP + index * (rowH + 0.14);
    vrule(slide, rightX, y + 0.1, 0.44, accent(tokens), 2.5);
    text(slide, label, { x: rightX + 0.28, y, w: rightW - 0.28, h: 0.64 }, tokens, 'caption', {
      margin: 0,
      fontSize: 15,
      colorRole: 'primary_text',
      label: `标注 ${index + 1}`,
    });
    if (index < 2) {
      hrule(slide, rightX, y + rowH + 0.06, rightW, muted(tokens), 0.75);
    }
  });
  footer(slide, tokens, 'AI 幻觉 · 课程汇报', '06 / 09');
};
