/**
 * Editable visual components for generated decks.
 *
 * Every component consumes one preallocated safe-area box. Components never
 * mutate the deck theme and never place content outside the supplied box.
 */

const pptxgen = require('pptxgenjs');
const H = require('pptx-helpers');
const S = require('pptx-shapes');
const SVG = require('pptx-svg-library');
const { imageSize } = require('image-size');

const SHAPE = new pptxgen().ShapeType;
const CHART = new pptxgen().ChartType;

function items(value) {
  return Array.isArray(value) ? value.filter(Boolean) : [];
}

// ── 数值轴范围 ────────────────────────────────────────────
// pptxgenjs 默认让纵轴自动贴合数据，导致：
//   1) 最高点的 outEnd 数据标签顶到绘图区上沿、与图表标题相撞或被裁；
//   2) 轴上限随数据浮动，跨页比例不可比。
// 这里统一计算"整齐上限 + 顶部余量"，并允许作者用 axis_max / axis_min 覆盖。
const NICE_STEPS = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];

function niceNumber(value) {
  const v = Math.abs(Number(value));
  if (!Number.isFinite(v) || v <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(v));
  for (const step of NICE_STEPS) {
    const candidate = step * magnitude;
    if (candidate >= v) return candidate;
  }
  return 10 * magnitude;
}

function seriesValues(series) {
  const out = [];
  for (const entry of series) {
    for (const value of Array.isArray(entry && entry.values) ? entry.values : []) {
      const n = Number(value);
      if (Number.isFinite(n)) out.push(n);
    }
  }
  return out;
}

function resolveAxisRange(data, series) {
  const values = seriesValues(series);
  const dataMax = values.length ? Math.max(...values) : 0;
  const dataMin = values.length ? Math.min(...values) : 0;
  const override = (key) => (Number.isFinite(Number(data[key])) ? Number(data[key]) : null);
  const max = override('axis_max') ?? niceNumber(dataMax * 1.08);
  const min = override('axis_min') ?? (dataMin < 0 ? -niceNumber(Math.abs(dataMin) * 1.08) : 0);
  return { min, max, majorUnit: niceNumber((max - min) / 4) };
}

/**
 * 结论面板布局：宽度与高度由文案量决定。
 *
 * 旧实现固定 `w = area.w*0.31 / h = area.h*0.84`，不论文案长短，
 * 短结论会撑出一个上下大片空白的"空盒子"。这里按字数估算行数收缩高度并垂直居中，
 * 空出的宽度还给图表。
 * @returns {{ box: object, chartRatio: number }}
 */
function takeawayLayout(text, area, tokens, lang) {
  const plain = String(text || '');
  const isCJK = /[぀-ヿ㐀-鿿豈-﫿]/u.test(plain);
  const length = plain.length;
  const ratio = Math.min(0.38, Math.max(0.24, 0.24 + (length / (isCJK ? 90 : 150)) * 0.14));
  const w = area.w * ratio;
  const x = area.x + area.w - w;
  const fontSize = H.fontSizeScale(tokens, lang).label;
  // 与 H.estimateTextFit 同一套估算：字宽(cm) = 字号 × 0.035(CJK)/0.021(拉丁)。
  const charWidthIn = (fontSize * (isCJK ? 0.035 : 0.021)) / 2.54;
  const charsPerLine = Math.max(4, Math.floor((w - 0.36) / charWidthIn));
  const lines = Math.max(1, Math.ceil(length / charsPerLine));
  const lineHeightIn = (fontSize * 1.4) / 72;
  const h = Math.min(area.h, Math.max(area.h * 0.3, lines * lineHeightIn + 0.5));
  return {
    box: { x, y: area.y + (area.h - h) / 2, w, h },
    chartRatio: 1 - ratio - 0.05,
  };
}

function textOf(value, fallback) {
  if (typeof value === 'string') return value;
  if (value && typeof value === 'object') {
    return String(value.label || value.title || value.name || fallback || '');
  }
  return String(fallback || '');
}

function palette(tokens) {
  return {
    canvas: H.color(tokens, 'canvas'),
    surface: H.color(tokens, 'surface'),
    text: H.color(tokens, 'primary_text'),
    muted: H.color(tokens, 'secondary_text'),
    accent: H.color(tokens, 'primary_accent'),
    accent2: H.color(tokens, 'secondary_accent'),
  };
}

function containImage(path, box) {
  const size = imageSize(path);
  if (!size.width || !size.height) throw new RangeError(`Cannot determine image size: ${path}`);
  const scale = Math.min(box.w / size.width, box.h / size.height);
  const w = size.width * scale;
  const h = size.height * scale;
  return {
    x: box.x + (box.w - w) / 2,
    y: box.y + (box.h - h) / 2,
    w,
    h,
  };
}

/** cover 裁切：填满 box 并居中裁掉溢出（区别于 contain 的留白）。 */
function coverImage(path, box) {
  const size = imageSize(path);
  if (!size.width || !size.height) throw new RangeError(`Cannot determine image size: ${path}`);
  return {
    x: box.x,
    y: box.y,
    w: box.w,
    h: box.h,
    sizing: { type: 'cover', w: box.w, h: box.h },
  };
}

function addPanel(slide, box, tokens, options) {
  const p = palette(tokens);
  const shape = options?.shape || 'roundRect';
  return S.addStyledContainer(slide, shape, box, tokens, {
    fill: options?.fill || p.surface,
    line: options?.line || p.accent,
    lineWidth: options?.lineWidth || 1.25,
    fillTransparency: options?.fillTransparency,
  });
}

function addLabel(slide, text, box, tokens, lang, options) {
  const role = options?.role || (options?.align === 'left' ? 'body' : 'label');
  const inset = options?.shape ? S.safeInsetForShape(options.shape, box) : { x: 0, y: 0 };
  const safeBox = {
    x: box.x + inset.x,
    y: box.y + inset.y,
    w: Math.max(0.1, box.w - inset.x * 2),
    h: Math.max(0.1, box.h - inset.y * 2),
  };
  const fittedOptions = {
    // Compact component labels often occupy sub-zones under one inch high.
    // A 16pt inset on every edge can consume the entire box; keep a readable
    // default while allowing callers to request larger editorial padding.
    margin: options?.margin ?? 6,
    bold: Boolean(options && options.bold),
    label: (options && options.label) || '视觉组件文本',
  };
  for (const key of ['align', 'valign', 'color', 'fontSize', 'fontFace', 'min', 'max']) {
    if (options?.[key] !== undefined) fittedOptions[key] = options[key];
  }
  return H.addFittedText(slide, text, safeBox, tokens, lang, role, fittedOptions);
}

function addNumberMarker(slide, box, tokens) {
  const p = palette(tokens);
  slide.addShape(SHAPE.ellipse, {
    ...box,
    fill: { color: p.accent },
    line: { color: p.accent, transparency: 100 },
  });
}

function addSectionHero(slide, data, area, tokens, lang) {
  const p = palette(tokens);
  // 官方规范：禁止装饰性竖向 accent 色条；标题从内容区左缘开始。
  const titleBox = {
    x: area.x,
    y: area.y + area.h * 0.05,
    w: area.w * 0.72,
    h: area.h * 0.42,
  };
  addLabel(slide, data.title || data.claim, titleBox, tokens, lang, {
    bold: true,
    align: 'left',
    // 必须显式声明 title 角色：addLabel 默认按 align 猜角色，左对齐会被判成
    // body（上限 26pt），导致 Hero 标题与副标题同级、层级塌陷。
    role: 'title',
    fontSize: H.fontSizeScale(tokens, lang).title,
    fontFace: H.fontFamily(tokens).title,
    label: 'Hero 标题',
  });
  if (data.subtitle || data.takeaway) {
    addLabel(
      slide,
      data.subtitle || data.takeaway,
      {
        x: titleBox.x,
        y: titleBox.y + titleBox.h + H.spacing(tokens, 3),
        w: area.w * 0.58,
        h: area.h * 0.46,
      },
      tokens,
      lang,
      { align: 'left', color: p.muted, label: 'Hero 副标题' },
    );
  }
  slide.addShape(SHAPE.ellipse, {
    x: area.x + area.w * 0.8,
    y: area.y + area.h * 0.08,
    w: area.h * 0.42,
    h: area.h * 0.42,
    fill: { color: p.accent2, transparency: 12 },
    line: { transparency: 100 },
  });
}

function addProcessFlow(slide, data, area, tokens, lang) {
  const steps = items(data.steps || data.items);
  if (steps.length < 2 || steps.length > 5) {
    throw new RangeError('addProcessFlow requires 2-5 steps.');
  }
  const gap = H.spacing(tokens, 3);
  const cells = H.weightedColumns(area, steps.length, data.weights, gap);
  const cardH = area.h * 0.72;
  const y = area.y + (area.h - cardH) / 2;
  steps.forEach((step, index) => {
    const x = cells[index].x;
    const cardW = cells[index].w;
    const shape = 'roundRect';
    const card = { x, y, w: cardW, h: cardH };
    const inset = S.safeInsetForShape(shape, card);
    addPanel(slide, card, tokens, { shape, variant: index });
    addLabel(
      slide,
      data.numbered === false
        ? textOf(step, `Step ${index + 1}`)
        : `${index + 1}. ${textOf(step, `Step ${index + 1}`)}`,
      { x: x + inset.x, y: y + inset.y, w: cardW - inset.x * 2, h: cardH - inset.y * 2 },
      tokens,
      lang,
      { bold: true, role: 'node', label: `流程步骤 ${index + 1}` },
    );
    if (index < steps.length - 1) {
      slide.addShape(SHAPE.line, {
        x: x + cardW,
        y: y + cardH * 0.5,
        w: gap,
        h: 0,
        line: {
          color: palette(tokens).accent2,
          width: 2,
          endArrowType: 'triangle',
        },
      });
    }
  });
}

function addTimeline(slide, data, area, tokens, lang) {
  const stages = items(data.stages || data.items);
  if (stages.length < 3 || stages.length > 6) {
    throw new RangeError('addTimeline requires 3-6 stages.');
  }
  const p = palette(tokens);
  const axisY = area.y + area.h * 0.52;
  const stepW = area.w / stages.length;
  slide.addShape(SHAPE.line, {
    x: area.x + stepW * 0.5,
    y: axisY,
    w: area.w - stepW,
    h: 0,
    line: { color: p.accent, width: 2.5 },
  });
  stages.forEach((stage, index) => {
    const centerX = area.x + stepW * (index + 0.5);
    addNumberMarker(slide, { x: centerX - 0.2, y: axisY - 0.2, w: 0.4, h: 0.4 }, tokens);
    const above = index % 2 === 0;
    addLabel(
      slide,
      textOf(stage),
      {
        x: centerX - stepW * 0.5,
        y: above ? area.y : axisY + 0.45,
        w: stepW,
        h: area.h * 0.36,
      },
      tokens,
      lang,
      { bold: true, label: `时间线阶段 ${index + 1}` },
    );
  });
}

function addComparison(slide, data, area, tokens, lang) {
  const entries = items(data.items);
  if (entries.length < 2 || entries.length > 3) {
    throw new RangeError('addComparison requires 2-3 items.');
  }
  const gap = H.spacing(tokens, 3);
  // 去等宽化：显式 weights 优先；有 highlight 时默认给首选项 1.55 倍权重，
  // 避免“等宽双卡”的 AI 模板感（参考 asymmetric-decision）。
  let weights = data.weights;
  if (!weights && data.highlight !== undefined && entries.length === 2) {
    const hi = Number(data.highlight) === 0 ? 0 : 1;
    weights = hi === 0 ? [1.55, 1] : [1, 1.55];
  }
  const cells = H.weightedColumns(area, entries.length, weights, gap);
  const p = palette(tokens);
  entries.forEach((entry, index) => {
    const shape = 'roundRect';
    addPanel(slide, cells[index], tokens, {
      shape,
      line: index === Number(data.highlight || 0) ? p.accent2 : p.accent,
      lineWidth: index === Number(data.highlight || 0) ? 2.5 : 1.25,
    });
    const label = textOf(entry);
    const detail =
      entry && typeof entry === 'object'
        ? items(entry.points || entry.details)
            .map(textOf)
            .join('\n')
        : '';
    addLabel(
      slide,
      label,
      {
        x: cells[index].x + cells[index].w * 0.08,
        y: cells[index].y + cells[index].h * 0.06,
        w: cells[index].w * 0.84,
        h: cells[index].h * 0.32,
      },
      tokens,
      lang,
      { bold: true, label: `对比标题 ${index + 1}` },
    );
    if (detail) {
      addLabel(
        slide,
        detail,
        {
          x: cells[index].x + cells[index].w * 0.08,
          y: cells[index].y + cells[index].h * 0.42,
          w: cells[index].w * 0.84,
          h: cells[index].h * 0.5,
        },
        tokens,
        lang,
        { align: 'left', color: p.muted, label: `对比内容 ${index + 1}` },
      );
    }
  });
}

function addMetricDashboard(slide, data, area, tokens, lang) {
  const metrics = items(data.metrics || data.items);
  if (metrics.length < 2 || metrics.length > 4) {
    throw new RangeError('addMetricDashboard requires 2-4 metrics.');
  }
  const gap = H.spacing(tokens, 3);
  const emphasis = data.emphasis !== undefined ? Number(data.emphasis) : -1;
  const weights = metrics.map((_, index) => (index === emphasis ? 1.6 : 1));
  const cells = H.weightedColumns(area, metrics.length, weights, gap);
  const p = palette(tokens);
  metrics.forEach((metric, index) => {
    const shape = 'roundRect';
    addPanel(slide, cells[index], tokens, { shape, variant: index });
    const value = metric && typeof metric === 'object' ? metric.value : metric;
    const label = metric && typeof metric === 'object' ? metric.label : '';
    addLabel(
      slide,
      value,
      {
        x: cells[index].x,
        y: cells[index].y + cells[index].h * 0.18,
        w: cells[index].w,
        h: cells[index].h * 0.3,
      },
      tokens,
      lang,
      { bold: true, role: 'kpi', shape, color: p.accent, label: `指标值 ${index + 1}` },
    );
    addLabel(
      slide,
      label,
      {
        x: cells[index].x,
        y: cells[index].y + cells[index].h * 0.48,
        w: cells[index].w,
        h: cells[index].h * 0.42,
      },
      tokens,
      lang,
      { role: 'label', shape, color: p.muted, label: `指标标签 ${index + 1}` },
    );
  });
}

/**
 * 风格化数据表：表头强调 + 斑马纹 + 细边框，全部来自调色板。
 * data: { columns: string[], rows: (string|number)[][], highlight_row?: number,
 *         zebra?: boolean (默认 true), title?: string }
 */
function addStyledTable(slide, data, area, tokens, lang) {
  const p = palette(tokens);
  const columns = items(data.columns);
  const rows = items(data.rows);
  if (!rows.length) throw new RangeError('addStyledTable requires at least one row.');
  const widths = items(data.column_widths);
  const headerCells = columns.map((name) => ({
    text: textOf(name),
    options: {
      fill: { color: p.accent },
      color: 'FFFFFF',
      bold: true,
      fontFace: H.fontFamily(tokens).body,
      fontSize: Math.max(11, H.fontSizeScale(tokens, lang).caption + 1),
      align: 'left',
      valign: 'middle',
    },
  }));
  const highlight = data.highlight_row !== undefined ? Number(data.highlight_row) : -1;
  const bodyRows = rows.map((row, rowIndex) => {
    const zebra = data.zebra === false ? false : rowIndex % 2 === 1;
    const emphasized = rowIndex === highlight;
    const baseFill = emphasized ? p.accent2 : zebra ? p.surface : p.canvas;
    return items(row).map((cell) => ({
      text: textOf(cell),
      options: {
        fill: { color: baseFill },
        color: emphasized ? 'FFFFFF' : p.text,
        bold: emphasized,
        fontFace: H.fontFamily(tokens).body,
        fontSize: Math.max(11, H.fontSizeScale(tokens, lang).caption),
        align: 'left',
        valign: 'middle',
      },
    }));
  });
  const takeaway = data.title ? takeawayLayout(String(data.title), area, tokens, lang) : null;
  const tableBox = {
    x: area.x,
    y: area.y,
    w: area.w * (takeaway ? takeaway.chartRatio : 1),
    h: area.h,
  };
  const colCount = columns.length || (bodyRows[0] ? bodyRows[0].length : 1);
  slide.addTable([headerCells, ...bodyRows], {
    x: tableBox.x,
    y: tableBox.y,
    w: tableBox.w,
    h: tableBox.h,
    colW: widths.length === colCount ? widths.map(Number) : undefined,
    border: { type: 'solid', color: p.muted, pt: 0.5 },
    margin: 0.06,
  });
  if (takeaway) {
    addPanel(slide, takeaway.box, tokens, { line: p.accent2 });
    addLabel(slide, String(data.title), takeaway.box, tokens, lang, {
      bold: true,
      align: 'left',
      label: '表格结论',
    });
  }
}

function addChartWithTakeaway(slide, data, area, tokens, lang) {
  const p = palette(tokens);
  const colors = [p.accent, p.accent2, p.muted];
  const rawSeries = items(data.series);
  const series = rawSeries.map((entry) => {
    const normalized = { ...entry };
    delete normalized.color;
    return normalized;
  });
  if (!series.length) {
    throw new RangeError('addChartWithTakeaway requires editable chart series.');
  }
  const takeawayText = data.takeaway || 'State the conclusion supported by this chart.';
  const takeaway = takeawayLayout(takeawayText, area, tokens, lang);
  const chartBox = { x: area.x, y: area.y, w: area.w * takeaway.chartRatio, h: area.h };
  // 官方规范：stacked 图数据标签只能用 ctr/inEnd/inBase，outEnd 会损坏文件；
  // 非 stacked 用 outEnd 合法。
  const stacked = data.stacked === true;
  // 图表语法扩展：kind 支持 bar（默认）/line/doughnut；bar 方向用 orientation。
  // 设计原则“无网格线”：valGridLine 默认关闭，data.gridlines === true 显式恢复。
  const kind = ['bar', 'line', 'doughnut'].includes(data.kind) ? data.kind : 'bar';
  const chartType = kind === 'line' ? CHART.line : kind === 'doughnut' ? CHART.doughnut : CHART.bar;
  // 单系列柱/条形图：pptxgenjs 只在 chartColors 长度 >1 时才写 <c:dPt>，
  // 每 series 一色会让所有柱子同色，色彩不承载任何分类信息。
  // 这里给每个数据点一个同族色阶；highlight_index 可指定用满色的点。
  const pointCount = Array.isArray(series[0] && series[0].values) ? series[0].values.length : 0;
  const varyByPoint = kind === 'bar' && !stacked && series.length === 1 && pointCount > 1;
  const chartColors = varyByPoint
    ? S.accentRamp(p.accent, p.canvas, pointCount, data.highlight_index)
    : rawSeries.map((entry, index) => entry.color || colors[index % colors.length]);
  // 图表内文字统一从字号层级派生：图表标题 < 页面标题，轴标签/数据标签 < 正文。
  // 之前的硬编码 18pt/22pt 与正文同级，一页会出现两个"准标题"。
  const labelPt = H.fontSizeScale(tokens, lang).label;
  const chartText = {
    chartTitle: Math.max(14, Math.min(18, labelPt + 1)),
    dataLabel: Math.max(12, labelPt - 2),
    legend: Math.max(12, labelPt - 3),
    axis: Math.max(11, labelPt - 4),
  };
  const chartOptions = {
    ...chartBox,
    showTitle: true,
    title: data.title || data.measure || 'Key result',
    titleFontFace: H.fontFamily(tokens).title,
    titleFontSize: chartText.chartTitle,
    // PptxGenJS ignores a `color` property on series data. Supplying one color per
    // series through chartColors writes c:ser/c:spPr and keeps style tokens visible.
    chartColors,
    dataLabelColor: p.text,
    dataLabelFormatCode: '#,##0.##',
    dataLabelFontFace: H.fontFamily(tokens).body,
    dataLabelFontSize: chartText.dataLabel,
    showValue: true,
    showLegend: kind === 'doughnut' ? true : series.length > 1,
    legendFontFace: H.fontFamily(tokens).body,
    legendFontSize: chartText.legend,
    showCatName: false,
    showSerName: false,
    altText: data.alt_text || data.altText || data.takeaway || 'Editable data chart',
  };
  if (kind === 'doughnut') {
    chartOptions.dataLabelPosition = 'bestFit';
    chartOptions.holeSize = Number(data.hole_size || 60);
  } else {
    chartOptions.catAxisLabelFontFace = H.fontFamily(tokens).body;
    chartOptions.valAxisLabelFontFace = H.fontFamily(tokens).body;
    const axisRange = resolveAxisRange(data, series);
    chartOptions.catAxisLabelFontSize = chartText.axis;
    chartOptions.valAxisLabelFontSize = chartText.axis;
    chartOptions.valAxisMaxVal = axisRange.max;
    chartOptions.valAxisMinVal = axisRange.min;
    chartOptions.valAxisMajorUnit = axisRange.majorUnit;
    chartOptions.catAxisLabelColor = p.muted;
    chartOptions.valAxisLabelColor = p.muted;
    chartOptions.catGridLine = { style: 'none' };
    chartOptions.valGridLine =
      data.gridlines === true ? { color: p.muted, size: 1 } : { style: 'none' };
    chartOptions.dataLabelPosition = stacked ? 'inEnd' : 'outEnd';
    if (kind === 'bar') {
      chartOptions.barDir = data.orientation === 'bar' ? 'bar' : 'col';
    }
  }
  slide.addChart(chartType, series, chartOptions);
  addPanel(slide, takeaway.box, tokens, { line: p.accent2 });
  addLabel(slide, takeawayText, takeaway.box, tokens, lang, {
    bold: true,
    label: '图表结论',
  });
}

function addArchitecture(slide, data, area, tokens, lang) {
  const nodes = items(data.nodes || data.items);
  if (nodes.length < 2 || nodes.length > 6) {
    throw new RangeError('addArchitecture requires 2-6 nodes.');
  }
  const columns = nodes.length > 3 ? 3 : nodes.length;
  const rows = Math.ceil(nodes.length / columns);
  const cells = H.gridLayout(area, columns, rows, {
    columnGap: H.spacing(tokens, 3),
    rowGap: H.spacing(tokens, 3),
  });
  nodes.forEach((node, index) => {
    const cell = cells[index];
    if (index > 0) {
      const previous = cells[index - 1];
      const lineStyle = { color: palette(tokens).muted, width: 1.5, endArrowType: 'triangle' };
      if (Math.abs(previous.y - cell.y) < 0.01) {
        // 同一行：水平连接线，高度必须为 0，否则斜向拉伸。
        slide.addShape(SHAPE.line, {
          x: previous.x + previous.w,
          y: previous.y + previous.h / 2,
          w: Math.max(0.05, cell.x - previous.x - previous.w),
          h: 0,
          line: lineStyle,
        });
      } else {
        // 换行：改为竖直连接线指向正上方的节点。
        // 旧实现直接连两格中点，跨行时会画出斜穿版面的对角箭头。
        const above = cells[index - columns];
        if (above) {
          slide.addShape(SHAPE.line, {
            x: above.x + above.w / 2,
            y: above.y + above.h,
            w: 0,
            h: Math.max(0.05, cell.y - above.y - above.h),
            line: lineStyle,
          });
        }
      }
    }
    const shape = 'roundRect';
    addPanel(slide, cell, tokens, { shape, variant: index });
    addLabel(slide, textOf(node), cell, tokens, lang, {
      bold: true,
      role: 'node',
      shape,
      label: `架构节点 ${index + 1}`,
    });
  });
}

function addMatrix(slide, data, area, tokens, _lang) {
  const entries = items(data.items);
  if (entries.length < 2 || entries.length > 4) {
    throw new RangeError('addMatrix requires 2-4 items.');
  }
  const p = palette(tokens);
  const plot = {
    x: area.x + area.w * 0.12,
    y: area.y + area.h * 0.02,
    w: area.w * 0.82,
    h: area.h * 0.47,
  };
  slide.addShape(SHAPE.line, {
    x: plot.x,
    y: plot.y + plot.h,
    w: plot.w,
    h: 0,
    line: { color: p.muted, width: 1.5, endArrowType: 'triangle' },
  });
  slide.addShape(SHAPE.line, {
    x: plot.x,
    y: plot.y,
    w: 0,
    h: plot.h,
    line: { color: p.muted, width: 1.5, beginArrowType: 'triangle' },
  });
  entries.forEach((entry, index) => {
    // 用 ?? 而非 ||：x=0 / y=0 是合法的最左/最上坐标，|| 会把它当假值替换掉。
    const xValue = Number(entry?.x ?? (index + 1) / (entries.length + 1));
    const yValue = Number(entry?.y ?? ((index % 3) + 1) / 4);
    const x = plot.x + Math.max(0.08, Math.min(0.92, xValue)) * plot.w;
    const y = plot.y + (1 - Math.max(0.08, Math.min(0.92, yValue))) * plot.h;
    slide.addShape(SHAPE.ellipse, {
      x: x - 0.16,
      y: y - 0.16,
      w: 0.32,
      h: 0.32,
      fill: { color: index % 2 ? p.accent2 : p.accent },
      line: { transparency: 100 },
    });
  });
  const legend = {
    x: area.x,
    y: area.y + area.h * 0.58,
    w: area.w,
    h: area.h * 0.42,
  };
  const legendCells = H.gridLayout(legend, entries.length, 1, {
    columnGap: H.spacing(tokens, 3),
  });
  entries.forEach((entry, index) => {
    addPanel(slide, legendCells[index], tokens, {
      line: index % 2 ? p.accent2 : p.accent,
    });
    addLabel(slide, textOf(entry), legendCells[index], tokens, _lang, {
      bold: true,
      label: `矩阵标签 ${index + 1}`,
    });
  });
}

function addAnnotatedVisual(slide, data, area, tokens, lang) {
  const p = palette(tokens);
  const imageBox = { x: area.x, y: area.y, w: area.w * 0.56, h: area.h };
  if (data.asset) {
    addPanel(slide, imageBox, tokens, { shape: 'rect', fill: p.surface, line: p.muted });
    const useCover = data.fit === 'cover';
    slide.addImage({
      path: data.asset,
      ...(useCover
        ? coverImage(data.asset, {
            x: imageBox.x + 0.04,
            y: imageBox.y + 0.04,
            w: imageBox.w - 0.08,
            h: imageBox.h - 0.08,
          })
        : containImage(data.asset, imageBox)),
      altText: data.alt_text || data.altText || data.purpose || 'Presentation visual',
      shadow: H.softShadow(tokens) || undefined,
    });
    // 单色着色：强调色半透明叠层，把照片统一进风格色系
    if (data.tint) {
      slide.addShape(SHAPE.rect, {
        x: imageBox.x + 0.04,
        y: imageBox.y + 0.04,
        w: imageBox.w - 0.08,
        h: imageBox.h - 0.08,
        fill: { color: p.accent, transparency: Number(data.tint) || 55 },
        line: { color: p.accent, transparency: 100 },
      });
    }
  } else if (data.svg_reference) {
    addPanel(slide, imageBox, tokens, { shape: 'none', fill: p.canvas, line: p.muted });
    SVG.addCornerDecoration(
      slide,
      data.svg_reference,
      {
        x: imageBox.x + imageBox.w * 0.16,
        y: imageBox.y + imageBox.h * 0.12,
        w: imageBox.w * 0.68,
        h: imageBox.h * 0.68,
      },
      tokens,
    );
  } else {
    addPanel(slide, imageBox, tokens, { shape: 'ellipse', fill: p.surface, line: p.accent });
    addLabel(
      slide,
      data.title || data.purpose || textOf(items(data.annotations || data.items)[0], 'Overview'),
      imageBox,
      tokens,
      lang,
      { bold: true, label: '解释焦点' },
    );
  }
  const annotations = items(data.annotations || data.items).slice(0, 3);
  const annotationArea = {
    x: area.x + area.w * 0.6,
    y: area.y,
    w: area.w * 0.4,
    h: area.h,
  };
  const cells = H.gridLayout(annotationArea, 1, Math.max(1, annotations.length), {
    rowGap: H.spacing(tokens, 3),
  });
  annotations.forEach((annotation, index) => {
    addPanel(slide, cells[index], tokens);
    addLabel(slide, textOf(annotation), cells[index], tokens, lang, {
      align: 'left',
      fontSize: 18,
      margin: 16,
      label: `图像注释 ${index + 1}`,
    });
  });
}

function addQuotePanel(slide, data, area, tokens, lang) {
  const p = palette(tokens);
  // 官方规范：禁止装饰性竖条；引文仅用底面色块 + 文本层级区分。
  addPanel(slide, area, tokens, { fill: p.surface, line: p.surface });
  addLabel(
    slide,
    data.quote || data.text,
    {
      x: area.x + area.w * 0.08,
      y: area.y + area.h * 0.16,
      w: area.w * 0.84,
      h: area.h * 0.38,
    },
    tokens,
    lang,
    { bold: true, align: 'left', label: '引文' },
  );
  if (data.source) {
    addLabel(
      slide,
      data.source,
      {
        x: area.x + area.w * 0.48,
        y: area.y + area.h * 0.65,
        w: area.w * 0.4,
        h: area.h * 0.31,
      },
      tokens,
      lang,
      { align: 'right', color: p.muted, label: '引文来源' },
    );
  }
}

function addSummary(slide, data, area, tokens, lang) {
  const takeaways = items(data.items || data.takeaways).slice(0, 4);
  if (!takeaways.length) throw new RangeError('addSummary requires 1-4 takeaways.');
  if (takeaways.length === 1) {
    addPanel(slide, area, tokens, { line: palette(tokens).accent2 });
    return addLabel(slide, textOf(takeaways[0]), area, tokens, lang, {
      bold: true,
      label: '总结结论',
    });
  }
  return addProcessFlow(slide, { steps: takeaways, numbered: false }, area, tokens, lang);
}

function addReferenceList(slide, data, area, tokens, lang) {
  const references = items(data.items || data.references);
  if (!references.length) throw new RangeError('addReferenceList requires at least one reference.');
  addPanel(slide, area, tokens, { line: palette(tokens).muted });
  return addLabel(
    slide,
    references.map(textOf).join('\n'),
    {
      x: area.x + area.w * 0.06,
      y: area.y + area.h * 0.08,
      w: area.w * 0.88,
      h: area.h * 0.84,
    },
    tokens,
    lang,
    { align: 'left', role: 'reference', label: '参考资料' },
  );
}

const COMPONENTS = {
  hero: addSectionHero,
  'visual-dominant': addAnnotatedVisual,
  'process-path': addProcessFlow,
  timeline: addTimeline,
  comparison: addComparison,
  dashboard: addMetricDashboard,
  architecture: addArchitecture,
  matrix: addMatrix,
  quote: addQuotePanel,
  summary: addSummary,
  table: addStyledTable,
  reference: addReferenceList,
};

function renderVisual(slide, family, data, area, tokens, lang) {
  const component =
    family === 'dashboard' && items((data || {}).series).length
      ? addChartWithTakeaway
      : COMPONENTS[family];
  if (!component) throw new RangeError(`Unknown visual layout family: ${family}`);
  return component(slide, data || {}, area, tokens, lang);
}

function renderVisualSpec(slide, visual, family, area, tokens, lang) {
  const normalized = visual && typeof visual === 'object' ? visual : {};
  const data = {
    ...(normalized.details && typeof normalized.details === 'object' ? normalized.details : {}),
    ...Object.fromEntries(
      ['asset', 'alt_text', 'purpose', 'type']
        .filter((key) => normalized[key] !== undefined)
        .map((key) => [key, normalized[key]]),
    ),
  };
  return renderVisual(slide, family, data, area, tokens, lang);
}

module.exports = {
  addAnnotatedVisual,
  addArchitecture,
  addChartWithTakeaway,
  addComparison,
  addStyledTable,
  addMatrix,
  addMetricDashboard,
  addProcessFlow,
  addQuotePanel,
  addReferenceList,
  addSectionHero,
  addSummary,
  addTimeline,
  renderVisual,
  renderVisualSpec,
};
