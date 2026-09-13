"""pptxgenjs rich-text arrays (>=2 runs) must survive generation and validation.

pptxgenjs writes one stray <a:pPr> after every run; the schema allows at most
one, positioned first. normalize_unpacked removes the strays so inline
emphasis (multi-run coloured text) becomes usable instead of forbidden.
"""

from __future__ import annotations

import contextlib
import os
import re
import subprocess
import sys
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROBE = """
const pptxgen = require('pptxgenjs');
const pptx = new pptxgen();
const s = pptx.addSlide();
s.addText([
  { text: '流畅是', options: { fontFace: 'Cambria' } },
  { text: '能力', options: { fontFace: 'Cambria', color: '1D4ED8', bold: true } },
  { text: '，忠实是选择。', options: { fontFace: 'Cambria' } },
], { x: 0.5, y: 0.5, w: 9, h: 1.2, fontSize: 28, margin: 0 });
pptx.writeFile({ fileName: process.argv[2] });
"""


class RichTextNormalizeTests(unittest.TestCase):
    def test_rich_text_survives_wrapper_and_validates(self) -> None:
        from shared.pptx_runtime import validate_pptx

        # run_with_pptxgenjs.js only accepts deck scripts inside the project,
        # so the probe lives in a scratch dir under ROOT and is cleaned up.
        scratch = ROOT / ".test-scratch"
        scratch.mkdir(exist_ok=True)
        try:
            out = scratch / "rich.pptx"
            probe = scratch / "probe.js"
            probe.write_text(PROBE, encoding="utf-8")
            env = {
                **os.environ,
                "NODE_PATH": str(ROOT / "scripts"),
                "PYTHON": sys.executable,
            }
            # the wrapper only accepts project-relative, forward-slash paths
            subprocess.run(
                [
                    "node",
                    "scripts/run_with_pptxgenjs.js",
                    "--output",
                    ".test-scratch/rich.pptx",
                    ".test-scratch/probe.js",
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )

            findings = validate_pptx(out)
            errors = [f for f in findings if getattr(f, "severity", "") == "error"]
            self.assertEqual([], errors)

            xml = zipfile.ZipFile(out).read("ppt/slides/slide1.xml").decode("utf-8")
            paragraphs = re.findall(r"<a:p>(.*?)</a:p>", xml, re.S)
            self.assertTrue(paragraphs)
            for paragraph in paragraphs:
                ppr_positions = [
                    match.start() for match in re.finditer(r"<a:pPr", paragraph)
                ]
                # at most one pPr and it must open the paragraph
                self.assertLessEqual(len(ppr_positions), 1)
                if ppr_positions:
                    self.assertEqual(0, ppr_positions[0])
            # inline emphasis preserved: 3 runs, accent colour on the middle one
            self.assertEqual(3, len(re.findall(r"<a:r>", xml)))
            self.assertIn("1D4ED8", xml)
        finally:
            if scratch.exists():
                for leftover in scratch.iterdir():
                    with contextlib.suppress(OSError):
                        leftover.unlink()
                with contextlib.suppress(OSError):
                    scratch.rmdir()


if __name__ == "__main__":
    unittest.main()
