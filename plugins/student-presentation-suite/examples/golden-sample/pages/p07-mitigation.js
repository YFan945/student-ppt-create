'use strict';
/** Golden sample slide 7 — mitigation */
module.exports = function (ctx) {
  const {
    page,
    text,
    title,
    rect,
    hrule,
    vrule,
    footer,
    pageTitle,
    ROUND,
    M,
    CW,
    CONTENT_TOP,
    muted,
    accent,
  } = ctx;
  const { slide, tokens } = page('light');
  pageTitle(slide, tokens, '对策', '降低幻觉：先取证，再回答');

  const preferred = { x: M, y: CONTENT_TOP, w: CW * 0.6, h: 2.6 };
  rect(slide, preferred, accent(tokens), 88, ROUND);
  vrule(slide, preferred.x, preferred.y, preferred.h, accent(tokens), 3);
  text(
    slide,
    '推荐',
    { x: preferred.x + 0.36, y: preferred.y + 0.22, w: 1.2, h: 0.26 },
    tokens,
    'caption',
    { margin: 0, fontSize: 12, colorRole: 'primary_accent', label: '推荐标记' },
  );
  title(
    slide,
    ['先检索再回答（RAG）'],
    { x: preferred.x + 0.36, y: preferred.y + 0.56, w: preferred.w - 0.72 },
    tokens,
    24,
    { label: '首选方案' },
  );
  text(
    slide,
    '引用可核验，补足知识边界\n把查证写进流程',
    { x: preferred.x + 0.36, y: preferred.y + 1.3, w: preferred.w - 0.72, h: 1.16 },
    tokens,
    'body',
    { margin: 0, align: 'left', bullet: false, label: '首选理由' },
  );

  const alt = { x: M + CW * 0.66, y: CONTENT_TOP + 0.34, w: CW * 0.34, h: 2.0 };
  hrule(slide, alt.x, alt.y, alt.w, muted(tokens), 0.75);
  text(
    slide,
    '仅提示「不要编」',
    { x: alt.x, y: alt.y + 0.26, w: alt.w, h: 0.6 },
    tokens,
    'caption',
    { margin: 0, fontSize: 15, colorRole: 'primary_text', label: '对照方案' },
  );
  text(
    slide,
    '零成本，但效果不稳定。',
    { x: alt.x, y: alt.y + 0.94, w: alt.w, h: 1.0 },
    tokens,
    'caption',
    { margin: 0, fontSize: 12, colorRole: 'secondary_text', label: '对照说明' },
  );
  footer(slide, tokens, 'AI 幻觉 · 课程汇报', '07 / 09');
};
