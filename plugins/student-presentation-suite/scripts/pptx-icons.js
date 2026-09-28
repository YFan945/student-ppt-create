/**
 * Built-in SVG icon library for the Student Presentation Suite.
 *
 * A small, dependency-free set of line icons rendered as inline SVG and
 * embedded via `addImage` base64 data URIs. Icons are vector (editable), keep a
 * consistent 24x24 viewBox, and take their stroke color from the current
 * design-token role so they stay on-palette.
 *
 * Usage from a deck.js:
 *
 *   const I = require('./pptx-icons.js');
 *   I.addIconFromLibrary(slide, 'check', { x: 0.5, y: 0.5, w: 0.3, h: 0.3 }, tokens);
 *   const svg = I.iconSVG('warning', 'B85042'); // raw SVG string
 *
 * Icons are meant for headers, callout chips, section markers, and small
 * accents — not as substitutes for charts or diagrams. `addText`/`addShape`
 * remain the fallback when no library icon fits.
 */

'use strict';

const ICON_PATHS = {
  check: '<path d="M4 12l5 5L20 6"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  warning: '<path d="M12 3L2 21h20L12 3z"/><path d="M12 9v6"/><circle cx="12" cy="18" r="1"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><circle cx="12" cy="8" r="1"/>',
  lightbulb:
    '<path d="M9 18h6M10 21h4M12 3a6 6 0 0 1 3 11.2c-.6.3-1 1-1 1.8H10c0-.8-.4-1.5-1-1.8A6 6 0 0 1 12 3z"/>',
  star: '<path d="M12 2l3 7 7 .5-5 5 1.5 7-6.5-4-6.5 4L9 14.5l-5-5L9 9z"/>',
  target:
    '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
  'arrow-right': '<path d="M4 12h16M13 5l7 7-7 7"/>',
  'arrow-down': '<path d="M12 4v16M5 13l7 7 7-7"/>',
  steps: '<path d="M3 17h4l4-8h4M15 9h4l2-4"/>',
  timeline:
    '<path d="M3 12h4M7 12a2 2 0 1 0 4 0 2 2 0 0 0-4 0zM17 12a2 2 0 1 0 4 0 2 2 0 0 0-4 0zM11 12h6"/>',
  refresh: '<path d="M20 12a8 8 0 1 1-2.3-5.7M20 3v4h-4"/>',
  compare: '<path d="M7 3v18M17 3v18M3 7h4M3 17h4M17 7h4M17 17h4"/>',
  grid: '<rect x="4" y="4" width="7" height="7"/><rect x="13" y="4" width="7" height="7"/><rect x="4" y="13" width="7" height="7"/><rect x="13" y="13" width="7" height="7"/>',
  layers: '<path d="M12 2l10 6-10 6L2 8z"/><path d="M2 14l10 6 10-6"/>',
  branch: '<path d="M6 3v12M6 15a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM18 3v6a6 6 0 0 1-6 6"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6 8-6s8 2 8 6"/>',
  users:
    '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 21c0-3.5 3-5 6.5-5s6.5 1.5 6.5 5M17 5a3.5 3.5 0 0 1 0 7M18.5 16.5c2 .5 3 1.7 3 3.5"/>',
  'chart-bar': '<path d="M4 20V10M10 20V4M16 20v-8M22 20H2"/>',
  'chart-line': '<path d="M4 18l5-6 4 3 7-8M3 21h18"/>',
  'chart-pie': '<path d="M12 3a9 9 0 1 0 9 9h-9z"/><path d="M21 12a9 9 0 0 0-9-9v9z"/>',
  metric: '<path d="M4 20h16M7 14l3-4 3 2 4-6"/>',
  quote: '<path d="M7 7h5v5c0 3-2 5-5 5M15 7h5v5c0 3-2 5-5 5"/>',
  file: '<path d="M6 2h8l4 4v16H6z"/><path d="M14 2v4h4"/>',
  database:
    '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
  book: '<path d="M4 4a2 2 0 0 1 2-2h14v18H6a2 2 0 0 0-2 2z"/><path d="M4 20a2 2 0 0 1 2-2h14"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/>',
  calendar: '<rect x="3" y="5" width="18" height="16"/><path d="M3 9h18M8 3v4M16 3v4"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M16 16l5 5"/>',
  link: '<path d="M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/>',
  flag: '<path d="M5 3v18M5 4h11l-2 5 2 5H5"/>',
  heart:
    '<path d="M12 21C6 16 3 12.5 3 8.8A4.8 4.8 0 0 1 12 6a4.8 4.8 0 0 1 9 2.8c0 3.7-3 7.2-9 12.2z"/>',
  leaf: '<path d="M4 20c0-9 7-16 16-16 0 9-7 16-16 16z"/><path d="M4 20C10 14 15 10 19 6"/>',
  download: '<path d="M12 3v12M6 9l6 6 6-6M4 21h16"/>',
  upload: '<path d="M12 21V9M6 15l6-6 6 6M4 3h16"/>',
};

const ICON_NAMES = Object.keys(ICON_PATHS);

function iconSVG(name, color) {
  const path = ICON_PATHS[name];
  if (!path) {
    throw new RangeError(`Unknown icon: ${name}. Available: ${ICON_NAMES.join(', ')}`);
  }
  const stroke = color || '#111827';
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" ` +
    `fill="none" stroke="${stroke}" stroke-width="2" ` +
    `stroke-linecap="round" stroke-linejoin="round">${path}</svg>`
  );
}

function addIconFromLibrary(slide, name, box, tokens, role) {
  const palette = (tokens && tokens.palette) || {};
  const color = palette[role || 'primary_accent'] || '#111827';
  const svg = iconSVG(name, color);
  const data = `data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`;
  slide.addImage({ data, ...box });
}

module.exports = {
  ICON_NAMES,
  addIconFromLibrary,
  iconSVG,
};
