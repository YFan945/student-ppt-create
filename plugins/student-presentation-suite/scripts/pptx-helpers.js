/**
 * 共享 pptxgenjs 布局辅助函数。
 *
 * 生成的 deck.js 通过以下方式引入：
 *   const H = require("pptx-helpers");
 *
 * run_with_pptxgenjs.js 会自动将 scripts/ 目录加入 NODE_PATH。
 */

// ── 单位常量 ──────────────────────────────────────────────

const CM_PER_INCH = 2.54;

// 16:9 幻灯片默认尺寸（英寸）
const SLIDE_W_IN = 10;
const SLIDE_H_IN = 5.625;

// pptxgenjs 实例工厂 — 顶层 require 不会导致循环依赖
const _pptxgen = require('pptxgenjs');
const _shapeType = new _pptxgen().ShapeType;

// ── Token 辅助 ────────────────────────────────────────────

/**
 * 从 tokens 中取指定角色的 6 位十六进制颜色（pptxgenjs 不接受 # 前缀）。
 * @param {object} tokens - resolve_design_tokens() 的输出
 * @param {string} role - "canvas" | "surface" | "primary_text" | "secondary_text" | "primary_accent" | "secondary_accent"
 * @returns {string}
 */
function color(tokens, role) {
  const hex = (tokens.palette && tokens.palette[role]) || '000000';
  return String(hex).replace(/^#/, '').slice(0, 6).toUpperCase();
}

/**
 * Return page-scoped tokens with a complete light or dark palette selected.
 * Pass the returned object to every helper and visual component on that page.
 * @param {object} tokens
 * @param {"light"|"dark"} mode
 * @returns {object}
 */
function paletteMode(tokens, mode) {
  const normalized = String(mode || 'light').toLowerCase();
  if (!['light', 'dark'].includes(normalized)) {
    throw new RangeError(`Unknown palette mode: ${mode}`);
  }
  if (normalized === 'dark' && !tokens.dark_palette) {
    throw new RangeError('Dark palette mode requires tokens.dark_palette.');
  }
  const selected = normalized === 'dark' ? tokens.dark_palette : tokens.palette;
  return {
    ...tokens,
    palette: { ...(selected || {}) },
    palette_mode: normalized,
  };
}

/**
 * 根据语言选择字号。
 * @param {object} tokens
 * @param {string} lang - "chinese" | "english" | "bilingual"
 * @returns {{ title: number, body: number }}
 */
function fontSizeScale(tokens, lang) {
  const t = tokens.typography || {};
  const isCJK = lang === 'chinese' || lang === 'bilingual';
  const body = isCJK ? t.body_cjk_min_pt || 22 : t.body_latin_min_pt || 20;
  // 官方规范：CJK 正文下限 22pt，页面标题必须 ≥32pt 才能满足 1.45× 层级门禁。
  // 早期 defaults 给的是 24pt，与正文 22pt 仅差 2pt，导致层级塌陷。
  const title = t.title_min_pt || Math.max(32, Math.round(body * 1.45));
  return {
    title,
    // 陈述/小标题：标题与正文之间的中间档，避免两者之间无过渡。
    subtitle: t.subtitle_min_pt || Math.max(Math.round(title * 0.8), body + 2),
    body,
    titleMax: t.title_max_pt || Math.max(44, title + 8),
    bodyMax: t.body_max_pt || (isCJK ? 26 : 24),
    label: t.label_min_pt || 16,
    caption: t.caption_min_pt || 11,
  };
}

// 官方 pptx skill 安全字体白名单：这些字体在 LibreOffice QA 与 Office 中
// 宽度一致，可信任 text-fit 检查。绝不默认 Aptos。
const SAFE_TITLE_FONTS = [
  'Cambria',
  'Bookman Old Style',
  'Century Schoolbook',
  'Times New Roman',
  'Arial',
  'Calibri',
  'Courier New',
];
const SAFE_BODY_FONTS = ['Calibri', 'Arial', 'Times New Roman', 'Cambria', 'Courier New'];
// 中文字体白名单：Windows/Office 环境随系统或 Office 附带，LibreOffice QA 环境可回落。
// 东亚字形由 <a:ea> typeface 控制（pptx_tool.py cjk-fonts 后处理写入），
// 这里的名字只用于生成映射与文档。
const SAFE_CJK_TITLE_FONTS = ['Microsoft YaHei', 'SimHei', 'DengXian', 'KaiTi', 'SimSun'];
const SAFE_CJK_BODY_FONTS = [
  'Microsoft YaHei',
  'DengXian',
  'DengXian Light',
  'SimSun',
  'FangSong',
  'KaiTi',
];

/**
 * 选中风格的字体族，强制落到官方安全字体。
 * @param {object} tokens
 * @returns {{ title: string, body: string, cjkTitle: string, cjkBody: string }}
 */
function fontFamily(tokens) {
  const t = tokens.typography || {};
  const pick = (value, candidates, fallback) =>
    candidates.includes(String(value || '')) ? String(value) : fallback;
  return {
    title: pick(t.title_font, SAFE_TITLE_FONTS, 'Cambria'),
    body: pick(t.body_font, SAFE_BODY_FONTS, 'Calibri'),
    cjkTitle: pick(t.cjk_title_font, SAFE_CJK_TITLE_FONTS, 'Microsoft YaHei'),
    cjkBody: pick(t.cjk_body_font, SAFE_CJK_BODY_FONTS, 'Microsoft YaHei'),
  };
}

/**
 * 全幅纹理背景（dots/waves/grid），供 decor=expressive 的章节/封面页使用。
 * 颜色默认取当前盘的 primary_text（深色页自然为浅色纹理）。
 * @param {object} slide
 * @param {object} tokens paletteMode 后的 tokens
 * @param {{pattern?: 'dots'|'waves'|'grid', color?: string, opacity?: number}} [opts]
 */
function patternBackground(slide, tokens, opts = {}) {
  // 用 SVG <pattern> 平铺整页：直接拉伸小贴片会变成一个巨大的孤立图形。
  const name = ['dots', 'waves', 'grid'].includes(opts.pattern) ? opts.pattern : 'grid';
  const palette = tokens.palette || {};
  const color = String(
    opts.color || palette.primary_text || palette.primary_accent || '94A3B8',
  ).replace(/^#/, '');
  const opacity = Math.max(0.02, Math.min(0.25, Number(opts.opacity ?? 0.08)));
  const motifs = {
    dots: '<circle cx="8" cy="8" r="1.6"/>',
    waves: '<path d="M0 10c4-7 9 7 13 0s9 7 13 0" fill="none"/>',
    grid: '<path d="M0 0.5H32M0.5 0V32" fill="none"/>',
  };
  const W = Math.round(SLIDE_W_IN * 96);
  const Ht = Math.round(SLIDE_H_IN * 96);
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${Ht}" viewBox="0 0 ${W} ${Ht}">` +
    `<defs><pattern id="p" width="32" height="32" patternUnits="userSpaceOnUse">` +
    `<g fill="#${color}" stroke="#${color}" stroke-width="0.7">${motifs[name]}</g>` +
    `</pattern></defs>` +
    `<rect width="${W}" height="${Ht}" fill="url(#p)" opacity="${opacity}"/></svg>`;
  const data = `data:image/svg+xml;base64,${Buffer.from(svg, 'utf8').toString('base64')}`;
  slide.addImage({ data, x: 0, y: 0, w: SLIDE_W_IN, h: SLIDE_H_IN });
}

/**
 * 统一 soft-shadow token。阴影颜色取浅色盘的 primary_text（最深色），
 * 深色页返回 null（暗场上的外阴影既不可见也会产生脏边）。
 * @param {object} tokens
 * @param {object} [overrides] {enabled, color, blur, offset, angle, opacity}
 * @returns {object|null} pptxgenjs shadow options 或 null
 */
function softShadow(tokens, overrides = {}) {
  const effects = (tokens.effects && tokens.effects.soft_shadow) || {};
  if (effects.enabled === false || overrides.enabled === false) return null;
  const mode = tokens.palette_mode || 'light';
  if (mode !== 'light') return null;
  const palette = tokens.palette || {};
  return {
    type: 'outer',
    color: String(overrides.color || palette.primary_text || '0F172A').replace(/^#/, ''),
    blur: Number(overrides.blur ?? effects.blur_pt ?? 10),
    offset: Number(overrides.offset ?? effects.offset_pt ?? 4),
    angle: Number(overrides.angle ?? effects.angle_deg ?? 90),
    opacity: Number(overrides.opacity ?? effects.opacity ?? 0.16),
  };
}

// ── 几何计算 ──────────────────────────────────────────────

/**
 * 安全绘图区 (inches)。自动扣除 safe margin、标题区和页脚区。
 * @param {number} slideW - 幻灯片宽度 (inches)
 * @param {number} slideH - 幻灯片高度 (inches)
 * @param {object} tokens
 * @param {{ reserveTitle?: boolean }} opts
 * @returns {{ x: number, y: number, w: number, h: number }}
 */
function safeArea(slideW, slideH, tokens, opts) {
  const g = tokens.geometry || {};
  const marginPct = (g.safe_margin_pct || 6) / 100;
  const marginX = slideW * marginPct;
  const marginY = slideH * marginPct;
  const gap = spacing(tokens, 3);
  const reserveTitle = !opts || opts.reserveTitle !== false;
  const titleZone = (slideH * (g.title_zone_pct || 16)) / 100;
  const footerZone = Math.max(marginY, (slideH * (g.footer_zone_pct || 5)) / 100);
  const titleHeight = reserveTitle ? Math.max(0.6, titleZone - gap * 2) : 0;
  const contentY = reserveTitle ? marginY + titleHeight + gap : marginY;
  const contentHeight = slideH - contentY - footerZone;
  if (slideW - marginX * 2 <= 0 || contentHeight <= 0) {
    throw new RangeError('Design tokens leave no usable slide safe area.');
  }

  return {
    x: marginX,
    y: contentY,
    w: slideW - marginX * 2,
    h: contentHeight,
    slideW,
    slideH,
    titleBox: reserveTitle
      ? { x: marginX, y: marginY, w: slideW - marginX * 2, h: titleHeight }
      : null,
  };
}

/**
 * 页脚文本框安全区 (inches)。返回值始终位于幻灯片边界内。
 * @param {number} slideW
 * @param {number} slideH
 * @param {object} tokens
 * @returns {{ x: number, y: number, w: number, h: number }}
 */
function footerArea(slideW, slideH, tokens) {
  const g = tokens.geometry || {};
  const marginPct = (g.safe_margin_pct || 6) / 100;
  const marginX = slideW * marginPct;
  const marginY = slideH * marginPct;
  const footerZone = Math.max(marginY, (slideH * (g.footer_zone_pct || 5)) / 100);
  const height = Math.min(0.28, footerZone);
  return {
    x: marginX,
    y: slideH - footerZone,
    w: slideW - marginX * 2,
    h: height,
  };
}

/**
 * 将 tokens spacing scale 转为 inches。
 * @param {object} tokens
 * @param {number} step - 间距档位 (1-6)
 * @returns {number} inches
 */
function spacing(tokens, step) {
  const scale = (tokens.geometry && tokens.geometry.spacing_scale_pt) || [6, 12, 18, 24, 36, 48];
  const pt = scale[Math.min(step - 1, scale.length - 1)] || 12;
  return pt / 72; // pt → inches
}

/**
 * 圆角半径 (inches)。
 * @param {object} tokens
 * @returns {number}
 */
function cornerRadius(tokens) {
  const pt = (tokens.geometry && tokens.geometry.corner_radius_pt) || 8;
  return pt / 72;
}

// ── 文字适配估算 ──────────────────────────────────────────

/**
 * 估算文本在给定盒子里需要的行数。
 * 中文 ≈ 字号×0.035cm/字，英文 ≈ 字号×0.021cm/字
 * @param {string} text - 文本内容
 * @param {number} boxW - 盒子宽度 (inches)
 * @param {number} fontSize - 字号 (pt)
 * @param {boolean} isCJK - 是否 CJK 为主
 * @returns {{ lines: number, fillRatio: number, overflow: boolean }}
 */
function estimateTextFit(text, boxW, boxH, fontSize, isCJK) {
  // 零尺寸盒子无法计算填充率
  if (boxW <= 0 || boxH <= 0) {
    return {
      lines: text ? 1 : 0,
      fillRatio: text ? Number.POSITIVE_INFINITY : 0,
      overflow: Boolean(text),
    };
  }
  const boxWCm = boxW * CM_PER_INCH;
  const boxHCm = boxH * CM_PER_INCH;
  const charWidthCm = fontSize * (isCJK ? 0.035 : 0.021);
  const charsPerLine = Math.max(1, Math.floor(boxWCm / charWidthCm));

  const paragraphs = text.split('\n');
  let totalLines = 0;
  for (const p of paragraphs) {
    totalLines += Math.max(1, Math.ceil(p.length / charsPerLine));
  }
  const lineHeightCm = ((fontSize * 1.4) / 72) * CM_PER_INCH;
  const textHeightCm = totalLines * lineHeightCm;
  const fillRatio = textHeightCm / boxHCm;

  return {
    lines: totalLines,
    fillRatio: Math.round(fillRatio * 100) / 100,
    overflow: fillRatio > 0.85,
  };
}

/**
 * 在写入文本框前估算适配情况。溢出时仅警告并返回 fit（含 overflow），
 * 不再阻断生成——对齐官方方式：溢出靠 QA 阶段逐页视觉检查兜底。
 */
function assertTextFits(text, boxW, boxH, fontSize, isCJK, label) {
  const fit = estimateTextFit(String(text || ''), boxW, boxH, fontSize, isCJK);
  if (fit.overflow) {
    // eslint-disable-next-line no-console
    console.warn(
      `${label || '文本框'}存在溢出风险：${fit.lines} 行，填充率 ${fit.fillRatio}。` +
        '请在 QA 逐页检查中确认，必要时拆分幻灯片、精简内容或扩大文本框。',
    );
  }
  return fit;
}

function rolePolicy(tokens, lang, role, options = {}) {
  const sizes = fontSizeScale(tokens, lang);
  const normalized = String(role || 'body');
  const table = {
    title: {
      min: sizes.title,
      max: sizes.titleMax,
      align: options.titleAlign || 'left',
      valign: 'mid',
      margin: 0,
    },
    body: { min: sizes.body, max: sizes.bodyMax, align: 'left', valign: 'top' },
    list: { min: sizes.body, max: sizes.bodyMax, align: 'left', valign: 'top' },
    reference: { min: sizes.caption, max: 12, align: 'left', valign: 'top' },
    caption: { min: sizes.caption, max: 12, align: 'left', valign: 'mid' },
    source: { min: sizes.caption, max: 12, align: 'left', valign: 'mid' },
    label: { min: sizes.label, max: 20, align: 'center', valign: 'mid', maxFillRatio: 0.85 },
    node: {
      min: Math.max(16, sizes.label),
      max: 21,
      align: 'center',
      valign: 'mid',
      maxFillRatio: 0.85,
    },
    kpi: {
      min: Math.max(16, sizes.label),
      max: 24,
      align: 'center',
      valign: 'mid',
      maxFillRatio: 0.85,
    },
    quote: {
      min: Math.max(18, sizes.label),
      max: 30,
      align: options.analysis ? 'left' : 'center',
      valign: 'mid',
    },
  };
  const policy = { ...(table[normalized] || table.body), ...options, role: normalized };
  // 调用方显式传入的字号必须生效。
  // 旧实现在 addText() 里用 `fontSize: fit.fontSize` 覆盖了调用方的 fontSize，
  // 导致"传了等于没传"且不报错（Hero 标题请求 32pt 实际只拿到 26pt）。
  // 这里把请求值作为上限，放不下时仍允许下调，因此不会产生新的失败。
  const requested = Number(policy.fontSize);
  if (Number.isFinite(requested) && requested > 0) {
    policy.max = requested;
    policy.min = Math.min(Number(policy.min) || requested, requested);
  }
  return policy;
}

/** Choose the largest readable size that fits. Never shrinks below the role floor. */
function fitText(text, box, policy = {}) {
  const min = Number(policy.min || policy.minFontSize || 10);
  const max = Math.max(min, Number(policy.max || policy.maxFontSize || min));
  const margin = policy.margin === undefined ? 8 : policy.margin;
  const margins = Array.isArray(margin) ? margin : [margin, margin, margin, margin];
  const usableW = box.w - ((margins[1] || 0) + (margins[3] || 0)) / 72;
  const usableH = box.h - ((margins[0] || 0) + (margins[2] || 0)) / 72;
  const plain = plainText(text);
  const isCJK = policy.isCJK ?? /[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]/u.test(plain);
  const maxFillRatio = Number(policy.maxFillRatio || 0.85);
  for (let size = max; size >= min; size -= 1) {
    const fit = estimateTextFit(plain, usableW, usableH, size, isCJK);
    if (fit.fillRatio <= maxFillRatio)
      return { ...fit, overflow: false, fits: true, fontSize: size, margin: margins };
  }
  const fit = estimateTextFit(plain, usableW, usableH, min, isCJK);
  return { ...fit, fits: false, fontSize: min, margin: margins };
}

function preflightText(text, box, tokens, lang, role, options = {}) {
  const policy = rolePolicy(tokens, lang, role, options);
  const fit = fitText(text, box, policy);
  return {
    ok: fit.fits,
    role: policy.role,
    box: { ...box },
    fontSize: fit.fontSize,
    lines: fit.lines,
    fillRatio: fit.fillRatio,
    resolution: fit.fits ? 'render' : 'expand-change-layout-compress-or-split',
  };
}

// 允许做"平衡换行"的角色：这些角色的盒子宽度可以微调而不影响版面骨架。
const BALANCE_ROLES = new Set([
  'title',
  'body',
  'list',
  'label',
  'quote',
  'kpi',
  'node',
  'reference',
]);

/**
 * 估算末行长度，必要时收窄盒子让各行长度均衡。
 *
 * 旧行为：estimateTextFit 只管"放不放得下"，从不管末行剩几个字。
 * 于是标题长度略超每行容量时，第二行只剩一两个字（孤字行）。
 * 这里不改变文本（插入 \n 会破坏"claim 必须出现在渲染文本"一类的门禁），
 * 而是把盒子收窄到 ceil(字数/行数) 的宽度，让换行点自然前移。
 * @returns {object|null} 收窄后的盒子，或 null（无需调整）
 */
function balancedBox(text, box, policy) {
  if (policy.balance === false || !BALANCE_ROLES.has(policy.role)) return null;
  const plain = plainText(text);
  if (!plain) return null;
  const isCJK = policy.isCJK ?? /[぀-ヿ㐀-鿿豈-﫿]/u.test(plain);
  // 拉丁文本按单词换行，收窄盒子无法精确控制断点，只在 CJK 场景介入。
  if (!isCJK) return null;
  const min = Number(policy.min || policy.minFontSize || 10);
  const margin = policy.margin === undefined ? 8 : policy.margin;
  const margins = Array.isArray(margin) ? margin : [margin, margin, margin, margin];
  const usableW = box.w - ((margins[1] || 0) + (margins[3] || 0)) / 72;
  const charWidthCm = min * 0.035;
  const charsPerLine = Math.max(1, Math.floor((usableW * CM_PER_INCH) / charWidthCm));
  const length = plain.length;
  if (charsPerLine < 6 || length <= charsPerLine) return null;
  const lines = Math.ceil(length / charsPerLine);
  if (lines < 2) return null;
  const last = length - charsPerLine * (lines - 1);
  const orphanLimit = Math.max(2, Math.round(charsPerLine * 0.25));
  if (last >= orphanLimit) return null;
  const target = Math.max(4, Math.ceil(length / lines));
  const narrowedW = Math.min(usableW, (target * charWidthCm) / CM_PER_INCH);
  if (narrowedW >= usableW - 0.01) return null;
  const newW = box.w - (usableW - narrowedW);
  return { x: box.x, y: box.y, w: newW, h: box.h };
}

/**
 * 决定最终文本盒子：先按原盒子试排，若末行会出现孤字且收窄后仍放得下，则收窄。
 */
function resolveTextPlacement(text, box, policy) {
  const fit = fitText(text, box, policy);
  if (!fit.fits) return { box, fit };
  const narrowed = balancedBox(text, box, policy);
  if (!narrowed) return { box, fit };
  const narrowedFit = fitText(text, narrowed, policy);
  if (!narrowedFit.fits || narrowedFit.lines > fit.lines + 1) return { box, fit };
  // 居中文本收窄后要保持视觉居中，不能让整块偏左。
  const centered = (policy.align || '') === 'center';
  return {
    box: centered ? { ...narrowed, x: box.x + (box.w - narrowed.w) / 2 } : narrowed,
    fit: narrowedFit,
  };
}

function addFittedText(slide, text, box, tokens, lang, role, options = {}) {
  const policy = rolePolicy(tokens, lang, role, options);
  const placement = resolveTextPlacement(text, box, policy);
  const fit = placement.fit;
  const textBox = placement.box;
  if (!fit.fits) {
    throw new RangeError(
      `${options.label || policy.role} cannot fit at ${fit.fontSize}pt; expand the region, change the layout, compress the copy, or split the slide.`,
    );
  }
  const shortReadingText = ['body', 'list'].includes(policy.role) && fit.fillRatio <= 0.45;
  const fonts = fontFamily(tokens);
  const pptxOptions = { ...options };
  for (const key of [
    'min',
    'max',
    'minFontSize',
    'maxFontSize',
    'label',
    'colorRole',
    'titleAlign',
    'analysis',
    'isCJK',
    'maxFillRatio',
    'balance',
  ]) {
    delete pptxOptions[key];
  }
  return slide.addText(text, {
    ...pptxOptions,
    x: textBox.x,
    y: textBox.y,
    w: textBox.w,
    h: textBox.h,
    fontSize: fit.fontSize,
    fontFace: pptxOptions.fontFace || (policy.role === 'title' ? fonts.title : fonts.body),
    color: pptxOptions.color || color(tokens, options.colorRole || 'primary_text'),
    align: pptxOptions.align || policy.align,
    valign: pptxOptions.valign || (shortReadingText ? 'mid' : policy.valign),
    margin: pptxOptions.margin === undefined ? (policy.margin ?? 8) : pptxOptions.margin,
  });
}

function plainText(text) {
  if (!Array.isArray(text)) {
    return String(text || '');
  }
  return text
    .map((item) => (typeof item === 'string' ? item : String((item && item.text) || '')))
    .join('');
}

/**
 * 将安全区切成等宽等高网格，避免生成脚本重复手算坐标。
 */
function gridLayout(area, columns, rows, opts) {
  if (!Number.isInteger(columns) || columns < 1 || !Number.isInteger(rows) || rows < 1) {
    throw new RangeError('gridLayout columns/rows must be positive integers.');
  }
  const columnGap = (opts && opts.columnGap) || 0;
  const rowGap = (opts && opts.rowGap) || 0;
  const cellW = (area.w - columnGap * (columns - 1)) / columns;
  const cellH = (area.h - rowGap * (rows - 1)) / rows;
  if (cellW <= 0 || cellH <= 0) {
    throw new RangeError('Grid gaps leave no usable cell area.');
  }
  const cells = [];
  for (let row = 0; row < rows; row += 1) {
    for (let column = 0; column < columns; column += 1) {
      cells.push({
        x: area.x + column * (cellW + columnGap),
        y: area.y + row * (cellH + rowGap),
        w: cellW,
        h: cellH,
        row,
        column,
      });
    }
  }
  return cells;
}

/**
 * 不对称列布局：按权重分配横向空间（对比组件的去等宽化原语）。
 * weights 缺省/非法时退化为等宽（与 gridLayout 单行一致，向后兼容）。
 * @param {{ x: number, y: number, w: number, h: number }} area
 * @param {number} count
 * @param {number[]|undefined} weights 每列权重（正值）
 * @param {number} gap 列间距（英寸）
 * @returns {Array<{x: number, y: number, w: number, h: number}>}
 */
function weightedColumns(area, count, weights, gap) {
  if (!Number.isInteger(count) || count < 1) {
    throw new RangeError('weightedColumns count must be a positive integer.');
  }
  const valid =
    Array.isArray(weights) && weights.length === count && weights.every((w) => Number(w) > 0);
  const ws = valid ? weights.map(Number) : Array(count).fill(1);
  const total = ws.reduce((a, b) => a + b, 0);
  // gap 缺省时旧实现算出 NaN，而 `NaN <= 0` 为 false，守卫形同虚设，
  // NaN 坐标会被直接写进 OOXML。这里补默认值并对结果做有限性校验。
  const gutter = Number.isFinite(gap) ? gap : 0;
  const usable = area.w - gutter * (count - 1);
  if (!Number.isFinite(usable) || usable <= 0) {
    throw new RangeError('weightedColumns gaps leave no usable width.');
  }
  const cells = [];
  let x = area.x;
  ws.forEach((w) => {
    const cellW = (usable * w) / total;
    cells.push({ x, y: area.y, w: cellW, h: area.h });
    x += cellW + gutter;
  });
  return cells;
}

// ── Box 创建辅助 ─────────────────────────────────────────

/**
 * 在安全区域内添加标题文本框。
 * @param {object} slide - pptxgen slide 对象
 * @param {string} text
 * @param {{ x: number, y: number, w: number, h: number }} area - safeArea() 返回
 * @param {object} tokens
 * @param {string} lang
 * @returns {object} 创建的 text 对象
 */
function addTitle(slide, text, area, tokens, lang) {
  const sizes = fontSizeScale(tokens, lang);
  const fonts = fontFamily(tokens);
  const fallbackTop =
    (area.slideH || SLIDE_H_IN) * (((tokens.geometry || {}).safe_margin_pct || 6) / 100);
  const titleBox = area.titleBox || {
    x: area.x,
    y: fallbackTop,
    w: area.w,
    // area.y === fallbackTop（reserveTitle: false）时旧实现算出负高度，
    // estimateTextFit 随即判溢出并 100% 抛错。这里兜一个最小可用高度。
    h: Math.max(0.4, area.y - fallbackTop - spacing(tokens, 1)),
  };
  return addFittedText(slide, text, titleBox, tokens, lang, 'title', {
    min: sizes.title,
    max: sizes.titleMax,
    fontFace: fonts.title,
    bold: true,
    margin: 0,
    label: '标题',
  });
}

/**
 * 在安全区域内添加正文文本框。
 * @param {object} slide
 * @param {string|string[]} text
 * @param {{ x: number, y: number, w: number, h: number }} area
 * @param {object} tokens
 * @param {string} lang
 * @param {{ bullet?: boolean, spacing?: number }} opts
 * @returns {object}
 */
function addBody(slide, text, area, tokens, lang, opts) {
  const textStr = Array.isArray(text) ? text.join('\n') : text;
  const options = {
    lineSpacingMultiple: 1.3,
    paraSpaceAfter:
      (opts && opts.spacing ? spacing(tokens, opts.spacing) : spacing(tokens, 1)) * 72,
  };

  if (opts && opts.bullet !== false) {
    options.bullet = true;
  }

  return addFittedText(slide, textStr, area, tokens, lang, 'body', { ...options, label: '正文' });
}

/**
 * 添加经过字号下限和溢出检查的通用文本框。
 */
function addTextBox(slide, text, box, tokens, lang, opts) {
  if (opts && opts.role) return addFittedText(slide, text, box, tokens, lang, opts.role, opts);
  const sizes = fontSizeScale(tokens, lang);
  const fonts = fontFamily(tokens);
  const isCJK = lang === 'chinese' || lang === 'bilingual';
  const requestedSize = (opts && opts.fontSize) || sizes.body;
  const fontSize = Math.max(requestedSize, sizes.body);
  const margin = opts && opts.margin !== undefined ? opts.margin : 16;
  const margins = Array.isArray(margin) ? margin : [margin, margin, margin, margin];
  const usableW = box.w - ((margins[1] || 0) + (margins[3] || 0)) / 72;
  const usableH = box.h - ((margins[0] || 0) + (margins[2] || 0)) / 72;
  assertTextFits(
    plainText(text),
    usableW,
    usableH,
    fontSize,
    isCJK,
    (opts && opts.label) || '文本框',
  );
  return slide.addText(text, {
    ...(opts || {}),
    x: box.x,
    y: box.y,
    w: box.w,
    h: box.h,
    fontSize,
    fontFace: (opts && opts.fontFace) || fonts.body,
    color: (opts && opts.color) || color(tokens, 'primary_text'),
    align: (opts && opts.align) || 'left',
    valign: (opts && opts.valign) || 'top',
    margin,
  });
}

/**
 * 添加始终位于画布内的页脚。页脚允许使用 10pt 以上辅助字号。
 */
function addFooter(slide, text, tokens, opts) {
  const slideW = (opts && opts.slideW) || SLIDE_W_IN;
  const slideH = (opts && opts.slideH) || SLIDE_H_IN;
  const box = footerArea(slideW, slideH, tokens);
  const fontSize = Math.max((opts && opts.fontSize) || 11, 10);
  assertTextFits(plainText(text), box.w, box.h, fontSize, false, '页脚');
  return slide.addText(text, {
    ...box,
    fontSize,
    fontFace: (opts && opts.fontFace) || fontFamily(tokens).body,
    color: (opts && opts.color) || color(tokens, 'secondary_text'),
    align: (opts && opts.align) || 'right',
    valign: 'mid',
    margin: 0,
  });
}

/**
 * 添加强调色卡片（圆角矩形 + 文字）。
 * @param {object} slide
 * @param {string} text
 * @param {{ x: number, y: number, w: number, h: number }} box
 * @param {object} tokens
 * @returns {{ shape: object, text: object }}
 */
function addAccentCard(slide, text, box, tokens) {
  const radius = cornerRadius(tokens);
  const padding = spacing(tokens, 2);
  // 与 addLabel 保持一致：小盒子上 padding 会把尺寸吃成负数，必须兜下限。
  const textWidth = Math.max(0.1, box.w - padding * 2);
  const textHeight = Math.max(0.1, box.h - padding * 2);
  const isCJK = /[\u3400-\u9fff]/u.test(String(text || ''));
  // 走统一的字号层级，避免这里再抄一份 22/20 兜底常量导致两处漂移。
  const fontSize = fontSizeScale(tokens, isCJK ? 'chinese' : 'english').body;
  assertTextFits(text, textWidth, textHeight, fontSize, isCJK, '卡片文本');
  const shape = slide.addShape(_shapeType.roundRect, {
    x: box.x,
    y: box.y,
    w: box.w,
    h: box.h,
    fill: { color: color(tokens, 'surface') },
    line: {
      color: color(tokens, 'primary_accent'),
      width: (tokens.lines && tokens.lines.standard_pt) || 1.25,
    },
    rectRadius: radius,
  });
  const textObj = slide.addText(text, {
    x: box.x + padding,
    y: box.y + padding,
    w: textWidth,
    h: textHeight,
    fontSize,
    fontFace: fontFamily(tokens).body,
    color: color(tokens, 'primary_text'),
    valign: 'mid',
  });
  return { shape, text: textObj };
}

/**
 * 添加分隔线。
 * @param {object} slide
 * @param {number} x
 * @param {number} y
 * @param {number} w
 * @param {object} tokens
 * @param {"hairline"|"standard"|"emphasis"|"section"} weight
 * @returns {object}
 */
function addDivider(slide, x, y, w, tokens, weight) {
  const linePt =
    (tokens.lines && tokens.lines[`${weight}_pt`]) ||
    (tokens.lines && tokens.lines.standard_pt) ||
    1.25;
  return slide.addShape(_shapeType.line, {
    x,
    y,
    w,
    h: 0,
    line: { color: color(tokens, 'secondary_text'), width: linePt },
  });
}

/**
 * 给 slide 设置背景色（canvas 角色落到背景）。
 * 设置页面背景。生成脚本必须逐页调用。
 * dark=true 仅为包含 dark_palette 的旧项目保留兼容性；正式轻量风格
 * 直接由调用方按背景参考选择并校验文字颜色。
 * @param {object} slide - pptxgen slide 对象
 * @param {object} tokens
 * @param {boolean} [dark] - true 用 dark_palette.canvas，false/缺省用 canvas
 * @returns {object} slide
 */
function addBackground(slide, tokens, dark) {
  const pageTokens = dark === true ? paletteMode(tokens, 'dark') : tokens;
  slide.background = { color: color(pageTokens, 'canvas') };
  return slide;
}

/**
 * Explicit compatibility helper for the selected reference's optional SVG motif.
 * Nothing calls this automatically; callers must not place it over content.
 * @param {object} slide
 * @param {{x:number,y:number,w:number,h:number}} area
 * @param {object} tokens
 * @param {"restrained"|"standard"|"expressive"} [intensity]
 */
function addStyleMotif(slide, area, tokens, intensity = 'standard') {
  const name = tokens.svg_reference?.name;
  if (!name || String(name).toLowerCase() === 'none') return slide;
  const SVG = require('pptx-svg-library');
  if (!SVG.CORNER_SETS[name] && !SVG.LEGACY_CORNER_ALIASES[name]) return slide;
  const scale = intensity === 'expressive' ? 0.3 : intensity === 'restrained' ? 0.17 : 0.23;
  const w = area.w * scale;
  const h = Math.min(area.h * 0.42, w);
  SVG.addCornerDecoration(slide, name, { x: area.x + area.w - w, y: area.y, w, h }, tokens, {
    transparency: intensity === 'restrained' ? 28 : 10,
  });
  return slide;
}

// ── 全局主题 ──────────────────────────────────────────────

/**
 * 将 design tokens 应用到 pptxgen 实例的全局默认值。
 * 背景不是全局属性：每页必须用 addBackground()（或 slide.background）显式设置，
 * 深色封面/浅色内容对比由调用处决定。
 * @param {object} pptx - new pptxgen() 实例
 * @param {object} tokens
 * @param {string} lang
 * @param {{ slideW?: number, slideH?: number }} [opts] - 可选幻灯片尺寸覆盖
 */
function applyTokens(pptx, tokens, lang, opts) {
  const sizes = fontSizeScale(tokens, lang);
  const fonts = fontFamily(tokens);
  const slideW = (opts && opts.slideW) || SLIDE_W_IN;
  const slideH = (opts && opts.slideH) || SLIDE_H_IN;

  // 设置幻灯片尺寸（默认 16:9）
  pptx.defineLayout({ name: 'STUDENT_WIDE', width: slideW, height: slideH });
  pptx.layout = 'STUDENT_WIDE';

  // 默认文字样式
  pptx.theme = {
    fontFace: fonts.body,
    fontSize: sizes.body,
    color: color(tokens, 'primary_text'),
  };
}

// ── 导出 ──────────────────────────────────────────────────

module.exports = {
  // 常量
  SLIDE_W_IN,
  SLIDE_H_IN,

  // Token 辅助
  color,
  paletteMode,
  fontSizeScale,
  fontFamily,
  softShadow,
  patternBackground,

  // 几何计算
  safeArea,
  footerArea,
  gridLayout,
  weightedColumns,
  spacing,
  cornerRadius,

  // 文字适配
  estimateTextFit,
  assertTextFits,
  fitText,
  preflightText,
  addFittedText,
  plainText,

  // Box 创建
  addTitle,
  addBody,
  addTextBox,
  addFooter,
  addAccentCard,
  addDivider,

  // 背景
  addBackground,
  addStyleMotif,

  // 全局
  applyTokens,
};
