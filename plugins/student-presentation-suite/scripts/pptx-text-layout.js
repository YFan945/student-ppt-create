'use strict';

// One measurement/wrapping implementation for helpers, actual drawing and registry.
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const fontkit = require('fontkit');
const fonts = new Map();
const widths = new Map();
const substitutions = new Map();
const CJK = /[\u3000-\u30ff\u3400-\u9fff\uf900-\ufaff\uff01-\uff60\uffe0-\uffee]/u;
const NO_START = /^[，。！？；：、）》】」』〕〉…,.!?;:%％)\]”’｝］]/u;
const NO_END = /[（《【「『〔〈(\[“‘｛［]$/u;
const wordSegmenter = new Intl.Segmenter('zh', { granularity: 'word' });
const ALIASES = {
  'Microsoft YaHei': 'msyh.ttc',
  SimHei: 'simhei.ttf',
  SimSun: 'simsun.ttc',
  DengXian: 'Deng.ttf',
  'DengXian Light': 'Dengl.ttf',
  KaiTi: 'simkai.ttf',
  FangSong: 'simfang.ttf',
  Calibri: 'calibri.ttf',
  Arial: 'arial.ttf',
  Cambria: 'cambria.ttc',
  'Times New Roman': 'times.ttf',
  'Courier New': 'cour.ttf',
};

function resolveFont(name, bold = false, italic = false) {
  const wanted = name || 'Calibri';
  const cacheKey = `${wanted}:${bold}:${italic}`;
  if (fonts.has(cacheKey)) return fonts.get(cacheKey);
  const candidates = [];
  if (fs.existsSync(wanted)) candidates.push(wanted);
  if (process.platform === 'win32') {
    const directory = path.join(process.env.WINDIR || 'C:\\Windows', 'Fonts');
    if (ALIASES[wanted]) candidates.push(path.join(directory, ALIASES[wanted]));
    const variants = {
      Arial: ['arialbd.ttf', 'ariali.ttf', 'arialbi.ttf'],
      Calibri: ['calibrib.ttf', 'calibrii.ttf', 'calibriz.ttf'],
      'Microsoft YaHei': ['msyhbd.ttc'],
      SimSun: [],
    };
    if (bold || italic) {
      const variant = variants[wanted]?.[bold && italic ? 2 : italic ? 1 : 0];
      if (variant) candidates.unshift(path.join(directory, variant));
    }
    // Filename and font family differ. Read metadata for custom installed families.
    if (!candidates.some((file) => fs.existsSync(file))) {
      for (const filename of fs.existsSync(directory) ? fs.readdirSync(directory) : []) {
        if (!/\.(ttf|otf|ttc)$/i.test(filename)) continue;
        try {
          const opened = fontkit.openSync(path.join(directory, filename));
          const members = opened.fonts || [opened];
          const match = members.find(
            (font) => font.familyName === wanted || font.fullName === wanted,
          );
          if (match) {
            fonts.set(cacheKey, match);
            return match;
          }
        } catch {
          /* unreadable system font */
        }
      }
    }
    candidates.push(path.join(directory, CJK.test(wanted) ? 'msyh.ttc' : 'arial.ttf'));
  } else {
    try {
      candidates.push(
        execFileSync(
          'fc-match',
          [
            '-f',
            '%{file}',
            `${wanted}:style=${bold ? 'Bold' : 'Regular'}${italic ? ' Italic' : ''}`,
          ],
          { encoding: 'utf8' },
        ).trim(),
      );
    } catch {
      /* macOS or a minimal host without fontconfig */
    }
    candidates.push(
      '/System/Library/Fonts/Helvetica.ttc',
      '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    );
  }
  for (const filename of candidates) {
    if (!filename || !fs.existsSync(filename)) continue;
    try {
      const opened = fontkit.openSync(filename);
      const members = opened.fonts || [opened];
      const font =
        members.find((item) => item.familyName === wanted || item.fullName === wanted) ||
        members[0];
      fonts.set(cacheKey, font);
      if (font.familyName !== wanted)
        substitutions.set(wanted, { requested: wanted, resolved: font.familyName, file: filename });
      return font;
    } catch {
      /* try the next installed face */
    }
  }
  throw new RangeError(
    `No installed font can measure ${wanted}; install a font or choose an available family.`,
  );
}

function measure(text, size, face, options = {}) {
  const font = resolveFont(face, Boolean(options.bold), Boolean(options.italic));
  const key = `${font.postscriptName}:${size}:${text}`;
  if (!widths.has(key)) {
    const run = font.layout(text);
    widths.set(
      key,
      ((run.positions.reduce((sum, item) => sum + item.xAdvance, 0) / font.unitsPerEm) * size) / 72,
    );
  }
  return widths.get(key);
}

// Real line height from fontkit metrics: font.descent is negative and
// lineGap may be 0/undefined. Factor 1.18 stays the fallback for faces that
// resolveFont cannot measure. Body/list copy keeps a 1.3 floor for classroom
// projection; display roles (title, caption, stat, ...) use the font's own
// metrics so tight display settings are not forced open.
function naturalLineHeightPt(piece, fallbackPt) {
  let height = fallbackPt;
  try {
    const font = resolveFont(
      piece.fontFace,
      Boolean(piece.options.bold),
      Boolean(piece.options.italic),
    );
    const { ascent, descent, unitsPerEm } = font;
    if (
      Number.isFinite(ascent) &&
      Number.isFinite(descent) &&
      Number.isFinite(unitsPerEm) &&
      unitsPerEm > 0
    ) {
      const gap = Number.isFinite(font.lineGap) ? font.lineGap : 0;
      height = ((ascent - descent + gap) / unitsPerEm) * piece.fontSize;
    }
  } catch {
    /* unresolved face — keep the factor fallback */
  }
  return height;
}

function sourceRuns(input, policy) {
  const values = Array.isArray(input) ? input : [{ text: String(input ?? ''), options: {} }];
  return values.flatMap((value) => {
    const run = typeof value === 'string' ? { text: value } : value;
    const options = { ...(run.options || {}) };
    options.bold ??= policy.bold;
    options.italic ??= policy.italic;
    const text = String(run.text ?? '').replace(/\r\n?/g, '\n') + (options.breakLine ? '\n' : '');
    delete options.breakLine;
    const fontSize = Number(options.fontSize ?? policy.fontSize);
    if (!Number.isFinite(fontSize) || fontSize <= 0)
      throw new RangeError('rich-text fontSize must be a finite positive number');
    return [
      {
        text,
        options,
        fontSize,
        fontFace: options.fontFace || policy.fontFace,
      },
    ];
  });
}

function atoms(input, policy) {
  const runs = sourceRuns(input, policy);
  const text = runs.map((run) => run.text).join('');
  // Numeric values with units and Latin words are indivisible; CJK uses graphemes.
  const pattern =
    /\n|[+-]?\d+(?:,\d{3})*(?:\.\d+)?[ \t]*(?:%|％|分贝|小时|分钟|毫秒|公里|千米|厘米|毫米|公斤|千克|亿元|万元|人次|秒|米|元|人|次|年|月|天|个|项|页|张|份|组|倍|度|GB|MB|KB|Hz|kHz|MHz|GHz|kg|km|cm|mm|ms|h|s|m)?|[A-Za-z]+(?:[-'][A-Za-z]+)*|[^\n]/gu;
  const result = [];
  const words = new Map(
    [...wordSegmenter.segment(text)]
      .filter((part) => part.isWordLike && /^\p{Script=Han}{2,}$/u.test(part.segment))
      .map((part) => [part.index, part]),
  );
  const matches = [...text.matchAll(pattern)];
  for (let index = 0; index < matches.length; index++) {
    let match = matches[index];
    const word = words.get(match.index);
    if (word) {
      match = { 0: word.segment, index: word.index };
      while (matches[index + 1]?.index < word.index + word.segment.length) index++;
    }
    const start = match.index;
    const end = start + match[0].length;
    let offset = 0;
    const pieces = [];
    for (const run of runs) {
      const low = Math.max(start, offset);
      const high = Math.min(end, offset + run.text.length);
      if (high > low) {
        const fragment = run.text.slice(low - offset, high - offset);
        // Pair East Asian and Latin faces before measurement, not after writing.
        for (const part of fragment.match(
          /[\u3000-\u30ff\u3400-\u9fff\uf900-\ufaff\uff01-\uff60\uffe0-\uffee]+|[^\u3000-\u30ff\u3400-\u9fff\uf900-\ufaff\uff01-\uff60\uffe0-\uffee]+/gu,
        ) || []) {
          const requested =
            run.options.fontFace ||
            (CJK.test(part) || (CJK.test(text) && /^[“”‘’]+$/u.test(part))
              ? policy.cjkFontFace || run.fontFace
              : run.fontFace);
          let font = resolveFont(requested, Boolean(run.options.bold), Boolean(run.options.italic));
          if (
            [...part].some(
              (char) => !/\s/u.test(char) && !font.hasGlyphForCodePoint(char.codePointAt(0)),
            )
          ) {
            const fallback = policy.cjkFontFace || 'Microsoft YaHei';
            const replacement = resolveFont(
              fallback,
              Boolean(run.options.bold),
              Boolean(run.options.italic),
            );
            if (
              [...part].some(
                (char) =>
                  !/\s/u.test(char) && !replacement.hasGlyphForCodePoint(char.codePointAt(0)),
              )
            )
              throw new RangeError(
                `No measurable installed glyph for ${JSON.stringify(part)}; choose a supporting font`,
              );
            substitutions.set(`${requested}:glyph`, {
              requested,
              resolved: replacement.familyName,
              reason: 'missing-glyph',
            });
            font = replacement;
          }
          // Emit the REQUESTED face, never the resolved file's familyName:
          // resolveFont silently falls back to arial.ttf/msyh.ttc for
          // uninstalled names, and writing the resolved name would leak
          // "Arial" into the deliverable where the author/tokens named
          // another family. Measurement still goes through resolveFont.
          pieces.push({
            text: part,
            options: { ...run.options },
            fontSize: run.fontSize,
            fontFace: requested,
          });
        }
      }
      offset += run.text.length;
    }
    result.push({
      text: match[0],
      pieces,
      width:
        match[0] === '\n'
          ? 0
          : pieces.reduce(
              (sum, piece) =>
                sum + measure(piece.text, piece.fontSize, piece.fontFace, piece.options),
              0,
            ),
    });
  }
  return result;
}

function layoutText(input, box, policy) {
  const size = Number(policy.fontSize);
  if (!Number.isFinite(size) || size <= 0)
    throw new RangeError('fontSize must be a finite positive number');
  const margin = policy.margin ?? 0;
  const margins = Array.isArray(margin) ? margin : [margin, margin, margin, margin];
  const width = box.w - ((margins[1] || 0) + (margins[3] || 0)) / 72;
  const height = box.h - ((margins[0] || 0) + (margins[2] || 0)) / 72;
  const wrapWidth = width * (policy.wrapWidthRatio ?? 1);
  const lines = [];
  let line = [];
  let explicit = false;
  const lineWidth = (values) => values.reduce((sum, atom) => sum + atom.width, 0);
  const flush = () => {
    lines.push({ atoms: line, explicit });
    line = [];
    explicit = false;
  };
  for (const atom of atoms(input, policy)) {
    if (atom.text === '\n') {
      explicit = true;
      flush();
      continue;
    }
    if (line.length && lineWidth(line) + atom.width > wrapWidth) {
      const moved = [];
      while (line.length && (NO_START.test(atom.text) || NO_END.test(line.at(-1).text))) {
        moved.unshift(line.pop());
        if (moved.length >= 2) break;
      }
      if (line.length) flush();
      line.push(...moved);
    }
    line.push(atom);
  }
  if (line.length || !lines.length || lines.at(-1)?.explicit) flush();
  // Rebalance a CJK orphan only within the same paragraph, without changing copy.
  if (policy.balance !== false && lines.length > 1) {
    const last = lines.at(-1);
    const before = lines.at(-2);
    while (
      !before.explicit &&
      last.atoms
        .map((atom) => atom.text)
        .join('')
        .trim().length < 3 &&
      before.atoms.length > 1
    ) {
      const moved = before.atoms.at(-1);
      if (
        !CJK.test(moved.text) ||
        NO_START.test(moved.text) ||
        lineWidth(last.atoms) + moved.width > wrapWidth
      )
        break;
      last.atoms.unshift(before.atoms.pop());
    }
  }
  let y = (box.y || 0) + (margins[0] || 0) / 72;
  const rich = [];
  // Predicted wraps are NOT paragraphs. Let the viewer wrap the editable
  // object once; forcing our predicted edge as a paragraph makes a viewer's
  // slightly wider fonts wrap it a second time and creates orphan lines.
  // Without an explicit value, multi-paragraph body/list blocks get a
  // 0.4× paragraph-size space after each real (explicit-\n) paragraph; display
  // roles stay untouched. The value rides on the LAST run of the paragraph's
  // LAST visual line, so spcAft lands at the real paragraph end — never after
  // a wrapped line inside it. Measurement folds the same space into the line
  // height and y progression, keeping requiredH identical to what is written.
  const relaxedRole = !['body', 'list'].includes(policy.role);
  const contentFlags = lines.map((entry) => entry.atoms.length > 0);
  const explicitSpace = policy.paraSpaceAfter ?? policy.paraSpaceAfterPt;
  const hasExplicit = Number.isFinite(Number(explicitSpace));
  const paraEnds = lines.map((entry, index) => {
    // A trailing empty line emits no run, hence no pptxgenjs paragraph/space.
    if (index === lines.length - 1 && !contentFlags[index] && !entry.explicit) return false;
    if (entry.explicit) return true;
    return index === lines.length - 1;
  });
  const paragraphCount = paraEnds.filter(Boolean).length;
  const lineSizes = lines.map((entry) =>
    Math.max(size, ...entry.atoms.flatMap((atom) => atom.pieces).map((piece) => piece.fontSize)),
  );
  const spaceAfterPt = paraEnds.map((endsParagraph, index) => {
    if (!endsParagraph) return 0;
    if (hasExplicit) return Number(explicitSpace);
    return paragraphCount >= 2 && !relaxedRole ? 0.4 * lineSizes[index] : 0;
  });
  const geometry = lines.map((entry, index) => {
    const pieces = [];
    for (const piece of entry.atoms.flatMap((atom) => atom.pieces)) {
      const previous = pieces.at(-1);
      if (
        previous &&
        previous.fontFace === piece.fontFace &&
        previous.fontSize === piece.fontSize &&
        JSON.stringify(previous.options) === JSON.stringify(piece.options)
      )
        previous.text += piece.text;
      else pieces.push({ ...piece });
    }
    const lineSize = Math.max(size, ...pieces.map((piece) => piece.fontSize));
    const lineHeightPt =
      policy.lineSpacing > 4
        ? policy.lineSpacing
        : pieces.length
          ? Math.max(
              ...pieces.map((piece) => naturalLineHeightPt(piece, lineSize * 1.18, relaxedRole)),
            )
          : relaxedRole
            ? lineSize * 1.18
            : Math.max(lineSize * 1.18, lineSize * 1.3);
    const lineHeight = lineHeightPt / 72;
    const trailingSpacePt = spaceAfterPt[index];
    const annotateSpace = !hasExplicit && trailingSpacePt > 0;
    pieces.forEach((piece, position) =>
      rich.push({
        text: piece.text,
        options: {
          ...piece.options,
          fontFace: piece.fontFace,
          fontSize: piece.fontSize,
          breakLine: entry.explicit && position === pieces.length - 1 && index < lines.length - 1,
          ...(annotateSpace && position === pieces.length - 1
            ? { paraSpaceAfter: trailingSpacePt }
            : {}),
        },
      }),
    );
    if (!pieces.length && index < lines.length - 1)
      rich.push({
        text: '',
        options: {
          breakLine: true,
          ...(annotateSpace ? { paraSpaceAfter: trailingSpacePt } : {}),
        },
      });
    const result = {
      text: pieces.map((piece) => piece.text).join(''),
      x:
        (box.x || 0) +
        (margins[3] || 0) / 72 +
        (policy.align === 'center'
          ? (width - lineWidth(entry.atoms)) / 2
          : policy.align === 'right'
            ? width - lineWidth(entry.atoms)
            : 0),
      y,
      w: lineWidth(entry.atoms),
      h: lineHeight + trailingSpacePt / 72,
      fragments: pieces.map((piece) => ({
        ...piece,
        w: measure(piece.text, piece.fontSize, piece.fontFace, piece.options),
      })),
    };
    y += lineHeight + trailingSpacePt / 72;
    return result;
  });
  const requiredH = geometry.reduce((sum, entry) => sum + entry.h, 0);
  return {
    richText: rich,
    lines: geometry.length,
    lineGeometry: geometry,
    requiredH,
    // Line pitch only — paragraph spaces ride inside each line's h and must
    // not inflate the lineSpacing we write back to the text object.
    lineHeightPt: geometry.length
      ? Math.max(...geometry.map((entry, index) => entry.h - spaceAfterPt[index] / 72)) * 72
      : 0,
    fontSize: size,
    margin: margins,
    fillRatio: requiredH / height,
    fits:
      width > 0 &&
      height > 0 &&
      requiredH <= height * (policy.maxFillRatio ?? 0.95) &&
      geometry.every((entry) => entry.w <= width),
    substitutions: [...substitutions.values()],
  };
}

module.exports = { layoutText, measure, resolveFont };
