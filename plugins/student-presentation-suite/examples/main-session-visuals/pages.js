'use strict';

// Synthetic teaching content: editable text, native shapes/icons/connectors/table.
// Coordinates are examples, not a layout policy.
function colors(ctx) {
  return ctx.H.categoryColors(ctx.tokens);
}

function text(ctx, value, x, y, w, h, size = 17, extra = {}) {
  return ctx.H.addFittedText(
    ctx.slide,
    value,
    { x, y, w, h },
    ctx.tokens,
    'chinese',
    extra.role || 'body',
    {
      fontSize: size,
      margin: 0,
      ...extra,
    },
  );
}

function title(ctx, value) {
  text(ctx, value, 0.55, 0.34, 8.9, 0.56, 27, { bold: true, role: 'title' });
}

function panel(ctx, x, y, w, h, color) {
  ctx.slide.addShape('roundRect', {
    x,
    y,
    w,
    h,
    radius: 0.12,
    fill: { color, transparency: 94 },
    line: { color, transparency: 65, width: 0.8 },
    decorative: true,
  });
}

function arrow(ctx, x, y, w, color) {
  ctx.slide.addShape('line', {
    x,
    y,
    w,
    h: 0,
    line: { color, width: 1.5, endArrowType: 'triangle' },
  });
}

function icon(ctx, name, x, y, color) {
  // Native shapes also keep icons visible in viewers without SVG support.
  const draw = (kind, dx, dy, w, h, fill = false) =>
    ctx.slide.addShape(kind, {
      x: x + dx,
      y: y + dy,
      w,
      h,
      line: { color, width: 1.3 },
      fill: { color, transparency: fill ? 0 : 100 },
      decorative: true,
    });
  if (name === 'users') {
    draw('ellipse', 0.02, 0, 0.12, 0.12);
    draw('ellipse', 0.2, 0, 0.12, 0.12);
    draw('roundRect', 0, 0.16, 0.15, 0.16);
    draw('roundRect', 0.19, 0.16, 0.15, 0.16);
  } else if (name === 'target') {
    draw('ellipse', 0, 0, 0.34, 0.34);
    draw('ellipse', 0.09, 0.09, 0.16, 0.16);
    draw('ellipse', 0.15, 0.15, 0.04, 0.04, true);
  } else if (name === 'compare') {
    draw('rect', 0, 0.13, 0.1, 0.2, true);
    draw('rect', 0.2, 0, 0.1, 0.33, true);
  } else if (name === 'refresh') {
    draw('chevron', 0, 0, 0.15, 0.3, true);
    draw('chevron', 0.19, 0, 0.15, 0.3, true);
  } else {
    draw('rect', 0.03, 0, 0.27, 0.34);
    draw('line', 0.09, 0.08, 0.15, 0);
    draw('line', 0.09, 0.15, 0.15, 0);
    if (name === 'book') draw('line', 0.08, 0, 0, 0.34);
  }
}

function relationship(ctx) {
  title(ctx, '三类资源共同支持课程实践');
  const nodes = [
    ['book', '知识资料', '课程讲义与实验说明', '建立概念基础，保留可追溯的阅读入口。'],
    ['users', '协作伙伴', '同学分工与导师交流', '记录各自负责的问题，明确需要协助的环节。'],
    ['target', '实践任务', '实验操作与阶段反馈', '通过实际操作检验理解，用反馈调整下一步。'],
  ];
  nodes.forEach(([name, label, support, detail], index) => {
    const y = 1.24 + index * 1.2;
    panel(ctx, 0.55, y, 4.25, 1.02, colors(ctx)[index]);
    icon(ctx, name, 0.78, y + 0.16, colors(ctx)[index]);
    text(ctx, label, 1.25, y + 0.13, 3.25, 0.4, 19, { bold: true, color: colors(ctx)[index] });
    text(ctx, support, 1.25, y + 0.57, 3.25, 0.36, 15);
    arrow(ctx, 4.95, y + 0.45, 0.54, colors(ctx)[index]);
    text(ctx, detail, 5.7, y + 0.12, 3.55, 0.7, 17);
  });
  text(ctx, '共同目标：把概念、协作和操作连接成可复盘的学习过程', 0.65, 4.96, 8.7, 0.4, 17, {
    bold: true,
    color: colors(ctx)[0],
  });
}
relationship.presentation_copy = {
  headline: '三类资源共同支持课程实践',
  visual_labels: ['知识资料', '协作伙伴', '实践任务'],
};
relationship.notes =
  '这是合成教学示例。三类资源分别承担概念学习、协作和实践反馈的作用，箭头表示每类资源对应的解释，不表示统计转化。';

function groups(ctx) {
  title(ctx, '阶段复盘同时记录证据与改进');
  const groups = [
    [
      'file',
      '观察记录',
      '记录实验条件、步骤和现象，区分直接观察与后续推测。',
      '保留原始记录，让同伴可以核对实验过程与解释是否对应。',
    ],
    [
      'compare',
      '结果分析',
      '把不同条件下的现象放在同一口径中比较，说明可能影响。',
      '结合样本、条件与多轮记录，识别稳定变化并解释差异。',
    ],
    [
      'refresh',
      '下一步验证',
      '提出可操作的调整，说明要观察什么以及如何判断结果。',
      '先确认验证条件和分工，再根据新的记录决定是否继续修改。',
    ],
  ];
  groups.forEach(([name, label, a, b], index) => {
    const x = 0.55 + index * 3.04;
    panel(ctx, x, 1.2, 2.8, 2.65, colors(ctx)[index]);
    icon(ctx, name, x + 0.18, 1.4, colors(ctx)[index]);
    text(ctx, label, x + 0.63, 1.4, 1.98, 0.4, 19, { bold: true, color: colors(ctx)[index] });
    text(ctx, a, x + 0.18, 2.02, 2.42, 0.84, 15);
    text(ctx, b, x + 0.18, 2.96, 2.42, 0.84, 15);
  });
  ctx.slide.addTable(
    [
      [{ text: '记录层', options: { bold: true } }, '可核对材料', '用途'],
      ['观察', '实验日志与现象说明', '追溯过程'],
      ['解释', '条件比较与限制说明', '判断依据'],
      ['行动', '验证任务与分工', '推进改进'],
    ],
    {
      x: 0.55,
      y: 4.08,
      w: 8.88,
      h: 1.08,
      colW: [1.2, 4.4, 3.28],
      rowH: 0.27,
      fontSize: 12,
      margin: 0,
      headerRows: 1,
      headerFontSize: 12,
      color: ctx.tokens.palette.primary_text,
    },
  );
}
groups.presentation_copy = {
  headline: '阶段复盘同时记录证据与改进',
  visual_labels: ['观察记录', '结果分析', '下一步验证'],
};
groups.notes =
  '我们先记录实验条件和现象，再比较不同条件下的变化。确认样本和条件后，把发现转化为下一轮验证任务。记录、解释与行动共同形成复盘依据。';

function evidence(ctx) {
  title(ctx, '实验图与说明共同呈现观察依据');
  if (!ctx.exampleAsset)
    throw new Error('evidence requires ctx.exampleAsset with a real path, width and height');
  ctx.H.addPlannedImage(
    ctx.slide,
    ctx.exampleAsset,
    { x: 0.55, y: 1.34, w: 5.05, h: 3.52 },
    ctx.pptx,
  );
  ['先说明图中对象与实验条件', '再标明观察位置和对应现象', '最后区分直接观察与解释边界'].forEach(
    (label, index) => {
      const y = 1.35 + index * 1.2;
      panel(ctx, 5.95, y, 3.45, 1.0, colors(ctx)[index]);
      text(ctx, `${index + 1}`, 6.13, y + 0.16, 0.4, 0.4, 23, {
        bold: true,
        color: colors(ctx)[index],
      });
      text(ctx, label, 6.7, y + 0.17, 2.43, 0.65, 17);
    },
  );
  text(
    ctx,
    '图源：调用者提供的教学示意图；不代表真实实验照片或测量结果',
    0.55,
    5.02,
    8.85,
    0.27,
    12,
  );
}
evidence.presentation_copy = {
  headline: '实验图与说明共同呈现观察依据',
  visual_labels: ['实验条件', '观察位置', '解释边界'],
};
evidence.notes =
  '我们把图中的观察位置与条件记录对应起来，结合一致的测量过程解释差异，再明确下一步验证任务。';

function actions(ctx) {
  title(ctx, '把复盘问题对应到可执行的改进');
  text(ctx, '发现的问题', 1.15, 1.1, 3.2, 0.35, 17, { bold: true });
  text(ctx, '改进动作与检查条件', 5.43, 1.1, 3.95, 0.35, 17, { bold: true });
  const rows = [
    ['实验条件遗漏', '补齐条件记录', '同伴能按记录复现步骤'],
    ['观察与推测混写', '分开记录两种信息', '每项解释能找到对应观察'],
    ['下一步任务模糊', '明确验证对象与分工', '执行者知道要收集哪些记录'],
  ];
  rows.forEach(([problem, action, condition], index) => {
    const y = 1.7 + index * 1.05;
    panel(ctx, 0.55, y, 8.88, 0.88, colors(ctx)[index]);
    text(ctx, `${index + 1}`, 0.73, y + 0.2, 0.3, 0.4, 22, {
      color: colors(ctx)[index],
      bold: true,
    });
    text(ctx, problem, 1.15, y + 0.24, 3.2, 0.4, 18);
    arrow(ctx, 4.55, y + 0.43, 0.5, colors(ctx)[index]);
    text(ctx, action, 5.43, y + 0.1, 3.72, 0.4, 18, { bold: true, color: colors(ctx)[index] });
    text(ctx, condition, 5.43, y + 0.53, 3.72, 0.28, 14);
  });
  text(ctx, '完成条件应对应实际记录，不用装饰性进度条替代验证依据', 0.65, 5.0, 8.7, 0.3, 16);
}
actions.presentation_copy = {
  headline: '把复盘问题对应到可执行的改进',
  visual_labels: ['发现的问题', '改进动作与检查条件'],
};
actions.notes =
  '合成教学示例。每一行把问题、动作和可观察的完成条件对应起来；没有虚构比例、成果或验证状态。';

module.exports = { relationship, groups, evidence, actions };
