'use strict';
/** Golden sample slide 3 — section */
module.exports = function (ctx) {
  const { page, text, title, rect, hrule, footer, NAVY, S_W, S_H, M, CW, accent } = ctx;
  const { slide, tokens } = page('dark');
  rect(slide, { x: 0, y: 0, w: S_W, h: S_H }, NAVY);

  text(slide, '01', { x: M, y: 1.66, w: 2.2, h: 1.66 }, tokens, 'title', {
    min: 64,
    max: 64,
    bold: true,
    margin: 0,
    colorRole: 'primary_accent',
    label: '章节序号',
  });
  title(slide, ['幻觉不是偶发 bug'], { x: M + 2.1, y: 1.96, w: CW - 2.1 }, tokens, 32, {
    label: '章节标题',
  });
  hrule(slide, M + 2.1, 2.86, 1.2, accent(tokens), 3);
  text(
    slide,
    '从训练目标进入：它优化的是「像」，不是「真」',
    { x: M + 2.1, y: 3.06, w: CW - 2.1, h: 0.36 },
    tokens,
    'caption',
    { margin: 0, fontSize: 13, colorRole: 'secondary_text', label: '章节引导' },
  );
  // 章节页此前是整份 deck 唯一没有页脚的页面：内容只占页面高度 31%，
  // 底部留白高达 39%，深色场上显得悬空；且它不计数导致后续页码整体错位。
  footer(slide, tokens, 'AI 幻觉 · 课程汇报', '03 / 09');
};
