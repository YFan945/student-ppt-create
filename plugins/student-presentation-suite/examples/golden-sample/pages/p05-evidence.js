'use strict';
/** Golden sample slide 5 — evidence */
module.exports = function (ctx) {
  const {
    pptx,
    page,
    text,
    hrule,
    footer,
    pageTitle,
    H,
    F,
    M,
    CW,
    CONTENT_TOP,
    ink,
    muted,
    accent,
  } = ctx;
  const { slide, tokens } = page('light');
  pageTitle(slide, tokens, '证据', '示意数据：流畅的摘要有多少不忠实');

  text(slide, '≈30', { x: M, y: CONTENT_TOP + 0.22, w: 2.7, h: 1.42 }, tokens, 'title', {
    min: 58,
    max: 58,
    bold: true,
    margin: 0,
    colorRole: 'primary_accent',
    label: '关键数字',
  });
  text(
    slide,
    '约三成摘要与原文不一致',
    { x: M, y: CONTENT_TOP + 1.78, w: 2.9, h: 0.34 },
    tokens,
    'caption',
    { margin: 0, fontSize: 13, colorRole: 'primary_text', label: '数字说明' },
  );
  hrule(slide, M, CONTENT_TOP + 2.24, 2.4, accent(tokens), 2.5);

  slide.addChart(
    pptx.ChartType.bar,
    [{ name: '占比', labels: ['完全忠实', '部分不忠实', '明显不忠实'], values: [68, 22, 10] }],
    {
      x: M + CW * 0.4,
      y: CONTENT_TOP + 0.04,
      w: CW * 0.6,
      h: 2.5,
      barDir: 'col',
      chartColors: [accent(tokens)],
      showTitle: false,
      showLegend: false,
      showValue: true,
      dataLabelPosition: 'outEnd',
      dataLabelFontFace: F.body,
      dataLabelFontSize: 18,
      dataLabelColor: ink(tokens),
      catAxisLabelFontFace: F.body,
      catAxisLabelFontSize: 13,
      catAxisLabelColor: muted(tokens),
      catAxisLineShow: false,
      valAxisHidden: true,
      // 轴即使隐藏，柱高比例仍由轴范围决定；渲染回读门禁要求显式 min/max，
      // 禁止自动缩放把 68/84/89 这类差异抹平。
      valAxisMaxVal: 80,
      valAxisMinVal: 0,
      valAxisMajorUnit: 20,
      valGridLine: { style: 'none' },
      catGridLine: { style: 'none' },
      border: { pt: 0, color: H.color(tokens, 'canvas') },
      barGapWidthPct: 110,
      altText: '示意柱状图：完全忠实 68、部分不忠实 22、明显不忠实 10',
    },
  );

  text(
    slide,
    '示意数据，非已发表统计；用于演示「结论先于图表」的读法。',
    { x: M, y: CONTENT_TOP + 2.56, w: CW, h: 0.3 },
    tokens,
    'caption',
    { margin: 0, fontSize: 11, colorRole: 'secondary_text', label: '来源说明' },
  );
  footer(slide, tokens, 'AI 幻觉 · 课程汇报', '05 / 09');
};
