'use strict';

/**
 * Style preview deck builder (v0.19, P2-11 "show, don't tell").
 *
 * Builds a tiny 2-page deck (dark cover + light chart page) for ONE resolved
 * style so the user can pick a visual style from rendered pixels at intake
 * instead of from adjectives. Config arrives as JSON on stdin:
 *   { "out": "<abs path>.pptx", "topic": "...", "tokens": {resolved tokens} }
 *
 * The engine does all geometry (renderBackground + renderArchetype); the copy
 * is fixed sample content themed by the topic — this is a style sample, not a
 * content draft.
 */

const path = require('node:path');
const HELPERS_DIR =
  process.env.PPTX_HELPERS_DIR || path.join(process.env.CLAUDE_PLUGIN_ROOT || '', 'scripts');
const H = require(path.join(HELPERS_DIR, 'pptx-helpers.js'));
const L = require(path.join(HELPERS_DIR, 'pptx-layouts.js'));
const pptxgen = require('pptxgenjs');

let raw = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (chunk) => {
  raw += chunk;
});
process.stdin.on('end', () => {
  const config = JSON.parse(raw);
  const { out, topic, tokens } = config;
  if (!out || !tokens || !tokens.palette) {
    throw new Error('style_preview_deck: config needs out, tokens (resolved design tokens)');
  }
  const topicText = String(topic || '').trim() || '主题汇报';

  const pptx = new pptxgen();
  H.applyTokens(pptx, tokens, 'chinese');
  const registry = new (require(
    path.join(HELPERS_DIR, 'pptx-element-registry.js'),
  ).SlideElementRegistry)({
    slideW: H.SLIDE_W_IN,
    slideH: H.SLIDE_H_IN,
  });

  // Page 1 — dark cover: the style's field, band, motif and type scale.
  const cover = pptx.addSlide();
  H.renderBackground(cover, tokens, { kind: 'cover', dark: true });
  L.renderArchetype(
    { slide: cover, tokens: H.paletteMode(tokens, 'dark'), registry, slideNumber: 1 },
    {
      layout: { id: 'cover-editorial' },
      slots: {
        title: topicText,
        claim: '一次结构化、可核证的汇报',
      },
    },
  );

  // Page 2 — light content: chart language + claim + takeaway of the style.
  const content = pptx.addSlide();
  H.renderBackground(content, tokens, { kind: 'content', dark: false });
  L.renderArchetype(
    { slide: content, tokens: H.paletteMode(tokens, 'light'), registry, slideNumber: 2 },
    {
      layout: { id: 'data-chart-takeaway' },
      slots: {
        title: '关键结果',
        claim: '三项指标全部达标',
        visual: {
          type: 'chart',
          details: {
            takeaway: '本方法在全部数据集上领先（图表结论组件样式）',
            series: [
              {
                name: '本方法',
                labels: ['数据集 1', '数据集 2', '数据集 3'],
                values: [82, 88, 91],
              },
              { name: '基线', labels: ['数据集 1', '数据集 2', '数据集 3'], values: [76, 81, 84] },
            ],
          },
        },
      },
    },
  );
  registry.assertSafe();

  pptx.writeFile({ fileName: out }).then(() => {
    process.stdout.write(`${JSON.stringify({ ok: true, out })}\n`);
  });
});
