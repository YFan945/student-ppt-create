'use strict';
/** Golden sample slide 1 — cover */
module.exports = function (ctx) {
  const { page, text, title, rect, hrule, footer, NAVY, ROUND, S_W, S_H, M, accent } = ctx;
  const { slide, tokens } = page('dark');
  rect(slide, { x: 0, y: 0, w: S_W, h: S_H }, NAVY);

  // Echo motif: fluent repetition fading out, one unverified claim standing out.
  const bars = [
    { w: 3.0, t: 84 },
    { w: 2.55, t: 76 },
    { w: 2.1, t: 66 },
    { w: 1.65, t: 52 },
    { w: 1.2, t: 0 },
  ];
  const barH = 0.26;
  const step = 0.44;
  const bx = 5.0;
  const by = 1.38;
  bars.forEach((bar, index) => {
    rect(slide, { x: bx, y: by + index * step, w: bar.w, h: barH }, accent(tokens), bar.t, ROUND);
  });
  text(
    slide,
    '重复生成\n≠\n已核实',
    { x: bx - 0.04, y: by + bars.length * step + 0.14, w: 3.4, h: 1.0 },
    tokens,
    'caption',
    { margin: 0, fontSize: 12, colorRole: 'secondary_text', label: '母题注释' },
  );

  text(slide, '课堂汇报 · 人工智能导论', { x: M, y: 1.0, w: 4.3, h: 0.26 }, tokens, 'caption', {
    margin: 0,
    colorRole: 'primary_accent',
    label: '封面眉标',
  });
  title(slide, ['AI 会「编」，', '而且编得很自信'], { x: M, y: 1.4, w: 4.7 }, tokens, 40, {
    label: '封面标题',
    accentLines: [1],
  });
  hrule(slide, M, 3.5, 1.4, accent(tokens), 3);
  text(
    slide,
    '从语言模型的训练目标理解「幻觉」',
    { x: M, y: 3.7, w: 4.5, h: 0.34 },
    tokens,
    'caption',
    { margin: 0, fontSize: 13, colorRole: 'secondary_text', label: '封面副标题' },
  );
  footer(slide, tokens, 'AI 幻觉 · 课程汇报', '01 / 09');
};
