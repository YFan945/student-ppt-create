#!/usr/bin/env node
/**
 * Dry-run verifier for isolated builder page modules.
 *
 * `node scripts/check_page_module.js --work-dir <wd> --pages pages/p01-x.js,pages/p02-y.js`
 *
 * Runs each page module against a mock slide + a real SlideElementRegistry —
 * the same contract deck.js uses, minus the real PPTX render — and reports:
 *   - registry geometry/grammar findings (text_overlap, near_miss_alignment,
 *     dead_zone, accent_line_under_title, ...);
 *   - fit failures (RangeError from addFittedText) with the offending box;
 *   - off-palette color strings (chart/shape defaults like 000000 that the
 *     palette gate would flag).
 *
 * Exit codes: 0 = clean, 1 = findings (fix before BUILDER_DONE), 2 = usage/infra.
 * The deterministic gates at build still run — this is a pre-check, not a bypass.
 */

'use strict';

const fs = require('node:fs');
const path = require('node:path');

const SCRIPTS_DIR = __dirname;
const WORK_DIR = (() => {
  const i = process.argv.indexOf('--work-dir');
  return i > 0 ? path.resolve(process.argv[i + 1]) : null;
})();
const PAGES_ARG = (() => {
  const i = process.argv.indexOf('--pages');
  return i > 0 ? process.argv[i + 1] : null;
})();

if (!WORK_DIR || !PAGES_ARG) {
  process.stdout.write(
    'Usage: node scripts/check_page_module.js --work-dir <wd> --pages "pages/p01-a.js,pages/p02-b.js"\n',
  );
  process.exit(2);
}

// 页面模块裸 require('pptx-layouts')：把本目录挂进 NODE_PATH 后重初始化解析路径。
process.env.NODE_PATH = [process.env.NODE_PATH, SCRIPTS_DIR].filter(Boolean).join(path.delimiter);
require('node:module').Module._initPaths();

function extractTokens(deckJs) {
  const marker = 'const TOKENS = ';
  const start = deckJs.indexOf(marker);
  if (start < 0) return null;
  const body = deckJs.slice(start + marker.length);
  // 括号配平（尊重字符串），取到与之配对的 '}'。
  let depth = 0;
  let inStr = null;
  for (let i = 0; i < body.length; i++) {
    const ch = body[i];
    if (inStr) {
      if (ch === '\\') i++;
      else if (ch === inStr) inStr = null;
      continue;
    }
    if (ch === '"' || ch === "'" || ch === '`') inStr = ch;
    else if (ch === '{') depth++;
    else if (ch === '}') {
      depth--;
      if (depth === 0) {
        try {
          return JSON.parse(body.slice(0, i + 1));
        } catch (error) {
          return null;
        }
      }
    }
  }
  return null;
}

function mockSlide() {
  const calls = [];
  const record =
    (kind) =>
    (...args) => {
      calls.push({
        kind,
        args: args.map((a) => (typeof a === 'object' && a !== null ? a : String(a))),
      });
      return {};
    };
  const slide = {
    addText: record('text'),
    addShape: record('shape'),
    addImage: record('image'),
    addChart: record('chart'),
    addTable: record('table'),
    addNotes: record('notes'),
  };
  return { slide, calls };
}

function collectColors(calls) {
  const found = [];
  for (const call of calls) {
    const text = JSON.stringify(call.args);
    for (const m of text.matchAll(/\b[0-9A-Fa-f]{6}\b/g)) found.push(m[0].toUpperCase());
  }
  return found;
}

function paletteColors(tokens) {
  const set = new Set();
  const walk = (node) => {
    if (typeof node === 'string') {
      const t = node.toUpperCase();
      if (/^[0-9A-F]{6}$/.test(t)) set.add(t);
    } else if (node && typeof node === 'object') {
      for (const value of Object.values(node)) walk(value);
    }
  };
  walk(tokens);
  return set;
}

const deckPath = path.join(WORK_DIR, 'deck.js');
if (!fs.existsSync(deckPath)) {
  process.stdout.write(`check_page_module: ${deckPath} 不存在——先 plan 生成 deck.js 再自检\n`);
  process.exit(2);
}
const tokens = extractTokens(fs.readFileSync(deckPath, 'utf-8'));
if (!tokens || !tokens.palette) {
  process.stdout.write('check_page_module: deck.js 里没有可解析的 TOKENS——重新 plan 后再自检\n');
  process.exit(2);
}
const allowedColors = paletteColors(tokens);
const { SlideElementRegistry } = require(path.join(SCRIPTS_DIR, 'pptx-element-registry.js'));

const findings = [];
const pages = PAGES_ARG.split(',')
  .map((p) => p.trim())
  .filter(Boolean);

for (const rel of pages) {
  const pagePath = path.resolve(WORK_DIR, rel);
  if (!fs.existsSync(pagePath)) {
    findings.push({ page: rel, kind: 'missing', message: `页面模块不存在：${rel}` });
    continue;
  }
  const { slide, calls } = mockSlide();
  const registry = new SlideElementRegistry({
    slideW: 10,
    slideH: 5.625,
  });
  const layoutReport = [];
  try {
    const mod = require(pagePath);
    mod({
      pptx: {},
      slide,
      n: Number((rel.match(/p(\d+)-/) || [])[1] || 0),
      H: require(path.join(SCRIPTS_DIR, 'pptx-helpers.js')),
      registry,
      tokens,
      slideNumber: Number((rel.match(/p(\d+)-/) || [])[1] || 0),
      layoutReport,
    });
  } catch (error) {
    findings.push({
      page: rel,
      kind: 'throw',
      message: String((error && error.message) || error).slice(0, 300),
    });
    continue;
  }
  const analysis = registry.analyzeDeck();
  for (const err of analysis.errors || []) {
    findings.push({
      page: rel,
      kind: 'registry',
      code: err.code,
      message: String(err.message || err.code).slice(0, 200),
    });
  }
  for (const warn of analysis.warnings || []) {
    findings.push({
      page: rel,
      kind: 'warning',
      code: warn.code,
      message: String(warn.message || warn.code).slice(0, 200),
    });
  }
  const offPalette = collectColors(calls).filter((hex) => !allowedColors.has(hex));
  if (offPalette.length) {
    findings.push({
      page: rel,
      kind: 'off-palette',
      message: `疑似非调色板色值：${[...new Set(offPalette)].join(', ')}（颜色一律走 tokens 角色色，D13）`,
    });
  }
}

const blockers = findings.filter((f) => f.kind !== 'warning');
const report = { ok: blockers.length === 0, findings, blocker_count: blockers.length };
process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
process.exit(blockers.length ? 1 : 0);
