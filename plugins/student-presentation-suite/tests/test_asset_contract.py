"""Intentional placeholders retain provenance and legacy permission boundaries."""
from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.asset_contract import validate_assets


def fixture():
    return {"deck": "demo", "placeholder_policy": "allow", "assets": [{
        "slide": 1, "purpose": "装置照片区域", "source": "placeholder:device",
        "permission": "suite-original", "alt_text": "采集装置的示意占位", "fallback": "替换装置照片",
        "placeholder": {"kind": "photo-slot", "label": "素材待替换", "replacement": "装置实拍照片", "reason": "用户尚未提供"},
    }]}


class AssetContractTests(unittest.TestCase):
    def test_allowed_native_placeholder_requires_visible_label(self):
        data = fixture()
        self.assertTrue(validate_assets(data, Path.cwd(), ["装置照片区域\n素材待替换"])['ok'])
        self.assertFalse(validate_assets(data, Path.cwd(), ["装置照片区域"])['ok'])
        self.assertFalse(validate_assets(data, Path.cwd(), [])['ok'])
        self.assertFalse(validate_assets({'deck': 'demo', 'assets': []}, Path.cwd(), ['素材待替换'])['ok'])

    def test_legacy_default_and_explicit_prohibition_are_preserved(self):
        for policy in (None, 'forbid'):
            data = fixture()
            if policy is None:
                data.pop('placeholder_policy')
            else:
                data['placeholder_policy'] = policy
            self.assertFalse(validate_assets(data, Path.cwd())['ok'])

    def test_placeholder_cannot_claim_factual_source_or_lack_replacement(self):
        base = fixture()
        for key, value in [('source', 'real-photo'), ('permission', 'licensed')]:
            data = copy.deepcopy(base)
            data['assets'][0][key] = value
            self.assertFalse(validate_assets(data, Path.cwd())['ok'])
        for key in ('placeholder',):
            data = copy.deepcopy(base)
            data['assets'][0].pop(key)
            self.assertFalse(validate_assets(data, Path.cwd())['ok'])
        data = copy.deepcopy(base)
        data['assets'][0]['placeholder']['replacement'] = '   '
        self.assertFalse(validate_assets(data, Path.cwd())['ok'])

    def test_relative_file_dimensions_and_protected_region_remain_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.new('RGB', (40, 20)).save(root / 'figure.png')
            data = fixture()
            asset = data['assets'][0]
            asset.update(path='figure.png', width=40, height=20)
            self.assertTrue(validate_assets(data, root)['ok'])
            asset['width'] = 41
            self.assertFalse(validate_assets(data, root)['ok'])
            asset['width'] = 40
            asset['preserve_region'] = {'x': 0, 'y': 0, 'w': 1, 'h': 1}
            asset['crop'] = {'x': 0, 'y': 0, 'w': 0.5, 'h': 1}
            self.assertFalse(validate_assets(data, root)['ok'])

    def test_generated_placeholder_keeps_generation_provenance(self):
        data = fixture()
        data['assets'][0]['permission'] = 'generated'
        self.assertFalse(validate_assets(data, Path.cwd())['ok'])
        data['assets'][0]['prompt'] = 'Concept illustration for a future device photo slot'
        self.assertTrue(validate_assets(data, Path.cwd())['ok'])
