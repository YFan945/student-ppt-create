'use strict';

// Same synthetic facts on both versions. These are complete inspectable
// examples, never default page recipes. Render through render_visual_cases.py.
const V = require('../../scripts/pptx-relations.js');
const facts = {
  mechanism: [
    [
      '材料分段',
      '输入',
      '原始影像、语音和文本',
      '处理',
      '按材料边界分段',
      '保留',
      '原始边界与索引',
    ],
    [
      '特征表示',
      '输入',
      '已分段的材料',
      '处理',
      '形成对应的特征标签',
      '保留',
      '标签与原片段的对应',
    ],
    [
      '关系连接',
      '输入',
      '对象、事件与来源标签',
      '处理',
      '关联人物、地点和主题',
      '保留',
      '关系依据与原件入口',
    ],
  ],
  data: [
    ['方案A', '64'],
    ['方案B', '78'],
    ['方案C', '81'],
  ],
  evidence: [
    { label: '来源入口', detail: '每条记录保留来源路径，支持回到原始材料。' },
    { label: '版本信息', detail: '版本与更新时间并列，便于核对所用材料。' },
    { label: '关系标签', detail: '人物、地点和主题标签提供跨记录浏览入口。' },
  ],
};
function t(ctx, value, x, y, w, h, size, extra = {}) {
  ctx.H.addFittedText(ctx.slide, value, { x, y, w, h }, ctx.tokens, 'chinese', 'body', {
    fontSize: size,
    margin: 0,
    color: ctx.tokens.palette.primary_text,
    ...extra,
  });
}
function base(ctx, title, label) {
  ctx.slide.background = { color: 'F5F7FB' };
  t(ctx, title, 0.48, 0.35, 9.0, 0.62, 27, { bold: true });
  t(ctx, '合成教学案例 · ' + label, 0.5, 5.13, 9, 0.25, 10, { color: '526074' });
}
function panel(ctx, x, y, w, h, color = 'FFFFFF') {
  ctx.slide.addShape('rect', {
    x,
    y,
    w,
    h,
    fill: { color },
    line: { color: 'D8DFE9', width: 0.5 },
  });
}
function mechanismBefore(ctx) {
  base(ctx, '从原始材料到可追溯关系', '机制 / 改前');
  facts.mechanism.forEach((row, index) => {
    const x = 0.5 + index * 3.08;
    panel(ctx, x, 1.35, 2.9, 3.25);
    t(ctx, row[0], x + 0.18, 1.62, 2.54, 0.5, 20, { bold: true });
    t(
      ctx,
      `${row[1]}：${row[2]}\n${row[3]}：${row[4]}\n${row[5]}：${row[6]}`,
      x + 0.18,
      2.28,
      2.5,
      2.1,
      16,
    );
  });
}
function mechanismAfter(ctx) {
  base(ctx, '材料经过三步处理，保留可回溯的依据', '机制 / 改后');
  panel(ctx, 0.48, 1.3, 9.04, 3.44);
  V.processSteps(
    ctx,
    facts.mechanism.map((row) => ({
      title: row[0],
      rows: [
        { label: row[1], detail: row[2] },
        { label: row[3], detail: row[4] },
        { label: row[5], detail: row[6] },
      ],
    })),
    { x: 0.68, y: 1.57, w: 8.64, h: 2.9 },
    { fontSize: 14, titleHeight: 0.65, labelWidth: 0.45, gap: 0.3 },
  );
}
function dataBefore(ctx) {
  base(ctx, '三种方案在同一测试集上的表现', '数据 / 改前');
  facts.data.forEach(([label, value], index) => {
    const x = 0.5 + index * 3.08;
    panel(ctx, x, 1.5, 2.9, 2.35);
    V.metric(
      ctx,
      { label, value, unit: '%' },
      { x: x + 0.22, y: 1.85, w: 2.4, h: 1.6 },
      { fontSize: 32, labelSize: 18 },
    );
  });
  t(
    ctx,
    '测试条件相同；每种方案评测100个合成样本。\n方案C比方案A高17个百分点；本例不说明差异原因。',
    0.6,
    4.2,
    8.8,
    0.7,
    15,
  );
}
function dataAfter(ctx) {
  base(ctx, '同条件测试中，方案C比方案A高17个百分点', '数据 / 改后');
  panel(ctx, 0.5, 1.3, 5.7, 3.5);
  ctx.slide.addChart(
    ctx.pptx.ChartType.bar,
    [
      {
        name: '准确率',
        labels: facts.data.map((item) => item[0]),
        values: facts.data.map((item) => Number(item[1])),
      },
    ],
    {
      x: 0.7,
      y: 1.48,
      w: 5.26,
      h: 2.95,
      barDir: 'col',
      catAxisLabelFontSize: 13,
      valAxisLabelFontSize: 11,
      valAxisMinVal: 0,
      valAxisMaxVal: 100,
      valAxisMajorUnit: 20,
      showLegend: false,
      showValue: true,
      dataLabelPosition: 'outEnd',
      dataLabelFormatCode: '0"%"',
      chartColors: ['2363A0'],
      showTitle: false,
    },
  );
  V.evidenceRows(
    ctx,
    [
      { label: '同条件', detail: '每种方案评测100个合成样本，使用同一测试集。' },
      { label: '差异', detail: '方案A为64%，方案B为78%，方案C为81%。' },
      { label: '解释范围', detail: 'C比A高17个百分点；本例不说明差异原因。' },
    ],
    { x: 6.5, y: 1.6, w: 3.0, h: 2.9 },
    { fontSize: 14, labelWidth: 0.7, gap: 0.16 },
  );
}
function evidenceBefore(ctx) {
  base(ctx, '资料记录需要三个浏览入口', '图像证据 / 改前');
  ctx.H.addPlannedImage(ctx.slide, ctx.exampleAsset, { x: 0.5, y: 1.5, w: 3.0, h: 2.0 }, ctx.pptx);
  V.evidenceRows(
    ctx,
    facts.evidence,
    { x: 3.9, y: 1.45, w: 5.55, h: 3.2 },
    { fontSize: 18, labelWidth: 1.1, gap: 0.16 },
  );
}
function evidenceAfter(ctx) {
  base(ctx, '原件、版本与标签共同支持资料回看', '图像证据 / 改后');
  V.annotatedImage(
    ctx,
    ctx.exampleAsset,
    [
      { x: 0.94, y: 0.31 },
      { x: 0.94, y: 0.47 },
      { x: 0.9, y: 0.73 },
    ],
    { x: 0.5, y: 1.35, w: 5.4, h: 3.6 },
    { markerSize: 0.26, markerFontSize: 10 },
  );
  V.evidenceRows(
    ctx,
    facts.evidence.map((row, index) => ({ ...row, label: `${index + 1} ${row.label}` })),
    { x: 6.18, y: 1.5, w: 3.34, h: 3.3 },
    { fontSize: 15, labelWidth: 0.95, gap: 0.14 },
  );
}
const cases = {
  mechanism: [mechanismBefore, mechanismAfter],
  data: [dataBefore, dataAfter],
  evidence: [evidenceBefore, evidenceAfter],
};
for (const [name, pair] of Object.entries(cases))
  for (const page of pair) {
    // Exact heading is collected from authored output by the example runner.
    page.presentation_copy = { headline: '', visual_labels: [] };
    page.notes =
      name === 'mechanism'
        ? '沿处理方向解释三步，重点说明每步保留的依据。'
        : name === 'data'
          ? '本页是合成教学数据，比较同条件表现，不推断差异原因。'
          : '这是合成界面示意，重点说明来源、版本与关系标签如何帮助回看。';
  }
module.exports = { cases, facts };
