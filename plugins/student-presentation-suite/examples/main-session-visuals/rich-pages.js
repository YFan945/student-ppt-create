'use strict';

// Synthetic teaching material. Geometry and typography are example choices.
function text(ctx, value, x, y, w, h, size, options = {}) {
  return ctx.H.addFittedText(
    ctx.slide,
    value,
    { x, y, w, h },
    ctx.tokens,
    'chinese',
    options.role || 'body',
    { fontSize: size, margin: 0, ...options },
  );
}
function shape(ctx, kind, x, y, w, h, color, options = {}) {
  ctx.slide.addShape(kind, {
    x,
    y,
    w,
    h,
    fill: { color },
    line: { color, transparency: 100 },
    ...options,
  });
}
function heading(ctx, value) {
  text(ctx, value, 0.45, 0.3, 9.1, 0.62, 27, { bold: true, role: 'title' });
}
function image(ctx, box) {
  if (!ctx.exampleAsset)
    throw new Error(
      'This page needs ctx.exampleAsset; use designedPlaceholder if no image is available.',
    );
  ctx.H.addPlannedImage(ctx.slide, ctx.exampleAsset, box, ctx.pptx);
}
function coverLayout(ctx, headline, size) {
  const p = ctx.tokens.palette;
  if (ctx.exampleAsset) image(ctx, { x: 4.8, y: 0.4, w: 4.75, h: 4.78 });
  text(ctx, '课程研究汇报', 0.55, 0.72, 4.0, 0.36, 16, { color: p.primary_accent });
  text(ctx, headline, 0.55, 1.43, 4.4, 1.9, size, {
    bold: true,
    color: p.primary_text,
    role: 'title',
  });
  text(ctx, '从多源材料到可追溯的知识关系', 0.55, 3.62, 4.2, 0.8, 18, { color: p.secondary_text });
  text(ctx, '课程实践组\n信息组织与展示', 0.55, 4.82, 4.3, 0.6, 14, { color: p.secondary_text });
  if (ctx.exampleAsset)
    text(ctx, '概念插图', 8.35, 5.17, 1.2, 0.25, 11, { color: p.secondary_text });
}
function cover(ctx) {
  coverLayout(ctx, '文化档案的\n多模态整理\n与知识关联方法', 31);
}
cover.presentation_copy = { headline: '文化档案的\n多模态整理\n与知识关联方法', visual_labels: [] };
cover.notes = '我们重点介绍多源材料如何组织成可追溯的知识关系。';
cover.kind = 'cover';

function shortCover(ctx) {
  coverLayout(ctx, '文化档案\n知识关联', 38);
}
shortCover.presentation_copy = { headline: '文化档案\n知识关联', visual_labels: [] };
shortCover.notes = '本次汇报说明文化档案的知识关联方法。';
shortCover.kind = 'cover';

function richTechnical(ctx) {
  const p = ctx.tokens.palette;
  const colors = ctx.H.categoryColors(ctx.tokens);
  heading(ctx, '多源材料经过统一表示，形成可追溯的知识关联');
  image(ctx, { x: 0.45, y: 1.24, w: 2.75, h: 1.62 });
  text(ctx, '概念插图', 0.45, 2.92, 2.75, 0.26, 11, { color: p.secondary_text });
  text(ctx, '采集与归档', 0.45, 1.0, 2.75, 0.3, 18, { bold: true, color: colors[0] });
  ctx.slide.addTable(
    [
      ['材料', '保留的信息'],
      ['影像', '拍摄对象、位置与日期'],
      ['语音', '原始片段与访谈上下文'],
      ['文本', '出处、段落与版本'],
    ],
    {
      x: 0.45,
      y: 3.36,
      w: 2.75,
      h: 1.15,
      colW: [0.7, 2.05],
      rowH: 0.2875,
      fontSize: 12,
      headerRows: 1,
      headerFontSize: 13,
      margin: 0.02,
    },
  );
  text(ctx, '统一表示', 3.55, 1.0, 2.4, 0.3, 18, { bold: true, color: colors[1] });
  const steps = [
    ['材料分段', '保留原始边界与索引'],
    ['特征表示', '各模态形成对应标签'],
    ['关系连接', '关联人物、地点与主题'],
  ];
  steps.forEach(([a, b], i) => {
    const y = 1.58 + i * 0.98;
    shape(ctx, 'roundRect', 3.55, y, 2.4, 0.82, p.surface, {
      line: { color: colors[1], width: 1 },
    });
    text(ctx, a, 3.73, y + 0.04, 2.05, 0.39, 16, { bold: true });
    text(ctx, b, 3.73, y + 0.47, 2.05, 0.29, 12, { color: p.secondary_text });
    if (i < 2)
      ctx.slide.addShape('line', {
        x: 4.75,
        y: y + 0.86,
        w: 0,
        h: 0.08,
        line: { color: colors[1], width: 1.5, endArrowType: 'triangle' },
      });
  });
  text(ctx, '知识关联', 6.4, 1.0, 3.15, 0.3, 18, { bold: true, color: colors[2] });
  [
    ['对象', '人物与地点'],
    ['事件', '时间与活动'],
    ['来源', '原始材料入口'],
  ].forEach(([a, b], i) => {
    const y = 1.58 + i * 0.98;
    shape(ctx, 'ellipse', 6.43, y + 0.08, 0.32, 0.32, colors[2]);
    text(ctx, a, 6.95, y, 2.5, 0.32, 17, { bold: true });
    text(ctx, b, 6.95, y + 0.42, 2.5, 0.33, 15);
  });
  text(ctx, '关系连接保留出处，\n便于回看材料和核对解释。', 6.43, 4.48, 3.08, 0.68, 16);
  text(ctx, '统一表示保留来源，支撑知识关联', 0.45, 4.83, 5.55, 0.46, 19, {
    bold: true,
    color: p.primary_accent,
  });
}
richTechnical.presentation_copy = {
  headline: '多源材料经过统一表示，形成可追溯的知识关联',
  visual_labels: ['采集与归档', '统一表示', '知识关联'],
};
richTechnical.notes = '重点看中间的统一表示，再看右侧关系如何保留来源。采集细节可在页面中浏览。';

function comparison(ctx) {
  heading(ctx, '资料归档与知识关联解决不同的检索问题');
  text(ctx, '比较依据：材料组织方式与查询入口', 0.45, 1.15, 9.1, 0.4, 18);
  ctx.slide.addTable(
    [
      ['维度', '资料归档', '知识关联'],
      ['组织单元', '文件、目录和原始片段', '对象、事件、关系与来源'],
      ['查询入口', '按名称、目录和标签查找', '按对象及关联关系追溯'],
      ['适用任务', '定位并阅读原始材料', '跨材料探索关联与证据'],
      ['保留要求', '原件、出处及版本', '原件入口及关系依据'],
    ],
    {
      x: 0.45,
      y: 1.92,
      w: 9.1,
      h: 2.65,
      colW: [1.35, 3.5, 4.25],
      rowH: 0.53,
      fontSize: 17,
      headerRows: 1,
      headerFontSize: 18,
      margin: 0.05,
    },
  );
  text(ctx, '重点：关联组织应继续保留原始材料入口', 0.45, 4.96, 9.1, 0.4, 21, {
    bold: true,
    color: ctx.tokens.palette.primary_accent,
  });
}
comparison.presentation_copy = {
  headline: '资料归档与知识关联解决不同的检索问题',
  visual_labels: ['资料归档', '知识关联'],
};
comparison.notes = '只讲查询入口的差别和来源保留要求，其余比较供大家阅读。';

function designedPlaceholder(ctx) {
  const p = ctx.tokens.palette;
  heading(ctx, '采集装置与资料整理的展示方案');
  shape(ctx, 'roundRect', 0.45, 1.37, 4.35, 3.15, p.surface, {
    line: { color: p.primary_accent, width: 1 },
  });
  // A topical editable scene, not an empty box or a fabricated device photo.
  shape(ctx, 'rect', 1.18, 2.32, 1.55, 1.09, 'FFFFFF', {
    line: { color: p.primary_accent, width: 1.4 },
  });
  [0, 1, 2].forEach((i) => shape(ctx, 'rect', 1.41, 2.57 + i * 0.2, 1.06, 0.06, p.primary_accent));
  shape(ctx, 'roundRect', 3.08, 2.42, 0.98, 0.89, p.primary_accent);
  shape(ctx, 'ellipse', 3.34, 2.64, 0.43, 0.43, 'FFFFFF');
  text(ctx, '素材待替换', 0.75, 1.67, 3.75, 0.4, 21, { bold: true, color: p.primary_accent });
  text(ctx, '实验装置照片区域', 0.75, 3.75, 3.75, 0.38, 17);
  text(ctx, '采集目标', 5.35, 1.46, 4.1, 0.37, 20, { bold: true });
  text(ctx, '保留材料细节与采集条件，\n将原始记录对应到整理结果。', 5.35, 2.04, 4.1, 0.86, 19);
  text(ctx, '归档要求', 5.35, 3.26, 4.1, 0.37, 20, { bold: true });
  text(ctx, '原件、出处和版本分别记录；\n展示素材与证据入口保持对应。', 5.35, 3.84, 4.1, 0.87, 19);
  text(ctx, '重点：整理后的展示仍可追溯到原始记录', 0.45, 5.03, 9.1, 0.35, 19, {
    bold: true,
    color: p.primary_accent,
  });
}
designedPlaceholder.presentation_copy = {
  headline: '采集装置与资料整理的展示方案',
  visual_labels: ['素材待替换', '采集目标', '归档要求'],
};
designedPlaceholder.notes = '我们保留采集条件和来源入口，让整理结果对应到原始记录。';
designedPlaceholder.asset_record = {
  slide: 1,
  purpose: '采集装置照片区域',
  source: 'placeholder:device',
  permission: 'suite-original',
  alt_text: '资料与采集装置的原生示意占位',
  fallback: '替换为实验装置实拍照片',
  placeholder: {
    kind: 'photo-slot',
    label: '素材待替换',
    replacement: '实验装置的实拍照片',
    reason: '尚未提供照片',
  },
};

function photoProcess(ctx) {
  if (!ctx.exampleAssets || ctx.exampleAssets.length < 4)
    throw new Error(
      'photoProcess needs four supplied image records, each with path, width and height',
    );
  heading(ctx, '影像材料与整理流程共同保留资料上下文');
  const p = ctx.tokens.palette;
  ctx.exampleAssets.slice(0, 4).forEach((asset, i) => {
    const x = 0.45 + (i % 2) * 2.22;
    const y = 1.23 + Math.floor(i / 2) * 1.72;
    ctx.H.addPlannedImage(ctx.slide, asset, { x, y, w: 2.06, h: 1.32 }, ctx.pptx);
    text(ctx, asset.label || `影像材料 ${i + 1}`, x, y + 1.36, 2.06, 0.31, 13, {
      color: p.secondary_text,
    });
  });
  [
    ['原始材料', '保留原件及材料入口'],
    ['上下文记录', '对应对象、位置与采集时间'],
    ['归档组织', '整理出处、版本和检索标签'],
    ['关联核对', '回看原始记录，核对解释'],
  ].forEach(([a, b], i) => {
    const y = 1.27 + i * 0.88;
    text(ctx, `${i + 1}`, 5.25, y, 0.42, 0.4, 22, { bold: true, color: p.primary_accent });
    text(ctx, a, 5.9, y, 3.5, 0.37, 19, { bold: true });
    text(ctx, b, 5.9, y + 0.43, 3.5, 0.33, 15);
    if (i < 3)
      ctx.slide.addShape('line', {
        x: 5.47,
        y: y + 0.48,
        w: 0,
        h: 0.28,
        line: { color: p.primary_accent, width: 1.3, endArrowType: 'triangle' },
      });
  });
  text(ctx, '资料整理保留上下文，展示解释可以追溯', 0.45, 5.04, 9.1, 0.35, 19, {
    bold: true,
    color: p.primary_accent,
  });
}
photoProcess.presentation_copy = {
  headline: '影像材料与整理流程共同保留资料上下文',
  visual_labels: ['原始材料', '上下文记录', '归档组织', '关联核对'],
};
photoProcess.notes = '重点看右侧四步怎样保留上下文；左侧影像可选择一张说明。';

// An editable image region with the actual planned generation prompt visible.
// The caller must register the returned record under an approved allow policy.
function promptPlaceholder(ctx, options, box) {
  const { prompt, replacement, reason, label = '素材待替换', kind = 'concept' } = options;
  if (![prompt, replacement, reason].every((value) => typeof value === 'string' && value.trim()))
    throw new TypeError('promptPlaceholder needs a prompt, replacement and reason');
  const p = ctx.tokens.palette;
  const { x, y, w, h } = box;
  shape(ctx, 'rect', x, y, w, h, p.surface, {
    decorative: true,
    line: { color: p.primary_accent, width: 1, transparency: 0 },
  });
  text(ctx, label, x + w * 0.04, y + h * 0.06, w * 0.92, h * 0.18, options.labelSize || 16, {
    color: p.primary_accent,
    bold: true,
  });
  text(
    ctx,
    `生成提示词：${prompt}`,
    x + w * 0.04,
    y + h * 0.3,
    w * 0.92,
    h * 0.62,
    options.promptSize || 14,
    {
      color: p.secondary_text,
    },
  );
  return {
    slide: ctx.n,
    purpose: options.purpose || replacement,
    source: `placeholder:${options.id || `image-${ctx.n}`}`,
    permission: 'suite-original',
    alt_text: replacement,
    fallback: '使用已授权工具按提示词生成并检查后替换此区域',
    prompt,
    placeholder: { kind, label, replacement, reason, prompt_visible: true },
  };
}

module.exports = {
  promptPlaceholder,
  cover,
  shortCover,
  richTechnical,
  comparison,
  designedPlaceholder,
  photoProcess,
};
