#!/usr/bin/env node

const { spawnSync } = require('node:child_process');
const { randomUUID } = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { resolveModule, installSearchPaths } = require('./pptx-runtime-paths.js');
const USAGE =
  'Usage: run_with_pptxgenjs.js --output <new-deck.pptx> <deck-script.js> [deck-args...]';

if (['--help', '-h'].includes(process.argv[2])) {
  process.stdout.write(`${USAGE}\n`);
  process.exit(0);
}

const runtime = resolveModule('pptxgenjs');
const fontkit = resolveModule('fontkit');
const scriptsDir = __dirname;
installSearchPaths([runtime, fontkit], [scriptsDir]);
process.env.PPTX_HELPERS_DIR = scriptsDir;

if (process.argv[2] === '--probe') {
  process.stdout.write(JSON.stringify(runtime));
  process.exit(0);
}

const outputFlag = process.argv.indexOf('--output');
const output = outputFlag >= 0 ? process.argv[outputFlag + 1] : '';
const script = outputFlag >= 0 ? process.argv[outputFlag + 2] : '';
const deckArgs = outputFlag >= 0 ? process.argv.slice(outputFlag + 3) : [];
if (!script || !fs.existsSync(script) || !fs.statSync(script).isFile()) {
  // eslint-disable-next-line no-console
  console.error(USAGE);
  process.exit(2);
}
if (!output || !/\.(pptx|potx)$/i.test(output)) {
  // eslint-disable-next-line no-console
  console.error('--output must name a new .pptx or .potx file');
  process.exit(2);
}
const finalOutput = path.resolve(output);
if (fs.existsSync(finalOutput)) {
  // eslint-disable-next-line no-console
  console.error(`Refusing to overwrite existing output: ${finalOutput}`);
  process.exit(2);
}
const protectedInputs = [script, ...deckArgs]
  .filter((value) => typeof value === 'string' && fs.existsSync(value))
  .map((value) => path.resolve(value).toLowerCase());
if (protectedInputs.includes(finalOutput.toLowerCase())) {
  // eslint-disable-next-line no-console
  console.error(`Output must not be the deck script or an existing input: ${finalOutput}`);
  process.exit(2);
}

fs.mkdirSync(path.dirname(finalOutput), { recursive: true });
const token = randomUUID();
const extension = path.extname(finalOutput);
const stem = path.basename(finalOutput, extension);
const generated = path.join(path.dirname(finalOutput), `.${stem}.${token}.raw${extension}`);
const normalized = path.join(path.dirname(finalOutput), `.${stem}.${token}.normalized${extension}`);
try {
  const result = spawnSync(process.execPath, [path.resolve(script), generated, ...deckArgs], {
    stdio: 'inherit',
    env: process.env,
  });
  if (result.status !== 0) {
    process.exitCode = result.status === null ? 1 : result.status;
    return;
  }
  if (!fs.existsSync(generated) || !fs.statSync(generated).isFile()) {
    // eslint-disable-next-line no-console
    console.error(`Deck script did not create the requested output: ${generated}`);
    process.exitCode = 1;
    return;
  }
  const python = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  // CJK sidecar：scaffold deck.js 通过 H.writeCjkMap 写 <generated>.cjk-map.json。
  // 把 <a:ea> 注入折叠进同一次 normalize-generated（一个 python 进程），构建链
  // 不增加任何步骤；没有 sidecar 的手写 deck 保持原行为（不注入）。
  const cjkMapPath = `${generated}.cjk-map.json`;
  const cjkArgs = [];
  if (fs.existsSync(cjkMapPath)) {
    try {
      const map = JSON.parse(fs.readFileSync(cjkMapPath, 'utf8'));
      for (const [latin, cjk] of Object.entries(map)) {
        if (typeof latin === 'string' && typeof cjk === 'string' && latin && cjk) {
          cjkArgs.push('--cjk-map', `${latin}=${cjk}`);
        }
      }
    } catch (_) {
      // sidecar 不可读就跳过注入：字体回落到查看器默认，不影响构建。
    }
  }
  const normalization = spawnSync(
    python,
    [
      path.join(__dirname, 'pptx_tool.py'),
      'normalize-generated',
      generated,
      '--output',
      normalized,
      ...cjkArgs,
    ],
    { encoding: 'utf8', env: process.env },
  );
  if (normalization.status !== 0) {
    // eslint-disable-next-line no-console
    console.error(
      (normalization.stderr || normalization.stdout || 'PPTX normalization failed').trim(),
    );
    process.exitCode = normalization.status === null ? 1 : normalization.status;
    return;
  }
  // normalize 的 changed 混着两类修复：图表轴引用移除与 slide XML 结构修复
  // （stray pPr、<a:ea> 注入）。只有图表条目值得"组合图降级"告警；结构修复
  // 在这里只回显一行，避免被误读成图表问题。
  let normalizedCharts = [];
  let otherFixes = [];
  try {
    const payload = JSON.parse(normalization.stdout || '{}');
    const changed = Array.isArray(payload.changed) ? payload.changed : [];
    normalizedCharts = changed.filter((item) => String(item).includes('chart'));
    otherFixes = changed.filter((item) => !String(item).includes('chart'));
  } catch (_) {
    // 忽略 stdout 解析失败；仍继续用已归一化文件。
  }
  if (otherFixes.length > 0) {
    // eslint-disable-next-line no-console
    console.warn(
      `[normalize] ${otherFixes.length} 处 slide XML 结构修复（stray pPr 清理 / CJK <a:ea> 注入）：\n` +
        `  ${otherFixes.join('\n  ')}`,
    );
  }
  if (normalizedCharts.length > 0) {
    // eslint-disable-next-line no-console
    console.warn(
      `[normalize] ${normalizedCharts.length} 个图表的未声明轴引用被移除（pptxgenjs 常规输出；` +
        `若本意是双轴组合图，请在 deck.js 中显式声明 valAxes + catAxes 各两条）：\n` +
        `  ${normalizedCharts.join('\n  ')}`,
    );
  }
  // A same-directory hard link is atomic and fails with EEXIST on every
  // supported platform; rename() would overwrite a raced-in file on POSIX.
  // 硬链接不可用时统一回退为复制：除 EEXIST/EPERM 外，FAT/exFAT 常见的
  // ENOSYS、网络盘的 EACCES、旧内核的 EOPNOTSUPP 都不该让构建直接崩掉。
  try {
    fs.linkSync(normalized, finalOutput);
  } catch (linkError) {
    if (linkError.code === 'EEXIST') {
      // 目标已存在（并发构建竞态）才是真正的异常路径。
      throw linkError;
    }
    fs.copyFileSync(normalized, finalOutput);
  }
  const presentationCopy = require('node:path').join(
    require('node:path').dirname(script),
    'presentation-copy.json',
  );
  if (fs.existsSync(presentationCopy)) {
    const copy = JSON.parse(fs.readFileSync(presentationCopy, 'utf8'));
    copy.pptx_sha256 = require('node:crypto')
      .createHash('sha256')
      .update(fs.readFileSync(finalOutput))
      .digest('hex');
    fs.writeFileSync(presentationCopy, `${JSON.stringify(copy, null, 2)}\n`);
  }
  // Sidecars were written for the temporary raw output. Carry them to the
  // normalized artifact so pipeline/build can hash-bind the actual geometry.
  for (const suffix of ['.registry-report.json', '.layout-report.json']) {
    if (fs.existsSync(`${generated}${suffix}`))
      fs.renameSync(`${generated}${suffix}`, `${finalOutput}${suffix}`);
  }
} finally {
  for (const temporary of [
    generated,
    normalized,
    `${generated}.cjk-map.json`,
    `${generated}.registry-report.json`,
    `${generated}.layout-report.json`,
  ]) {
    try {
      fs.rmSync(temporary, { force: true });
    } catch (_) {
      // Preserve the primary failure; stale dot-files are safe to remove manually.
    }
  }
}
