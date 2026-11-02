'use strict';

const H = require('./pptx-helpers.js');
const L = require('./pptx-layouts.js');

function captureSlide(ctx) {
  const slide = ctx.slide;
  // Keep the native table API, including automatic sizing and merged cells.
  // Its outer box is useful context; native table text is read back from OOXML.
  if (typeof slide.addTable === 'function') {
    const originalTable = slide.addTable.bind(slide);
    slide.addTable = (rows, options = {}) => {
      // PptxGenJS uses lowercase span names. Accept the common camelCase
      // aliases too, without replacing native cells with separately drawn boxes.
      const nativeRows = rows.map((row) =>
        row.map((cell) => {
          if (!cell || typeof cell !== 'object' || Array.isArray(cell)) return cell;
          const opts = cell.options || {};
          return {
            ...cell,
            options: {
              ...opts,
              colspan: opts.colspan ?? opts.colSpan,
              rowspan: opts.rowspan ?? opts.rowSpan,
            },
          };
        }),
      );
      const nativeOptions = { ...options };
      // Zero-height native rows depend on viewer auto-sizing (LibreOffice can
      // misplace them). Derive omitted row heights from text metrics instead
      // of requiring callers to fill geometry or banning merged tables.
      if (nativeOptions.rowH === undefined && nativeOptions.h === undefined) {
        const columns = Math.max(
          ...nativeRows.map((row) => row.reduce((n, cell) => n + (cell?.options?.colspan || 1), 0)),
        );
        const tableW = nativeOptions.w ?? (ctx.registry.options?.slideW || 10) - 1;
        const widths = Array.isArray(nativeOptions.colW)
          ? nativeOptions.colW
          : Array(columns).fill(nativeOptions.colW || tableW / columns);
        nativeOptions.rowH = nativeRows.map((row) => {
          let column = 0;
          return Math.max(
            ...row.map((cell) => {
              const opts = cell?.options || {};
              const span = opts.colspan || 1;
              const width = widths
                .slice(column, column + span)
                .reduce((sum, value) => sum + value, 0);
              column += span;
              const rawMargin = opts.margin ?? nativeOptions.margin ?? [0.05, 0.1, 0.05, 0.1];
              const margins = Array.isArray(rawMargin) ? rawMargin : Array(4).fill(rawMargin);
              const pointMargins = margins[0] >= 1 ? margins : margins.map((value) => value * 72);
              const policy = H.rolePolicy(ctx.tokens, ctx.lang || 'chinese', 'body', {
                ...nativeOptions,
                ...opts,
                fontSize: opts.fontSize ?? nativeOptions.fontSize ?? 12,
                margin: pointMargins,
              });
              const fit = H.fitText(cell?.text ?? cell, { x: 0, y: 0, w: width, h: 1000 }, policy);
              const margin = policy.margin;
              const vertical = Array.isArray(margin)
                ? Number(margin[0] || 0) + Number(margin[2] || 0)
                : 2 * Number(margin || 0);
              return (fit.requiredH + vertical / 72) / (opts.rowspan || 1);
            }),
          );
        });
      }
      const recorded = { ...nativeOptions };
      const result = originalTable(nativeRows, nativeOptions);
      ctx.nativeObjects = (ctx.nativeObjects || 0) + 1;
      const height =
        recorded.h ??
        (Array.isArray(recorded.rowH)
          ? recorded.rowH.reduce((sum, value) => sum + value, 0)
          : Number(recorded.rowH) * nativeRows.length);
      if (['x', 'y', 'w'].every((key) => Number.isFinite(recorded[key])) && Number.isFinite(height))
        ctx.registry.register(ctx.n, { type: 'table', ...recorded, h: height });
      return result;
    };
  }
  for (const [method, type] of [
    ['addText', 'text'],
    ['addShape', 'shape'],
    ['addImage', 'image'],
    ['addChart', 'chart'],
  ]) {
    if (typeof slide[method] !== 'function') continue;
    const original = slide[method].bind(slide);
    slide[method] = (...args) => {
      const options = { ...(method === 'addImage' ? args[0] : args.at(-1) || {}) };
      const text = type === 'text' ? H.plainText(args[0]) : undefined;
      if (type === 'text' && !options._textLayout) {
        const policy = H.rolePolicy(
          ctx.tokens,
          ctx.lang || 'chinese',
          options.role || 'body',
          options,
        );
        const layout = H.fitText(args[0], options, policy);
        if (
          options.positionMixedText === true &&
          /[\u3400-\u9fff\uff01-\uff60]/u.test(text) &&
          /[A-Za-z0-9]/.test(text)
        ) {
          H.addPositionedText(
            slide,
            args[0],
            options,
            ctx.tokens,
            ctx.lang || 'chinese',
            options.role || 'body',
            { ...options, fontSize: layout.fontSize, cjkFontFace: policy.cjkFontFace },
          );
          return slide;
        }
        args[0] = layout.richText;
        options._textLayout = { sourceText: text, ...layout };
        options.fontSize = layout.fontSize;
        options.fontFace = policy.fontFace;
        options.cjkFontFace = options.cjkFontFace || policy.cjkFontFace;
        options.margin = layout.margin;
        options.lineSpacing = layout.lineHeightPt ?? layout.fontSize * 1.18;
        options.valign ??= 'top';
      }
      const isLine = method === 'addShape' && args[0] === 'line';
      const element = {
        type: isLine ? 'line' : type,
        shapeType: method === 'addShape' ? args[0] : undefined,
        ...options,
        text,
        textColors:
          type === 'text'
            ? Array.isArray(args[0])
              ? args[0]
                  .filter((run) => String(run.text || '').trim())
                  .map((run) => run.options?.color || options.color)
              : [options.color]
            : undefined,
        textSizes:
          type === 'text'
            ? Array.isArray(args[0])
              ? args[0]
                  .filter((run) => String(run.text || '').trim())
                  .map((run) => run.options?.fontSize ?? options.fontSize)
              : [options.fontSize]
            : undefined,
        textFonts:
          type === 'text'
            ? Array.isArray(args[0])
              ? args[0]
                  .filter((run) => String(run.text || '').trim())
                  .map((run) => run.options?.fontFace || options.fontFace)
              : [options.fontFace]
            : undefined,
        // Whether each collected run carries letters/digits/CJK (symbol-only
        // runs are excluded from font-mix counting downstream).
        textScriptFlags:
          type === 'text'
            ? Array.isArray(args[0])
              ? args[0]
                  .filter((run) => String(run.text || '').trim())
                  .map((run) => /[A-Za-z0-9぀-ヿ㐀-鿿豈-﫿]/u.test(String(run.text || '')))
              : [/[A-Za-z0-9぀-ヿ㐀-鿿豈-﫿]/u.test(text)]
            : undefined,
        // Role metadata for role-aware warnings; explicit textRole wins, bare
        // role (addFittedText channel) next, otherwise unknown. Never reaches
        // pptxgenjs — stripped from the forwarded options below.
        textRole: type === 'text' ? options.textRole || options.role || 'unknown' : undefined,
        decorative: Boolean(
          (type !== 'text' && (options.decorative || options.allowOverlap)) ||
          options._background ||
          (type !== 'text' &&
            options.x === 0 &&
            options.y === 0 &&
            options.w >= H.SLIDE_W_IN &&
            options.h >= H.SLIDE_H_IN),
        ),
      };
      // Native image sizing writes the viewport extent to OOXML, not the
      // scaled source extent. Register the same visible bounds as the viewer.
      if (method === 'addImage' && options.sizing) {
        element.w = options.sizing.w ?? options.w;
        element.h = options.sizing.h ?? options.h;
      }
      if (isLine)
        Object.assign(element, {
          x1: options.x,
          y1: options.y,
          x2: options.x + options.w,
          y2: options.y + options.h,
        });
      if (options._textLayout) {
        element.lineGeometry = options._textLayout.lineGeometry;
        element.text = options._textLayout.sourceText;
      }
      ctx.registry.register(ctx.n, element);
      const clean = { ...options };
      for (const key of [
        '_textLayout',
        '_background',
        'decorative',
        'allowOverlap',
        'role',
        'textRole',
        'logicalGroup',
        'logicalText',
        'logicalBox',
        'positionMixedText',
      ])
        delete clean[key];
      if (method === 'addImage') args[0] = clean;
      else args[args.length - 1] = clean;
      return original(...args);
    };
  }
}

function renderPage(ctx, mod) {
  if (!ctx.tokens.model_led) {
    if (typeof mod === 'function') mod(ctx);
    else L.renderDeclaredPage(ctx, mod);
    return;
  }
  const mode = ctx.designMode || ctx.tokens.design_freedom || 'auto';
  if (mod.typography) {
    const allowed = new Set([
      'title_pt',
      'cover_title_pt',
      'slide_title_pt',
      'statement_pt',
      'key_statement_pt',
      'stat_pt',
      'body_pt',
      'subtitle_pt',
      'caption_pt',
      'source_pt',
      'reference_pt',
      'label_pt',
      'node_pt',
      'kpi_pt',
      'quote_pt',
      'list_pt',
    ]);
    for (const [key, value] of Object.entries(mod.typography)) {
      if (!allowed.has(key)) throw new Error(`unknown page typography key: ${key}`);
      if (!Number.isFinite(value) || value <= 0)
        throw new Error(`page typography ${key} must be a finite positive number`);
    }
    const typography = { ...mod.typography };
    const title = mod.kind === 'cover' ? typography.cover_title_pt : typography.slide_title_pt;
    if (typography.title_pt === undefined && title !== undefined) typography.title_pt = title;
    if (typography.statement_pt === undefined && typography.key_statement_pt !== undefined)
      typography.statement_pt = typography.key_statement_pt;
    ctx.tokens = { ...ctx.tokens, typography: { ...ctx.tokens.typography, ...typography } };
  }
  if (mod.visual_language)
    ctx.tokens = {
      ...ctx.tokens,
      visual_language: { ...ctx.tokens.visual_language, ...mod.visual_language },
    };
  ctx.registry.options.designPreferencesAdvisory = true;
  ctx.registry.options.capture = true;
  captureSlide(ctx);
  ctx.visualUsage = [];
  if (typeof mod === 'function') {
    ctx.tokens = H.paletteMode(ctx.tokens, mod.dark ? 'dark' : 'light');
    const addNotes = ctx.slide.addNotes.bind(ctx.slide);
    const noteCalls = new Set();
    ctx.slide.addNotes = (notes) => {
      const key = Array.isArray(notes) ? notes.join('\n') : String(notes || '');
      if (noteCalls.has(key)) return ctx.slide;
      noteCalls.add(key);
      return addNotes(notes);
    };
    try {
      mod(ctx);
      // PPTX_MEASURE：测量工具把文本写入换成测量空操作，页面没有已登记元素属预期。
      if (
        !process.env.PPTX_MEASURE &&
        typeof ctx.registry._slide === 'function' &&
        !ctx.registry._slide(ctx.n).length &&
        !ctx.nativeObjects
      )
        throw new Error(
          'unfinished page: no drawable objects were authored; implement the page function',
        );
    } catch (error) {
      if (!/^Slide \d+:/.test(error.message))
        error.message = `Slide ${ctx.n}: ${/cannot fit|text_overflow/.test(error.message) ? 'text_overflow' : 'construction_failure'} ${error.message}`;
      throw error;
    } finally {
      ctx.slide.addNotes = addNotes;
    }
    const notes = String(mod.notes || mod.presentation_copy?.speaker_notes || '');
    if (notes && !noteCalls.has(notes)) addNotes(notes);
  } else {
    const request = { ...mod };
    if (!request.move && !request.layout)
      throw new Error('Declarative page needs an explicit author-selected move or layout');
    try {
      L.renderDeclaredPage(ctx, request);
    } catch (error) {
      error.message = `Slide ${ctx.n}: ${error.layoutFit ? 'layout_fit' : 'construction_failure'} ${error.message}`;
      throw error;
    }
  }
  ctx.registry.backgrounds?.set(ctx.n, ctx.slide.background);
  ctx.presentationCopy?.push({
    slide: ctx.n,
    design_freedom: mode,
    ...(mod.presentation_copy || {
      headline:
        mod.slots?.title ||
        ctx.registry._slide(ctx.n).find((el) => el.textRole === 'title')?.text ||
        '',
      visual_labels: mod.slots?.body || [],
    }),
    visual_usage: [...(mod.presentation_copy?.visual_usage || []), ...ctx.visualUsage],
    speaker_notes: String(mod.notes || mod.presentation_copy?.speaker_notes || ''),
    text_runs: ctx.registry
      ._slide(ctx.n)
      .filter((element) => element.type === 'text')
      .map((element) => element.text || ''),
  });
}

module.exports = { renderPage, captureSlide };
