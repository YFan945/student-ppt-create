from __future__ import annotations

import sys
import tempfile
import unittest
import warnings
import zipfile
from io import BytesIO
from pathlib import Path
from unittest import mock

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import shared.pptx_static_core as core


def slide_xml(text: str, ph_type: str = "title", explicit_sz: str | None = None) -> str:
    rpr = f'<a:rPr sz="{explicit_sz}"/>' if explicit_sz else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld><p:spTree>
    <p:sp>
      <p:nvSpPr><p:cNvPr id="2" name="{ph_type} 1"/><p:nvPr><p:ph type="{ph_type}"/></p:nvPr></p:nvSpPr>
      <p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r>{rpr}<a:t>{text}</a:t></a:r></a:p></p:txBody>
    </p:sp>
  </p:spTree></p:cSld>
</p:sld>"""


def bounded_slide_xml(text: str, x: int, y: int, cx: int, cy: int, typeface: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld><p:spTree>
    <p:sp>
      <p:nvSpPr><p:cNvPr id="2" name="Body 1"/><p:nvPr><p:ph type="body"/></p:nvPr></p:nvSpPr>
      <p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm></p:spPr>
      <p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr sz="2400"><a:latin typeface="{typeface}"/></a:rPr><a:t>{text}</a:t></a:r></a:p></p:txBody>
    </p:sp>
  </p:spTree></p:cSld>
</p:sld>"""


def rels_to_layout() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
</Relationships>"""


def rels_to_master() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>
</Relationships>"""


def style_xml(part: str, title_sz: str = "2800", body_sz: str = "2400") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<p:{part} xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
          xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld><p:spTree/></p:cSld>
  <p:txStyles>
    <a:titleStyle><a:lvl1pPr><a:defRPr sz="{title_sz}"/></a:lvl1pPr></a:titleStyle>
    <a:bodyStyle><a:lvl1pPr><a:defRPr sz="{body_sz}"/></a:lvl1pPr></a:bodyStyle>
  </p:txStyles>
</p:{part}>"""


class PptxStaticCoreTests(unittest.TestCase):
    def write_pptx(
        self,
        path: Path,
        slides: list[str],
        *,
        layout_title_sz: str | None = None,
        layout_body_sz: str | None = None,
        master_title_sz: str = "2800",
        master_body_sz: str = "2400",
    ) -> None:
        with zipfile.ZipFile(path, "w") as zf:
            for idx, slide in enumerate(slides, start=1):
                zf.writestr(f"ppt/slides/slide{idx}.xml", slide)
                zf.writestr(f"ppt/slides/_rels/slide{idx}.xml.rels", rels_to_layout())
            if layout_title_sz or layout_body_sz:
                zf.writestr(
                    "ppt/slideLayouts/slideLayout1.xml",
                    style_xml("sldLayout", layout_title_sz or "2800", layout_body_sz or "2400"),
                )
            else:
                zf.writestr(
                    "ppt/slideLayouts/slideLayout1.xml",
                    """<?xml version="1.0" encoding="UTF-8"?>
<p:sldLayout xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
             xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld><p:spTree/></p:cSld>
</p:sldLayout>""",
                )
            zf.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", rels_to_master())
            zf.writestr(
                "ppt/slideMasters/slideMaster1.xml",
                style_xml("sldMaster", master_title_sz, master_body_sz),
            )

    def test_resolves_master_title_font_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / "master-title-size.pptx"
            self.write_pptx(pptx, [slide_xml("Inherited title")])

            result = core.inspect_pptx(pptx)

        self.assertNotIn("error", result)
        self.assertEqual(result["findings"], [])

    def test_caches_inherited_context_per_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / "two-slides-one-layout.pptx"
            self.write_pptx(pptx, [slide_xml("First"), slide_xml("Second")])

            with mock.patch.object(
                core,
                "inherited_font_context_for_layout",
                wraps=core.inherited_font_context_for_layout,
            ) as wrapped:
                result = core.inspect_pptx(pptx)

        self.assertEqual(result["findings"], [])
        self.assertEqual(wrapped.call_count, 1)
        self.assertEqual(0, result["deck_statistics"]["distinct_layout_patterns"])

    def test_flags_large_overlap_between_non_text_visible_objects(self) -> None:
        overlap_slide = """<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main'
          xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'><p:cSld><p:spTree>
          <p:pic><p:spPr><a:xfrm><a:off x='1000000' y='1000000'/><a:ext cx='3000000' cy='2000000'/></a:xfrm></p:spPr></p:pic>
          <p:pic><p:spPr><a:xfrm><a:off x='2000000' y='1500000'/><a:ext cx='3000000' cy='2000000'/></a:xfrm></p:spPr></p:pic>
          </p:spTree></p:cSld></p:sld>"""
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / "overlap.pptx"
            self.write_pptx(pptx, [overlap_slide])
            result = core.inspect_pptx(pptx)
        risks = [risk for finding in result["findings"] for risk in finding["risk"]]
        self.assertIn("unexpected-object-overlap-risk", risks)

    def test_does_not_flag_label_contained_by_card_as_overlap(self) -> None:
        contained_slide = """<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main'
          xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'><p:cSld><p:spTree>
          <p:sp><p:spPr><a:xfrm><a:off x='1000000' y='1000000'/><a:ext cx='4000000' cy='2500000'/></a:xfrm></p:spPr></p:sp>
          <p:sp><p:spPr><a:xfrm><a:off x='1400000' y='1400000'/><a:ext cx='3200000' cy='800000'/></a:xfrm></p:spPr>
          <p:txBody><a:p><a:r><a:rPr sz='2400'/><a:t>Card label</a:t></a:r></a:p></p:txBody></p:sp>
          </p:spTree></p:cSld></p:sld>"""
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / "contained.pptx"
            self.write_pptx(pptx, [contained_slide])
            result = core.inspect_pptx(pptx)
        risks = [risk for finding in result["findings"] for risk in finding["risk"]]
        self.assertNotIn("unexpected-object-overlap-risk", risks)

    def test_flags_low_resolution_embedded_picture(self) -> None:
        image_buffer = BytesIO()
        Image.new("RGB", (20, 20), "navy").save(image_buffer, format="PNG")
        picture_slide = """<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main'
          xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'
          xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'><p:cSld><p:spTree>
          <p:pic><p:blipFill><a:blip r:embed='rIdImage'/></p:blipFill><p:spPr><a:xfrm><a:off x='0' y='0'/><a:ext cx='9144000' cy='9144000'/></a:xfrm></p:spPr></p:pic>
          </p:spTree></p:cSld></p:sld>"""
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / "low-res.pptx"
            self.write_pptx(pptx, [picture_slide])
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(pptx, "a") as archive:
                    archive.writestr("ppt/slides/_rels/slide1.xml.rels", """<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>
                    <Relationship Id='rIdImage' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/image' Target='../media/image1.png'/>
                    </Relationships>""")
                    archive.writestr("ppt/media/image1.png", image_buffer.getvalue())
            result = core.inspect_pptx(pptx)
        risks = [risk for finding in result["findings"] for risk in finding["risk"]]
        self.assertIn("low-resolution-image-risk", risks)

    def test_flags_stretched_embedded_picture(self) -> None:
        image_buffer = BytesIO()
        Image.new("RGB", (2000, 2000), "navy").save(image_buffer, format="PNG")
        picture_slide = """<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main'
          xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'
          xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'><p:cSld><p:spTree>
          <p:pic><p:blipFill><a:blip r:embed='rIdImage'/></p:blipFill><p:spPr><a:xfrm><a:off x='0' y='0'/><a:ext cx='9144000' cy='4572000'/></a:xfrm></p:spPr></p:pic>
          </p:spTree></p:cSld></p:sld>"""
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / "stretched.pptx"
            self.write_pptx(pptx, [picture_slide])
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(pptx, "a") as archive:
                    archive.writestr("ppt/slides/_rels/slide1.xml.rels", """<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>
                    <Relationship Id='rIdImage' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/image' Target='../media/image1.png'/>
                    </Relationships>""")
                    archive.writestr("ppt/media/image1.png", image_buffer.getvalue())
            result = core.inspect_pptx(pptx)
        risks = [risk for finding in result["findings"] for risk in finding["risk"]]
        self.assertIn("image-aspect-distortion-risk", risks)

    def test_flags_title_outside_title_zone_and_footer_invasion(self) -> None:
        slide = """<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main'
          xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'><p:cSld><p:spTree>
          <p:sp><p:nvSpPr><p:cNvPr id='2' name='Title 1'/><p:nvPr><p:ph type='title'/></p:nvPr></p:nvSpPr>
          <p:spPr><a:xfrm><a:off x='300000' y='2000000'/><a:ext cx='5000000' cy='1000000'/></a:xfrm></p:spPr>
          <p:txBody><a:p><a:r><a:rPr sz='3000'/><a:t>Late title</a:t></a:r></a:p></p:txBody></p:sp>
          <p:sp><p:nvSpPr><p:cNvPr id='3' name='Body 1'/><p:nvPr><p:ph type='body'/></p:nvPr></p:nvSpPr>
          <p:spPr><a:xfrm><a:off x='300000' y='6500000'/><a:ext cx='3000000' cy='500000'/></a:xfrm></p:spPr>
          <p:txBody><a:p><a:r><a:rPr sz='2400'/><a:t>Footer invasion</a:t></a:r></a:p></p:txBody></p:sp>
          </p:spTree></p:cSld></p:sld>"""
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / "zones.pptx"
            self.write_pptx(pptx, [slide])
            result = core.inspect_pptx(pptx)
        risks = [risk for finding in result["findings"] for risk in finding["risk"]]
        self.assertIn("title-outside-title-zone", risks)
        self.assertIn("footer-zone-invasion", risks)

    def test_flags_low_contrast_text_and_insufficient_gutter(self) -> None:
        slide = """<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main'
          xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'><p:cSld><p:spTree>
          <p:sp><p:spPr><a:xfrm><a:off x='1000000' y='1000000'/><a:ext cx='1000000' cy='1000000'/></a:xfrm><a:solidFill><a:srgbClr val='EEEEEE'/></a:solidFill></p:spPr>
          <p:txBody><a:p><a:r><a:rPr sz='2400'><a:solidFill><a:srgbClr val='CCCCCC'/></a:solidFill></a:rPr><a:t>Low contrast</a:t></a:r></a:p></p:txBody></p:sp>
          <p:pic><p:spPr><a:xfrm><a:off x='2050000' y='1000000'/><a:ext cx='1000000' cy='1000000'/></a:xfrm></p:spPr></p:pic>
          </p:spTree></p:cSld></p:sld>"""
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / "contrast-gutter.pptx"
            self.write_pptx(pptx, [slide])
            result = core.inspect_pptx(pptx)
        risks = [risk for finding in result["findings"] for risk in finding["risk"]]
        self.assertIn("low-foreground-background-contrast", risks)
        self.assertIn("insufficient-gutter-risk", risks)

    def test_flags_connector_routed_through_unrelated_object(self) -> None:
        slide = """<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main'
          xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'><p:cSld><p:spTree>
          <p:cxnSp><p:spPr><a:xfrm><a:off x='500000' y='2000000'/><a:ext cx='5000000' cy='0'/></a:xfrm><a:ln w='25400'/></p:spPr></p:cxnSp>
          <p:pic><p:spPr><a:xfrm><a:off x='2500000' y='1500000'/><a:ext cx='1000000' cy='1000000'/></a:xfrm></p:spPr></p:pic>
          </p:spTree></p:cSld></p:sld>"""
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / "connector-crossing.pptx"
            self.write_pptx(pptx, [slide])
            result = core.inspect_pptx(pptx)
        risks = [risk for finding in result["findings"] for risk in finding["risk"]]
        self.assertIn("connector-crosses-object-risk", risks)

    def test_flags_chart_without_title_and_small_labels(self) -> None:
        slide = """<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main'
          xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'
          xmlns:c='http://schemas.openxmlformats.org/drawingml/2006/chart'
          xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'><p:cSld><p:spTree>
          <p:graphicFrame><p:xfrm><a:off x='1000000' y='1000000'/><a:ext cx='4000000' cy='3000000'/></p:xfrm>
          <a:graphic><a:graphicData><c:chart r:id='rIdChart'/></a:graphicData></a:graphic></p:graphicFrame>
          </p:spTree></p:cSld></p:sld>"""
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / "chart.pptx"
            self.write_pptx(pptx, [slide])
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(pptx, "a") as archive:
                    archive.writestr("ppt/slides/_rels/slide1.xml.rels", """<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>
                    <Relationship Id='rIdChart' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart' Target='../charts/chart1.xml'/>
                    </Relationships>""")
                    archive.writestr("ppt/charts/chart1.xml", """<c:chartSpace xmlns:c='http://schemas.openxmlformats.org/drawingml/2006/chart'
                    xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'><c:chart><c:plotArea><a:p><a:r><a:rPr sz='1400'/><a:t>Small label</a:t></a:r></a:p></c:plotArea></c:chart></c:chartSpace>""")
            result = core.inspect_pptx(pptx)
        risks = [risk for finding in result["findings"] for risk in finding["risk"]]
        self.assertIn("chart-missing-title-risk", risks)
        self.assertIn("chart-label-font-size-below-18pt", risks)

    def test_flags_explicit_text_padding_below_token(self) -> None:
        slide = """<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main'
          xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'><p:cSld><p:spTree>
          <p:sp><p:nvSpPr><p:cNvPr id='2' name='Body'/><p:nvPr><p:ph type='body'/></p:nvPr></p:nvSpPr>
          <p:spPr><a:xfrm><a:off x='500000' y='1000000'/><a:ext cx='3000000' cy='1000000'/></a:xfrm></p:spPr>
          <p:txBody><a:bodyPr lIns='100000' rIns='100000'/><a:p><a:r><a:rPr sz='2400'/><a:t>Too close</a:t></a:r></a:p></p:txBody></p:sp>
          </p:spTree></p:cSld></p:sld>"""
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / "padding.pptx"
            self.write_pptx(pptx, [slide])
            result = core.inspect_pptx(pptx)
        risks = [risk for finding in result["findings"] for risk in finding["risk"]]
        self.assertIn("text-box-padding-below-16pt", risks)

    def test_flags_nearly_aligned_stacked_objects(self) -> None:
        slide = """<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main'
          xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'><p:cSld><p:spTree>
          <p:pic><p:spPr><a:xfrm><a:off x='1000000' y='1000000'/><a:ext cx='2000000' cy='1000000'/></a:xfrm></p:spPr></p:pic>
          <p:pic><p:spPr><a:xfrm><a:off x='1050000' y='2500000'/><a:ext cx='2000000' cy='1000000'/></a:xfrm></p:spPr></p:pic>
          </p:spTree></p:cSld></p:sld>"""
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / "alignment.pptx"
            self.write_pptx(pptx, [slide])
            result = core.inspect_pptx(pptx)
        risks = [risk for finding in result["findings"] for risk in finding["risk"]]
        self.assertIn("alignment-tolerance-risk", risks)

    def test_resolves_layout_body_style_and_reports_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / "layout-body-size.pptx"
            self.write_pptx(
                pptx,
                [slide_xml("Body text from layout", ph_type="body")],
                layout_body_sz="1800",
                master_body_sz="2600",
            )

            result = core.inspect_pptx(pptx)

        self.assertEqual(result["findings"][0]["min_font_pt"], 18)
        self.assertEqual(result["findings"][0]["font_size_source"], "layout-style")
        self.assertIn("font-size-below-20pt", result["findings"][0]["risk"])

    def test_explicit_font_size_overrides_inherited_style(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / "explicit-size.pptx"
            self.write_pptx(
                pptx,
                [slide_xml("Explicit small title", explicit_sz="1800")],
                master_title_sz="3200",
            )

            result = core.inspect_pptx(pptx)

        self.assertEqual(result["findings"][0]["min_font_pt"], 18)
        self.assertEqual(result["findings"][0]["font_size_source"], "explicit")
        self.assertIn("heading-font-size-below-24pt", result["findings"][0]["risk"])

    def test_subtitle_below_24pt_is_not_treated_as_primary_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / "subtitle-size.pptx"
            self.write_pptx(
                pptx,
                [slide_xml("Readable subtitle", ph_type="subTitle", explicit_sz="2200")],
            )

            result = core.inspect_pptx(pptx)

        risks = result["findings"][0]["risk"] if result["findings"] else []
        self.assertNotIn("heading-font-size-below-24pt", risks)

    def test_flags_outside_geometry_and_uncommon_font(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / "geometry-font.pptx"
            self.write_pptx(
                pptx,
                [
                    bounded_slide_xml(
                        "Outside text",
                        x=12_000_000,
                        y=100_000,
                        cx=1_000_000,
                        cy=500_000,
                        typeface="Rare Decorative Font",
                    )
                ],
            )
            result = core.inspect_pptx(pptx)
        risks = set(result["findings"][0]["risk"])
        self.assertIn("shape-outside-slide", risks)
        self.assertIn("font-compatibility-review-required", risks)
        self.assertIn("Rare Decorative Font", result["font_families"])

    # ── Text overflow estimation ──────────────────────────────

    def test_cjk_overflow_detected_with_long_text(self) -> None:
        """长中文文本在小盒子里应检测到垂直溢出风险"""
        overflow = core.estimate_text_overflow(
            chars=120, is_cjk=True, font_size_pt=22,
            box_width_emu=int(10 * core.EMU_PER_CM),   # 10cm 宽
            box_height_emu=int(5 * core.EMU_PER_CM),    # 5cm 高
        )
        self.assertIsNotNone(overflow)
        # 22pt 中文: 字宽≈0.77cm, 10cm/0.77≈13 字/行, 120 字需 10 行
        # 行高 1.18× ≈ 0.92cm, 10 行≈9.2cm > 5cm → fill_ratio > 1.0
        self.assertGreater(overflow["fill_ratio"], 1.0)

    def test_cjk_text_fits_in_large_box(self) -> None:
        """短中文文本在大盒子里不应溢出"""
        overflow = core.estimate_text_overflow(
            chars=30, is_cjk=True, font_size_pt=22,
            box_width_emu=int(14 * core.EMU_PER_CM),   # 14cm 宽
            box_height_emu=int(8 * core.EMU_PER_CM),    # 8cm 高
        )
        self.assertIsNotNone(overflow)
        self.assertLess(overflow["fill_ratio"], 0.5)

    def test_english_overflow_detected(self) -> None:
        """长英文文本在小盒子里应检测到垂直溢出"""
        overflow = core.estimate_text_overflow(
            chars=200, is_cjk=False, font_size_pt=20,
            box_width_emu=int(10 * core.EMU_PER_CM),
            box_height_emu=int(4 * core.EMU_PER_CM),
        )
        self.assertIsNotNone(overflow)
        self.assertGreater(overflow["fill_ratio"], 0.85)

    def test_unknown_font_size_returns_none(self) -> None:
        """字号未知时无法估算"""
        overflow = core.estimate_text_overflow(
            chars=100, is_cjk=True, font_size_pt=None,
            box_width_emu=1_000_000, box_height_emu=1_000_000,
        )
        self.assertIsNone(overflow)

    def test_zero_dimensions_returns_none(self) -> None:
        """零尺寸文本框无法估算"""
        overflow = core.estimate_text_overflow(
            chars=50, is_cjk=True, font_size_pt=22,
            box_width_emu=0, box_height_emu=1_000_000,
        )
        self.assertIsNone(overflow)

    def test_very_short_text_never_overflows(self) -> None:
        """极短文本不应溢出"""
        overflow = core.estimate_text_overflow(
            chars=5, is_cjk=True, font_size_pt=22,
            box_width_emu=int(5 * core.EMU_PER_CM),
            box_height_emu=int(3 * core.EMU_PER_CM),
        )
        self.assertIsNotNone(overflow)
        self.assertLess(overflow["fill_ratio"], 0.85)

    def test_explicit_paragraphs_margins_and_indent_increase_estimated_lines(self) -> None:
        plain = core.estimate_text_overflow(
            chars=40, is_cjk=False, font_size_pt=20,
            box_width_emu=int(10 * core.EMU_PER_CM), box_height_emu=int(8 * core.EMU_PER_CM),
        )
        formatted = core.estimate_text_overflow(
            chars=40, is_cjk=False, font_size_pt=20,
            box_width_emu=int(10 * core.EMU_PER_CM), box_height_emu=int(8 * core.EMU_PER_CM),
            paragraphs=["twenty words split", "into separate paragraph"],
            horizontal_margin_emu=int(2 * core.EMU_PER_CM),
            vertical_margin_emu=int(1 * core.EMU_PER_CM),
            bullet_indent_emu=int(1 * core.EMU_PER_CM),
        )
        self.assertIsNotNone(plain)
        self.assertIsNotNone(formatted)
        self.assertGreater(formatted["est_lines"], plain["est_lines"])
        self.assertEqual(2.0, formatted["horizontal_margin_cm"])

    def test_pptx_with_overflowing_cjk_text_is_flagged(self) -> None:
        """生成的 PPTX 中长文本应触发真实裁切标记 text-vertical-overflow"""
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / "overflow.pptx"
            # ~100 中文字 + 24pt + 8cm×3cm 盒子 → 确定溢出
            # 24pt 字宽≈0.84cm, 8cm/0.84≈9 字/行, 100 字≈12 行
            # 行高 1.18× ≈ 1.00cm, 12 行≈12cm > 3cm → fill_ratio > 4.0
            chinese_text = (
                "人工智能技术正在深刻改变教育的面貌从个性化学习路径到智能评估系统"
                "自适应学习平台可以显著提升学生的学习效率和参与度"
            )
            self.write_pptx(
                pptx,
                [
                    bounded_slide_xml(
                        chinese_text,
                        x=500_000, y=1_500_000,
                        cx=int(8 * core.EMU_PER_CM),
                        cy=int(3 * core.EMU_PER_CM),
                        typeface="Microsoft YaHei",
                    )
                ],
            )
            result = core.inspect_pptx(pptx)
        risks = result["findings"][0]["risk"] if result["findings"] else []
        self.assertIn("text-vertical-overflow", risks)
        self.assertIn("overflow_estimate", result["findings"][0])

    def test_pptx_with_short_text_no_overflow_flag(self) -> None:
        """短文本 PPTX 不应触发溢出风险"""
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / "no-overflow.pptx"
            self.write_pptx(
                pptx,
                [
                    bounded_slide_xml(
                        "Short title here",
                        x=500_000, y=1_500_000,
                        cx=int(12 * core.EMU_PER_CM),
                        cy=int(7 * core.EMU_PER_CM),
                        typeface="Calibri",
                    )
                ],
            )
            result = core.inspect_pptx(pptx)
        risks = result["findings"][0]["risk"] if result["findings"] else []
        self.assertNotIn("text-vertical-overflow-risk", risks)
        self.assertNotIn("text-vertical-overflow", risks)

    def test_explicit_spc_pts_drives_line_height(self) -> None:
        from xml.etree import ElementTree as ET

        xml = """<p:sp xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
          <p:txBody><a:p><a:pPr><a:lnSpc><a:spcPts val="5074"/></a:lnSpc></a:pPr></a:p></p:txBody>
        </p:sp>"""
        self.assertEqual(50.74, core.shape_line_height_pt(ET.fromstring(xml), 43.0))

    def test_line_height_fallback_matches_helpers(self) -> None:
        overflow = core.estimate_text_overflow(
            chars=10, is_cjk=True, font_size_pt=32,
            box_width_emu=int(20 * core.EMU_PER_CM),
            box_height_emu=int(10 * core.EMU_PER_CM),
        )
        self.assertIsNotNone(overflow)
        self.assertAlmostEqual(32 * core.LINE_HEIGHT_RATIO, overflow["line_height_pt"], places=2)

    def test_fill_between_risk_and_clipping_is_advisory(self) -> None:
        overflow = core.estimate_text_overflow(
            chars=10, is_cjk=True, font_size_pt=32,
            box_width_emu=int(20 * core.EMU_PER_CM),
            box_height_emu=int(1.45 * core.EMU_PER_CM),
            line_height_pt=32 * 1.18,
        )
        self.assertIsNotNone(overflow)
        self.assertGreater(overflow["fill_ratio_raw"], core.OVERFLOW_BOX_FILL_RATIO)
        self.assertLessEqual(overflow["fill_ratio_raw"], core.CLIPPING_FILL_RATIO)


    # ── CJK detection across languages ──────────────────

    def test_cjk_detects_japanese(self) -> None:
        """has_cjk should detect Japanese kanji + hiragana."""
        self.assertTrue(core.has_cjk("日本語のテキスト"))
        self.assertTrue(core.has_cjk("東京タワー"))

    def test_cjk_detects_korean(self) -> None:
        """has_cjk should detect Korean Hangul (U+AC00-D7AF)."""
        self.assertTrue(core.has_cjk("한국어 텍스트"))
        self.assertTrue(core.has_cjk("안녕하세요"))

    def test_cjk_rejects_pure_ascii(self) -> None:
        """has_cjk should return False for pure Latin text."""
        self.assertFalse(core.has_cjk("Hello world"))
        self.assertFalse(core.has_cjk("Testing 123"))

    def test_cjk_rejects_emoji_only(self) -> None:
        """has_cjk should return False for emoji-heavy text."""
        self.assertFalse(core.has_cjk("🚀✨🎉"))


if __name__ == "__main__":
    unittest.main()
