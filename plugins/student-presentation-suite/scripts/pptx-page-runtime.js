'use strict';

const H = require('./pptx-helpers.js');
const L = require('./pptx-layouts.js');

function captureSlide(ctx) {
  const slide = ctx.slide;
  // Tables use the same measured text and registered shapes as every free page.
  // Complex spans must be expressed explicitly so no cell escapes measurement.
  if (typeof slide.addTable === 'function')
    slide.addTable = (rows, options = {}) => {
      if (!Array.isArray(rows) || !rows.length || rows.some((row) => !Array.isArray(row)))
        throw new Error('Table requires explicit cell rows');
      const count = Math.max(...rows.map((row) => row.length));
      const widths = Array.isArray(options.colW)
        ? options.colW
        : Array(count).fill(options.w / count);
      const heights = Array.isArray(options.rowH)
        ? options.rowH
        : Array(rows.length).fill(options.rowH ?? options.h / rows.length);
      if (
        widths.length !== count ||
        heights.length !== rows.length ||
        [...widths, ...heights].some((size) => !Number.isFinite(size) || size <= 0)
      )
        throw new RangeError('Table requires positive explicit cell geometry');
      const palette = ctx.tokens.palette || {};
      const headerRows =
        options.headerRows ?? (rows[0].some((cell) => cell?.options?.bold) ? 1 : 0);
      let y = options.y;
      rows.forEach((row, index) => {
        let x = options.x;
        for (let column = 0; column < count; column++) {
          const cell = row[column] ?? '';
          const value = typeof cell === 'object' && !Array.isArray(cell) ? cell : { text: cell };
          if (value.options?.colSpan || value.options?.rowSpan)
            throw new Error('Table spans require explicit registered cell shapes and text');
          const box = { x, y, w: widths[column], h: heights[index] };
          const cellOptions = { ...options, ...value.options, ...box };
          const header = index < headerRows;
          const highlighted = index === options.highlightRow;
          const fill =
            value.options?.fill ??
            (header
              ? (options.headerFill ?? { color: palette.primary_accent })
              : (options.fill ?? {
                  color: highlighted
                    ? palette.primary_accent
                    : index % 2
                      ? palette.surface
                      : palette.canvas,
                }));
          const foreground =
            value.options?.color ??
            (header
              ? (options.headerColor ?? H.readableTextColor(fill.color, ctx.tokens))
              : highlighted
                ? H.readableTextColor(fill.color, ctx.tokens)
                : (options.color ?? palette.primary_text));
          const explicitBorder = cellOptions.border;
          ctx.slide.addShape('rect', {
            ...box,
            fill,
            line: explicitBorder
              ? {
                  color: explicitBorder.color ?? palette.secondary_text,
                  width: explicitBorder.pt ?? 0.5,
                }
              : { type: 'none' },
            decorative: true,
          });
          if (!explicitBorder && !header)
            ctx.slide.addShape('line', {
              x: box.x,
              y: box.y + box.h,
              w: box.w,
              h: 0,
              line: { color: palette.secondary_text, transparency: 80, width: 0.4 },
              decorative: true,
            });
          ctx.slide.addText(value.text ?? '', {
            ...cellOptions,
            fill: undefined,
            color: foreground,
            bold: value.options?.bold ?? (header || highlighted || options.bold),
            fontSize:
              value.options?.fontSize ??
              (header ? (options.headerFontSize ?? options.fontSize) : options.fontSize) ??
              H.fontSizeScale(ctx.tokens, 'chinese').label,
            margin: cellOptions.margin ?? Math.min(4, box.h * 72 * 0.08),
            align:
              cellOptions.align ??
              (typeof value.text === 'number' || /^[-+]?\d[\d,.]*%?$/.test(String(value.text))
                ? 'right'
                : 'left'),
          });
          x += widths[column];
        }
        y += heights[index];
      });
      return slide;
    };
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
        if (!layout.fits)
          throw new RangeError(
            `Slide ${ctx.n}: text_overflow ${text.slice(0, 30)} in ${options.w}x${options.h}in at ${policy.fontSize}pt`,
          );
        if (
          options.positionMixedText !== false &&
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
        options.margin = layout.margin;
        options.lineSpacing = layout.fontSize * 1.18;
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
    ctx.slide.addNotes = () => {
      throw new Error('Free page notes belong in module.notes; the harness writes them once');
    };
    try {
      mod(ctx);
      if (typeof ctx.registry._slide === 'function' && !ctx.registry._slide(ctx.n).length)
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
    const copy = mod.presentation_copy;
    if (!copy || typeof copy !== 'object')
      throw new Error(`Slide ${ctx.n}: presentation_copy metadata missing`);
    const notes = String(mod.notes || copy.speaker_notes || '');
    if (notes) ctx.slide.addNotes(notes);
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
      headline: mod.slots?.title,
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
