'use strict';

const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const { spawnSync } = require('node:child_process');

function globalRoot() {
  const result =
    process.platform === 'win32'
      ? spawnSync(process.env.ComSpec || 'cmd.exe', ['/d', '/s', '/c', 'npm root -g'], {
          encoding: 'utf8',
        })
      : spawnSync('npm', ['root', '-g'], { encoding: 'utf8' });
  return result.status === 0 ? result.stdout.trim() : '';
}

function resolveModule(
  name,
  project = process.env.CLAUDE_PROJECT_DIR || process.cwd(),
  plugin = path.resolve(__dirname, '..'),
) {
  const attempts = [];
  for (const [source, candidate] of [
    ['project', project],
    ['plugin', plugin],
    ['global', null],
  ]) {
    const root = source === 'global' ? globalRoot() : candidate;
    if (!root) continue;
    try {
      const modulePath =
        source === 'global'
          ? require.resolve(path.join(root, name))
          : require.resolve(name, { paths: [root] });
      let packageRoot = path.dirname(modulePath);
      while (packageRoot !== path.dirname(packageRoot)) {
        const file = path.join(packageRoot, 'package.json');
        if (fs.existsSync(file)) {
          const pkg = JSON.parse(fs.readFileSync(file, 'utf8'));
          if (pkg.name === name) {
            const moduleRoot = name.startsWith('@')
              ? path.dirname(path.dirname(packageRoot))
              : path.dirname(packageRoot);
            return {
              source,
              root,
              modulePath,
              packageRoot,
              moduleRoot,
              version: pkg.version,
              attempts,
            };
          }
        }
        packageRoot = path.dirname(packageRoot);
      }
      throw new Error(`package.json for ${name} not found`);
    } catch (error) {
      attempts.push({ source, root, detail: error.message });
    }
  }
  const error = new Error(`${name} is unavailable from project, plugin or global roots`);
  error.attempts = attempts;
  throw error;
}

function installSearchPaths(resolutions, extras = []) {
  process.env.NODE_PATH = [
    ...new Set(
      [
        ...extras,
        ...resolutions.map((item) => item.moduleRoot),
        ...(process.env.NODE_PATH || '').split(path.delimiter),
      ].filter(Boolean),
    ),
  ].join(path.delimiter);
  Module._initPaths();
}

function probeModule(name, project) {
  const resolved = resolveModule(name, project);
  const environment = {
    ...process.env,
    NODE_PATH: [resolved.moduleRoot, process.env.NODE_PATH].filter(Boolean).join(path.delimiter),
  };
  const child = spawnSync(
    process.execPath,
    [
      '-e',
      'const file=require.resolve(process.argv[1]);require(process.argv[1]);console.log(file)',
      name,
    ],
    {
      cwd: project,
      env: environment,
      encoding: 'utf8',
    },
  );
  if (child.status !== 0)
    throw new Error(child.stderr || 'resolved module cannot load in production child');
  return { ...resolved, childLoadVerified: true };
}

module.exports = { resolveModule, installSearchPaths, probeModule };

if (require.main === module) {
  try {
    const result = probeModule(process.argv[2] || 'pptxgenjs', process.argv[3] || process.cwd());
    process.stdout.write(`${JSON.stringify({ ok: true, ...result })}\n`);
  } catch (error) {
    process.stdout.write(
      `${JSON.stringify({ ok: false, detail: error.message, attempts: error.attempts || [] })}\n`,
    );
    process.exitCode = 2;
  }
}
