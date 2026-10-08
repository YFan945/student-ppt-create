'use strict';

/**
 * Style preview deck builder (v0.19, P2-11 "show, don't tell").
 *
 * Builds a tiny 2-page deck (dark cover + light chart page) for ONE resolved
 * style so the user can pick a visual style from rendered pixels at intake
 * instead of from adjectives. Config arrives as JSON on stdin:
 *   { "out": "<abs path>.pptx", "topic": "...", "tokens": {resolved tokens} }
 *
 * The engine does all geometry through renderDeclaredPage moves. The copy
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

  const cover = pptx.addSlide();
  const coverClaim = [...topicText].length <= 14 ? topicText : '这一句是页面的主张';
  L.renderDeclaredPage(
    { slide: cover, tokens, registry, slideNumber: 1, lang: 'chinese' },
    {
      dark: true,
      kind: 'cover',
      move: 'thesis',
      slots: { title: '风格', claim: coverClaim, body: ['先看这一句'] },
    },
  );

  const content = pptx.addSlide();
  L.renderDeclaredPage(
    { slide: content, tokens, registry, slideNumber: 2, lang: 'chinese' },
    {
      dark: false,
      kind: 'content',
      move: 'metric',
      slots: {
        title: '关键结果',
        claim: '91',
        body: ['本方法在全部数据集上领先'],
      },
    },
  );
  registry.assertSafe();

  pptx.writeFile({ fileName: out }).then(() => {
    process.stdout.write(`${JSON.stringify({ ok: true, out })}\n`);
  });
});
