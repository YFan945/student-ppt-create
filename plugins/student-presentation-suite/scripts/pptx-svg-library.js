'use strict';

const CORNER_SETS = Object.freeze({
  'academic-bracket': 'bracket',
  'editorial-crop': 'crop-mark',
  'cherry-slash': 'slash',
  'coral-arc': 'arc',
  'studio-tape': 'tape',
  'data-axis': 'axis',
  'moss-contour': 'contour',
  'midnight-beam': 'beam',
  'minimal-focus': 'focus',
  'ocean-circuit': 'circuit',
  'teal-checkpoint': 'checkpoint',
  'terracotta-stamp': 'stamp',
});

const LEGACY_CORNER_ALIASES = Object.freeze({
  'berry-petal': 'terracotta-stamp',
  'sage-orbit': 'moss-contour',
});

function hex(value, fallback = '2563EB') {
  const candidate = String(value || fallback).replace(/^#/, '');
  return /^[0-9a-f]{6}$/iu.test(candidate) ? candidate.toUpperCase() : fallback;
}

function dataUri(svg) {
  return `data:image/svg+xml;base64,${Buffer.from(svg, 'utf8').toString('base64')}`;
}

function paths(name, a, b) {
  const table = {
    bracket: `<path d="M34 12H12v96h22M12 34h15M12 86h15"/>`,
    petal: `<path d="M60 10C88 24 105 50 60 60C15 50 32 24 60 10Z"/><path d="M60 60C88 70 86 103 60 110C34 103 32 70 60 60Z" fill="${b}"/>`,
    'crop-mark': `<path d="M10 38V10h28M82 10h28v28M110 82v28H82"/><path d="M22 98L98 22" stroke="${b}"/>`,
    slash: `<path d="M15 110L78 10h27L42 110Z" fill="${a}" stroke="none"/><path d="M68 110l34-54" stroke="${b}"/>`,
    arc: `<path d="M12 100A88 88 0 0 1 100 12"/><circle cx="88" cy="25" r="8" fill="${b}" stroke="none"/>`,
    tape: `<path d="M23 20L102 9l7 35-79 11Z" fill="${b}" stroke="none"/><path d="M12 102L108 74"/>`,
    axis: `<path d="M12 12v96h96"/><path d="M30 87l19-18 17 7 31-38" stroke="${b}"/><circle cx="97" cy="38" r="5" fill="${a}"/>`,
    contour: `<path d="M8 94C27 61 46 113 65 80s31-13 47-48"/><path d="M8 112C28 77 49 126 70 94s28-17 42-41" stroke="${b}"/>`,
    beam: `<path d="M14 106L55 12h49L63 106Z" fill="${a}" fill-opacity=".22" stroke="none"/><path d="M32 106L72 12" stroke="${b}"/>`,
    focus: `<path d="M10 60h76"/><circle cx="94" cy="60" r="13" fill="${a}" stroke="none"/>`,
    circuit: `<path d="M10 22h38v36h35v40h27"/><circle cx="48" cy="22" r="6" fill="${b}"/><circle cx="83" cy="58" r="6" fill="${a}"/><circle cx="110" cy="98" r="6" fill="${b}"/>`,
    orbit: `<ellipse cx="59" cy="60" rx="48" ry="31" transform="rotate(-24 59 60)"/><circle cx="99" cy="38" r="8" fill="${b}" stroke="none"/>`,
    checkpoint: `<path d="M10 88C34 88 31 32 58 32s20 56 52 56"/><circle cx="58" cy="32" r="11" fill="${a}"/><path d="M52 32l4 4 8-10" stroke="#fff" stroke-width="4"/>`,
    stamp: `<path d="M20 14h80v92H20Z"/><path d="M32 28h56M32 42h38M32 84h56" stroke="${b}"/><path d="M71 57a17 17 0 1 0 1 0"/>`,
  };
  return table[name] || table.focus;
}

function getCornerSvg(name, options = {}) {
  const canonical = LEGACY_CORNER_ALIASES[name] || name;
  const resolved = CORNER_SETS[canonical] || canonical;
  const primary = hex(options.primary);
  const secondary = hex(options.secondary, '93C5FD');
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120"><g fill="none" stroke="#${primary}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">${paths(resolved, `#${primary}`, `#${secondary}`)}</g></svg>`;
  return dataUri(svg);
}

function getPatternSvg(name, options = {}) {
  const primary = hex(options.primary);
  const opacity = Math.max(0.04, Math.min(0.35, Number(options.opacity || 0.12)));
  const motif =
    name === 'dots'
      ? '<circle cx="8" cy="8" r="1.5"/>'
      : name === 'waves'
        ? '<path d="M0 8c5-8 11 8 16 0s11 8 16 0"/>'
        : '<path d="M0 0h32M0 16h32M0 32h32M0 0v32M16 0v32M32 0v32"/>';
  return dataUri(
    `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"><g fill="#${primary}" stroke="#${primary}" stroke-width=".7" opacity="${opacity}">${motif}</g></svg>`,
  );
}

function addCornerDecoration(slide, name, box, tokens, options = {}) {
  const palette = tokens.palette || {};
  return slide.addImage({
    data: getCornerSvg(name, {
      primary: palette.primary_accent,
      secondary: palette.secondary_accent,
    }),
    ...box,
    transparency: Number(options.transparency || 0),
    rotate: Number(options.rotate || 0),
    // 角落组按右上朝向绘制，其余锚点靠镜像（motif_at 的落位由此生效）。
    flipH: Boolean(options.flipH),
    flipV: Boolean(options.flipV),
  });
}

module.exports = {
  CORNER_SETS,
  LEGACY_CORNER_ALIASES,
  getCornerSvg,
  getPatternSvg,
  addCornerDecoration,
};
