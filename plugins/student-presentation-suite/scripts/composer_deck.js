#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const pptxgen = require('pptxgenjs');
const C = require('./pptx-composer.js');

const [output, specPath, tokensPath, assetManifestPath] = process.argv.slice(2);
if (!output || !specPath || !tokensPath || ['--help', '-h'].includes(output)) {
  process.stdout.write(
    'Usage: composer_deck.js <output.pptx> <slide-spec.json> <resolved-tokens.json> [asset-manifest.json]\n' +
      'Compatibility command: renders locked layouts and deterministic fallback; adaptive-freeform deck.js is the default production path.\n',
  );
  process.exit(output ? 0 : 2);
}

function readJson(file, label) {
  const resolved = path.resolve(file);
  if (!fs.existsSync(resolved) || !fs.statSync(resolved).isFile()) {
    throw new Error(`${label} does not exist: ${resolved}`);
  }
  return JSON.parse(fs.readFileSync(resolved, 'utf8'));
}

async function main() {
  const spec = readJson(specPath, 'Slide Spec');
  const tokens = readJson(tokensPath, 'resolved tokens');
  const assets = assetManifestPath ? readJson(assetManifestPath, 'asset manifest') : null;
  const lang = String(spec.meta?.language || 'English').toLowerCase();
  const pptx = new pptxgen();
  const report = C.renderDeck(pptx, spec, {
    tokens,
    lang: lang === 'chinese' ? 'chinese' : lang === 'bilingual' ? 'bilingual' : 'english',
    assetManifest: assets,
    compositionMode: 'deterministic-fallback',
  });
  await pptx.writeFile({ fileName: path.resolve(output) });
  process.stdout.write(`${JSON.stringify({ ok: true, slides: report.rendered.length })}\n`);
}

main().catch((error) => {
  process.stderr.write(`composer_deck: ${error.message}\n`);
  process.exitCode = 1;
});
