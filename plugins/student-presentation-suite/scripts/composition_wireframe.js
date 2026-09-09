'use strict';

/**
 * Render low-cost composition candidate wireframes to PPTX.
 *
 * Input is JSON produced by the v0.8 composition-candidate contract. The output
 * contains one wireframe slide per candidate. These slides intentionally show
 * hierarchy, zones and focal weight rather than finished styling; Claude should
 * render/inspect them before committing a high-leverage slide to final deck.js.
 */

const fs = require('fs');
const path = require('path');
const pptxgen = require('pptxgenjs');

const SLIDE_W = 13.333;
const SLIDE_H = 7.5;

function probe() {
  process.stdout.write(JSON.stringify({ ok: true, tool: 'composition-wireframe', version: '0.8' }));
}

function readJson(file) {
  const value = JSON.parse(fs.readFileSync(file, 'utf8'));
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError('Candidate file root must be an object.');
  }
  return value;
}

function zoneToBox(zone) {
  if (!Array.isArray(zone) || zone.length !== 4) throw new TypeError('zone must be [x,y,w,h]');
  const [x, y, w, h] = zone.map(Number);
  return { x: x * SLIDE_W, y: y * SLIDE_H, w: w * SLIDE_W, h: h * SLIDE_H };
}

function zoneLabel(name) {
  return String(name || '').replace(/[_-]+/g, ' ').toUpperCase();
}

function addZone(slide, name, zone, index) {
  const box = zoneToBox(zone);
  const fills = ['E8EEF8', 'F4E9DE', 'E8F3EB', 'F0E8F5', 'F7EFCF', 'E6F0F2'];
  const fill = fills[index % fills.length];
  slide.addShape('rect', {
    ...box,
    fill: { color: fill, transparency: 8 },
    line: { color: '8A94A6', width: 1, dash: 'dash' },
  });
  slide.addText(zoneLabel(name), {
    x: box.x + 0.08,
    y: box.y + 0.05,
    w: Math.max(0.3, box.w - 0.16),
    h: Math.min(0.32, Math.max(0.18, box.h - 0.08)),
    fontFace: 'Arial',
    fontSize: 10,
    bold: true,
    color: '4B5563',
    margin: 0,
    breakLine: false,
  });
}

function addCandidateSlide(pptx, candidate, data, number) {
  const slide = pptx.addSlide();
  slide.background = { color: 'FBFBFA' };

  slide.addText(`Candidate ${candidate.id || number}`, {
    x: 0.45,
    y: 0.2,
    w: 4.5,
    h: 0.35,
    fontFace: 'Arial',
    fontSize: 20,
    bold: true,
    color: '111827',
    margin: 0,
  });
  slide.addText(
    `${candidate.silhouette || 'unknown'}  ·  ${candidate.visual_strategy || 'unspecified'}  ·  focal ${candidate.focal_share ?? '?'}`,
    {
      x: 5.1,
      y: 0.23,
      w: 7.6,
      h: 0.28,
      fontFace: 'Arial',
      fontSize: 10,
      color: '6B7280',
      align: 'right',
      margin: 0,
    },
  );

  const canvas = { x: 0.46, y: 0.78, w: 12.4, h: 5.92 };
  slide.addShape('rect', {
    ...canvas,
    fill: { color: 'FFFFFF' },
    line: { color: 'D1D5DB', width: 1.2 },
  });

  const zones = candidate.zones || {};
  Object.entries(zones).forEach(([name, zone], index) => {
    const normalized = zoneToBox(zone);
    addZone(
      slide,
      name,
      [
        (normalized.x / SLIDE_W) * (canvas.w / SLIDE_W) + canvas.x / SLIDE_W,
        (normalized.y / SLIDE_H) * (canvas.h / SLIDE_H) + canvas.y / SLIDE_H,
        (normalized.w / SLIDE_W) * (canvas.w / SLIDE_W),
        (normalized.h / SLIDE_H) * (canvas.h / SLIDE_H),
      ],
      index,
    );
  });

  const refs = Array.isArray(candidate.reference_ids) ? candidate.reference_ids.join(', ') : '';
  slide.addText(`Refs: ${refs || 'none'}`, {
    x: 0.5,
    y: 6.91,
    w: 4.8,
    h: 0.22,
    fontFace: 'Arial',
    fontSize: 9,
    color: '6B7280',
    margin: 0,
  });
  slide.addText(String(candidate.rationale || ''), {
    x: 5.4,
    y: 6.85,
    w: 7.35,
    h: 0.38,
    fontFace: 'Arial',
    fontSize: 9,
    color: '374151',
    margin: 0,
    align: 'right',
    valign: 'mid',
  });

  if (String(data.selected_id || '') === String(candidate.id || '')) {
    slide.addShape('roundRect', {
      x: 11.82,
      y: 0.16,
      w: 1.0,
      h: 0.38,
      rectRadius: 0.04,
      fill: { color: 'DDF4E4' },
      line: { color: '4F8B61', width: 1 },
    });
    slide.addText('SELECTED', {
      x: 11.88,
      y: 0.25,
      w: 0.88,
      h: 0.15,
      fontFace: 'Arial',
      fontSize: 8,
      bold: true,
      color: '285A38',
      align: 'center',
      margin: 0,
    });
  }
}

async function main() {
  const argv = process.argv.slice(2);
  if (argv.includes('--probe')) {
    probe();
    return;
  }
  const inputIndex = argv.indexOf('--input');
  const outputIndex = argv.indexOf('--output');
  if (inputIndex < 0 || !argv[inputIndex + 1] || outputIndex < 0 || !argv[outputIndex + 1]) {
    throw new Error('Usage: node composition_wireframe.js --input candidates.json --output wireframes.pptx');
  }
  const input = path.resolve(argv[inputIndex + 1]);
  const output = path.resolve(argv[outputIndex + 1]);
  const data = readJson(input);
  const candidates = Array.isArray(data.candidates) ? data.candidates : [];
  if (!candidates.length) throw new Error('Candidate file contains no candidates.');

  const pptx = new pptxgen();
  pptx.layout = 'LAYOUT_WIDE';
  pptx.author = 'Student Presentation Suite';
  pptx.subject = 'v0.8 composition candidate wireframes';
  pptx.title = `Composition candidates for slide ${data.slide_id || '?'}`;
  pptx.company = 'Student Presentation Suite';
  pptx.lang = 'zh-CN';
  pptx.theme = {
    headFontFace: 'Arial',
    bodyFontFace: 'Arial',
    lang: 'zh-CN',
  };

  candidates.forEach((candidate, index) => addCandidateSlide(pptx, candidate, data, index + 1));
  fs.mkdirSync(path.dirname(output), { recursive: true });
  await pptx.writeFile({ fileName: output });
  process.stdout.write(JSON.stringify({ ok: true, output, candidates: candidates.length }));
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message || error}\n`);
  process.exitCode = 1;
});
