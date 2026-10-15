#!/usr/bin/env python3
"""List or render complete same-material teaching examples outside the plugin.

This developer/reference tool is not a production gate or a real-model benchmark.
Normal deck tasks still follow approved intake before generating examples.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared.design_tokens import resolve_design_tokens  # noqa: E402
from shared.hashing import file_sha256  # noqa: E402
from shared.pptx_runtime import validate_pptx  # noqa: E402
from shared.pptx_runtime.render import render_pptx  # noqa: E402

CATALOG = ROOT / 'examples/main-session-visuals/cases.json'


def interface_svg() -> str:
    """Synthetic interface drawing, no real product/person or external asset."""
    return '''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800" viewBox="0 0 1200 800">
<rect width="1200" height="800" fill="#e8eef6"/><rect x="20" y="20" width="1160" height="760" rx="12" fill="white"/>
<rect x="20" y="20" width="1160" height="110" fill="#14324d"/><text x="65" y="90" font-family="Arial" font-size="36" fill="white">SOURCE EXPLORER / SYNTHETIC INTERFACE</text>
<text x="80" y="230" font-family="Arial" font-size="29" fill="#18364b">Original record</text><rect x="80" y="260" width="1020" height="65" fill="#eef5fa"/>
<text x="110" y="303" font-family="Arial" font-size="29" fill="#23465d">archive / interview-01 / original</text>
<text x="80" y="400" font-family="Arial" font-size="29" fill="#18364b">Version: v2</text><text x="670" y="400" font-family="Arial" font-size="29" fill="#18364b">Updated: 2026-10-01</text>
<rect x="80" y="490" width="1020" height="200" rx="8" fill="#e6f3f0"/><text x="110" y="545" font-family="Arial" font-size="29" fill="#184e45">Browse related records</text>
<text x="110" y="625" font-family="Arial" font-size="32" fill="#184e45">PEOPLE     /     PLACES     /     TOPICS</text>
<text x="80" y="745" font-family="Arial" font-size="23" fill="#526074">Concept fixture. Not a real product screenshot.</text></svg>'''


def build(output: Path, selected: list[str], render: bool) -> dict:
    if output.resolve().is_relative_to(ROOT.parents[1]):
        raise ValueError('Example artifacts must be outside the marketplace repository')
    output.mkdir(parents=True, exist_ok=True)
    artifact = output / 'visual-cases.pptx'
    if artifact.exists():
        raise ValueError('Preserve existing examples; choose a fresh output directory')
    asset = output / 'synthetic-interface.svg'
    asset.write_text(interface_svg(), encoding='utf-8')
    tokens = resolve_design_tokens('Data Driven', authoring=True)
    tokens.update(model_led=True, design_freedom='auto')
    entry = output / 'examples.js'
    entry.write_text('''const path=require('node:path');
const root=ROOT; const H=require(path.join(root,'scripts/pptx-helpers.js'));
const R=require(path.join(root,'scripts/pptx-page-runtime.js'));
const {SlideElementRegistry}=require(path.join(root,'scripts/pptx-element-registry.js'));
const pptxgen=require('pptxgenjs'); const pptx=new pptxgen(); const tokens=TOKENS;
H.applyTokens(pptx,tokens,'chinese');
const registry=new SlideElementRegistry({slideW:H.SLIDE_W_IN,slideH:H.SLIDE_H_IN});
const {cases}=require(path.join(root,'examples/main-session-visuals/paired-pages.js'));
const presentationCopy=[]; let n=0;
for(const name of SELECTED) for(const page of cases[name]) {
const slide=pptx.addSlide(); n++;
const ctx={pptx,slide,n,H,tokens,registry,presentationCopy,exampleAsset:{path:ASSET,width:1200,height:800}};
R.renderPage(ctx,page); presentationCopy.at(-1).headline=registry._slide(n).find(e=>e.type==='text').text;
}
registry.assertSafe(); registry.writeReport(process.argv[2]); H.writeCjkMap(process.argv[2],tokens);
require('node:fs').writeFileSync(path.join(__dirname,'presentation-copy.json'),JSON.stringify({slides:presentationCopy},null,2));
pptx.writeFile({fileName:process.argv[2]});
'''.replace('ROOT', json.dumps(str(ROOT))).replace('TOKENS', json.dumps(tokens)).replace('SELECTED', json.dumps(selected)).replace('ASSET', json.dumps(str(asset))), encoding='utf-8')
    result = subprocess.run(['node', str(ROOT / 'scripts/run_with_pptxgenjs.js'), '--output', str(artifact), str(entry)],
                            env={**os.environ, 'CLAUDE_PLUGIN_ROOT': str(ROOT), 'PPTX_HELPERS_DIR': str(ROOT / 'scripts')},
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    (output / 'build.log').write_text(result.stdout + '\n' + result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError(f'Example build failed; inspect {output / "build.log"}:\n{result.stderr[-5000:]}')
    validation = validate_pptx(artifact)
    report = {'ok': validation['ok'], 'kind': 'fixed-source-examples', 'model_generated': False,
              'cases': selected, 'pptx': str(artifact), 'sha256': file_sha256(artifact), 'package': validation,
              'asset': {'path': str(asset), 'source': 'synthetic interface fixture', 'sha256': file_sha256(asset)},
              'visual_acceptance': 'author inspection required; technical ok is not aesthetic approval'}
    if render:
        pdf, pages, warnings = render_pptx(artifact, output / 'render', 'slide', 'png', 144)
        report.update(pdf=str(pdf), pages=[str(page) for page in pages], render_warnings=warnings)
    (output / 'examples-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--case', default='all', choices=['all', 'mechanism', 'data', 'evidence'])
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--render', action='store_true')
    args = parser.parse_args()
    catalog = json.loads(CATALOG.read_text(encoding='utf-8'))
    if args.list:
        print(json.dumps(catalog, ensure_ascii=False, indent=2))
        return 0
    if not args.output_dir:
        parser.error('--output-dir is required to build examples')
    selected = [item['id'] for item in catalog['cases']] if args.case == 'all' else [args.case]
    report = build(args.output_dir.resolve(), selected, args.render)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
