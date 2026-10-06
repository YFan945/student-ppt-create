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
// 页面按 deck.js / calibration-deck.js 同款契约经 env 解析 helpers；builder 的
// Bash 进程没有 CLAUDE_PLUGIN_ROOT，harness 自己补齐，否则 self_check 报
// Cannot find module 'scripts\pptx-layouts.js'，builder 被迫把 fallback 修进
// 页面产物（run-14 live）。
process.env.PPTX_HELPERS_DIR = process.env.PPTX_HELPERS_DIR || SCRIPTS_DIR;
process.env.CLAUDE_PLUGIN_ROOT = process.env.CLAUDE_PLUGIN_ROOT || path.resolve(SCRIPTS_DIR, '..');

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
        } catch (_error) {
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

// 0.26.0 处方机制：把确定性失败翻译成可执行修法。
const LAYOUT_LIBRARY = (() => {
  try {
    return require(
      path.join(SCRIPTS_DIR, '..', 'skills', 'sp-deck', 'references', 'layout-library.json'),
    );
  } catch (_error) {
    return { layouts: [] };
  }
})();

function paletteRoleMap(tokens) {
  const roleByHex = {};
  const walk = (node, trail) => {
    if (Array.isArray(node)) {
      node.forEach((value, index) => walk(value, `${trail}[${index}]`));
    } else if (node && typeof node === 'object') {
      for (const [key, value] of Object.entries(node)) walk(value, trail ? `${trail}.${key}` : key);
    } else if (typeof node === 'string') {
      const t = node.toUpperCase();
      if (/^[0-9A-F]{6}$/.test(t) && !roleByHex[t]) roleByHex[t] = trail;
    }
  };
  walk(tokens, '');
  return roleByHex;
}

function remedyForThrow(error, pagePath) {
  const message = String((error && error.message) || error);
  let mod = null;
  try {
    mod = require(pagePath);
  } catch (_error) {
    mod = null;
  }
  const kind = mod && typeof mod === 'object' ? String(mod.kind || 'content') : null;
  const eligible = (LAYOUT_LIBRARY.layouts || []).filter(
    (l) => !kind || !l.eligible_kinds || l.eligible_kinds.includes(kind),
  );
  const unknown = message.match(/Unknown layout:\s*(\S+)/);
  if (unknown) {
    return [
      `未知版式 "${unknown[1]}"。kind=${kind || '?'} 的可用版式：` +
        `${eligible
          .slice(0, 12)
          .map((l) => l.id)
          .join(', ')}（全表见 skills/sp-deck/references/layout-library.json）`,
    ];
  }
  const chain = message.match(/fallback chain \[([^\]]*)\] all failed/);
  if (chain) {
    const failed = chain[1].split('->').map((s) => s.trim());
    const family = ((LAYOUT_LIBRARY.layouts || []).find((l) => l.id === failed[0]) || {}).family;
    const alternatives = (LAYOUT_LIBRARY.layouts || []).filter(
      (l) =>
        family &&
        l.family === family &&
        !failed.includes(l.id) &&
        (!kind || !l.eligible_kinds || l.eligible_kinds.includes(kind)),
    );
    const bodyCount =
      mod && mod.slots && Array.isArray(mod.slots.body) ? mod.slots.body.length : null;
    const parts = [
      `版式链 ${chain[1]} 全部放不下当前载荷（slots.body ${bodyCount === null ? '?' : `${bodyCount} 条`}）。处方：`,
    ];
    if (alternatives.length) {
      parts.push(
        `同族更大容量版式：${alternatives
          .slice(0, 4)
          .map(
            (l) => `${l.id}（body_items ${JSON.stringify((l.capacity || {}).body_items || '?')}）`,
          )
          .join('；')}；`,
      );
    }
    if (bodyCount !== null && bodyCount > 1) {
      parts.push('或把 body 裁到更少条目后重试（COPY 同步裁剪，保内容门）；');
    }
    parts.push('禁止为放得下去掉必出内容或转函数式页面。');
    return [parts.join(' ')];
  }
  return [];
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
  const source = fs.readFileSync(pagePath, 'utf-8');
  if (source.includes('student-presentation-suite-scaffold')) {
    findings.push({
      page: rel,
      kind: 'scaffold',
      message: '页面仍是 scaffold 存根（未实现）——先实现再自检',
    });
    continue;
  }
  try {
    const mod = require(pagePath);
    const n = Number((rel.match(/p(\d+)-/) || [])[1] || 0);
    const ctx = {
      pptx: {},
      slide,
      n,
      H: require(path.join(SCRIPTS_DIR, 'pptx-helpers.js')),
      registry,
      tokens,
      slideNumber: n,
      layoutReport,
    };
    if (typeof mod === 'function') {
      mod(ctx);
    } else {
      // 声明式页面：glue 与 deck.js 同一入口。
      require(path.join(SCRIPTS_DIR, 'pptx-layouts.js')).renderDeclaredPage(ctx, mod);
    }
  } catch (error) {
    const finding = {
      page: rel,
      kind: 'throw',
      message: String((error && error.message) || error).slice(0, 300),
    };
    // 0.26.0 处方：确定性失败必须带可执行修法，builder 的循环从"猜"变成照方抓药
    // （run-14 live：同一 fit 链连续失败 6 次，每次只有症状没有出路）。
    const remedy = remedyForThrow(error, pagePath);
    if (remedy.length) finding.remedy = remedy;
    findings.push(finding);
    continue;
  }
  const functionPage = /module\.exports\s*=\s*function/.test(source);
  if (functionPage && !/custom|自定义/i.test(source)) {
    findings.push({
      page: rel,
      kind: 'escape-hatch',
      message: '函数式页面须在页内注释声明 custom 理由（D9）；非自定义坐标请用声明式页面',
    });
  }
  if (!functionPage) {
    // COPY 双源防线：slots 的字符串字面量必须引用 COPY.*（逐字节文案门的前提）；
    // visual 槽允许字面量（数据载荷）。按花括号配平截取 slots 块，避免误伤块外字段。
    const slotsAt = source.search(/slots:\s*\{/);
    if (slotsAt >= 0) {
      let depth = 0;
      let block = '';
      for (let i = source.indexOf('{', slotsAt); i < source.length; i++) {
        const ch = source[i];
        if (ch === '{') depth++;
        else if (ch === '}') {
          depth--;
          if (depth === 0) break;
        }
        block += ch;
      }
      const head = block.split(/visual:/)[0];
      if (/['"]/.test(head)) {
        findings.push({
          page: rel,
          kind: 'copy-source',
          message:
            '槽位值应引用 COPY.* 字面量，不要在 slots 里直接写字符串（page_copy_fidelity 的前提）',
        });
      }
    }
  }
  if (!calls.some((c) => c.kind === 'notes')) {
    findings.push({
      page: rel,
      kind: 'notes',
      message: '缺少讲稿：声明式填 notes 字段，函数式 slide.addNotes(...)——每页一次、纯文本',
    });
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
    const roleMap = paletteRoleMap(tokens);
    const mapping = [...new Set(offPalette)]
      .map((hex) =>
        roleMap[hex]
          ? `${hex}→就是 tokens 的 ${roleMap[hex]}，改用角色引用`
          : `${hex}→无同值角色，改用 palette.* 角色色`,
      )
      .join('；');
    findings.push({
      page: rel,
      kind: 'off-palette',
      message: `疑似非调色板色值：${[...new Set(offPalette)].join(', ')}（颜色一律走 tokens 角色色，D13）`,
      remedy: [mapping],
    });
  }
}

const blockers = findings.filter((f) => f.kind !== 'warning');
const report = { ok: blockers.length === 0, findings, blocker_count: blockers.length };
process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
process.exit(blockers.length ? 1 : 0);
