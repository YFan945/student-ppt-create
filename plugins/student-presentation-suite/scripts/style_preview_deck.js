'use strict';

/**
 * Style preview deck builder (v0.19, P2-11 "show, don't tell").
 *
 * Builds a 2-page editable information + evidence deck for ONE resolved
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

  const V = require(path.join(HELPERS_DIR, 'pptx-visuals.js'));
  const examples = require(path.join(HELPERS_DIR, '../examples/main-session-visuals/pages.js'));
  const pageTokens = { ...tokens, model_led: true };
  registry.options.designPreferencesAdvisory = true;
  const captureSlide = require(path.join(HELPERS_DIR, 'pptx-page-runtime.js')).captureSlide;
  registry.options.capture = true;
  const first = pptx.addSlide();
  captureSlide({ slide: first, tokens: pageTokens, H, registry, n: 1, lang: 'chinese' });
  H.renderBackground(first, pageTokens, { kind: 'content' });
  examples.groups({ slide: first, tokens: pageTokens, H });
  H.addFittedText(
    first,
    `课程复盘 · ${topicText}`,
    { x: 0.55, y: 5.12, w: 8.9, h: 0.25 },
    pageTokens,
    'chinese',
    'caption',
    { fontSize: 10, margin: 0 },
  );
  const second = pptx.addSlide();
  captureSlide({ slide: second, tokens: pageTokens, H, registry, n: 2, lang: 'chinese' });
  H.renderBackground(second, pageTokens, { kind: 'content' });
  H.addFittedText(
    second,
    '实验观察与行动依据',
    { x: 0.55, y: 0.35, w: 8.9, h: 0.5 },
    pageTokens,
    'chinese',
    'title',
    { fontSize: 27, margin: 0 },
  );
  V.addChartWithTakeaway(
    second,
    {
      kind: 'bar',
      title: '五类观察数量',
      takeaway: '工具与方法记录较多，下一轮结合具体情境解释差异。',
      series: [
        {
          name: '示例数量',
          labels: ['资料', '方法', '协作', '工具', '反馈'],
          values: [18, 24, 16, 28, 22],
        },
      ],
    },
    { x: 0.55, y: 1.1, w: 8.9, h: 2.9 },
    pageTokens,
    'chinese',
  );
  V.addComparison(
    second,
    {
      items: [
        { label: '记录观察', detail: '保留条件、过程与可复查的结果' },
        { label: '解释差异', detail: '结合证据说明原因与适用边界' },
        { label: '安排改进', detail: '明确下一步行动与检查依据' },
      ],
      fontSize: 15,
      detailFontSize: 11,
    },
    { x: 0.55, y: 4.18, w: 8.9, h: 0.98 },
    pageTokens,
    'chinese',
  );
  H.addFittedText(
    second,
    '数据来源：课程展示样例',
    { x: 0.55, y: 5.22, w: 8.9, h: 0.25 },
    pageTokens,
    'chinese',
    'caption',
    { fontSize: 10, margin: 0 },
  );
  first.addNotes(examples.groups.notes);
  second.addNotes(
    '工具与方法记录较多。下一轮结合具体情境解释差异，并分别安排来源核对、分工完善与记录复查。数据来源：课程展示样例。',
  );
  H.writeCjkMap(out, pageTokens);
  registry.writeReport(out);
  registry.assertSafe();

  pptx.writeFile({ fileName: out }).then(() => {
    process.stdout.write(`${JSON.stringify({ ok: true, out })}\n`);
  });
});
