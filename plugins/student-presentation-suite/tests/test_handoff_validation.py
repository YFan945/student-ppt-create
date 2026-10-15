from __future__ import annotations

import unittest

from shared.handoff_validation import handoff_errors


class HandoffValidationTests(unittest.TestCase):
    def test_delivery_directory_must_survive_handoff(self):
        brief = {'output_dir': 'outputs/independent'}
        self.assertEqual([], handoff_errors(brief, {'meta': dict(brief)}))
        for meta in ({}, {'output_dir': 'outputs/other'}):
            self.assertIn('.meta.output_dir', {item['path'] for item in handoff_errors(brief, {'meta': meta})})

    def test_matching_handoff_passes(self) -> None:
        brief = {
            "topic": "AI literacy",
            "scenario": "coursework",
            "language": "Chinese",
            "duration_min": 5,
            "slide_count": 2,
            "audience": {"type": "teacher", "depth": "standard"},
            "controls": {
                "max_words_per_slide": 40,
                "speaker_notes": True,
                "citations": "classroom",
            },
            "deliverables": ["pptx", "preview"],
        }
        spec = {
            "meta": {
                "topic": "AI literacy",
                "scenario": "coursework",
                "language": "Chinese",
                "duration_min": 5,
                "slide_count": 2,
                "audience_type": "teacher",
                "audience_depth": "standard",
                "max_words_per_slide": 40,
                "include_speaker_notes": True,
                "citation_style": "classroom",
                "deliverables": ["preview", "pptx"],
            }
        }
        self.assertEqual([], handoff_errors(brief, spec))

    def test_mismatch_reports_exact_field(self) -> None:
        errors = handoff_errors(
            {"topic": "A", "deliverables": ["pptx"]},
            {"meta": {"topic": "B", "deliverables": ["pptx", "pdf"]}},
        )
        self.assertEqual({".meta.topic", ".meta.deliverables"}, {item["path"] for item in errors})

    def test_missing_spec_fields_are_handoff_errors(self) -> None:
        brief = {
            "topic": "A",
            "scenario": "coursework",
            "audience": {"type": "teacher+classmates", "depth": "standard"},
            "language": "Chinese",
            "duration_min": 5,
            "controls": {"max_words_per_slide": 40, "speaker_notes": True},
            "deliverables": ["pptx", "preview"],
        }
        paths = {item["path"] for item in handoff_errors(brief, {"meta": {}})}
        self.assertTrue(
            {
                ".meta.topic",
                ".meta.scenario",
                ".meta.audience_type",
                ".meta.audience_depth",
                ".meta.language",
                ".meta.duration_min",
                ".meta.max_words_per_slide",
                ".meta.include_speaker_notes",
                ".meta.deliverables",
            }.issubset(paths)
        )

    def test_custom_visual_reference_must_match(self) -> None:
        custom = {
            "style_character": "Quiet field notes",
            "palette": {"canvas": "FFFFFF"},
            "backgrounds": {"cover": "Blue"},
            "svg_reference": {"name": "none", "usage": "none"},
        }
        brief = {"visual_style": "Other", "visual_style_custom": custom}
        spec = {
            "meta": {
                "visual_style": "Other",
                "visual_style_custom": {**custom, "style_character": "Loud poster"},
            }
        }
        paths = {item["path"] for item in handoff_errors(brief, spec)}
        self.assertIn(".meta.visual_style_custom", paths)
