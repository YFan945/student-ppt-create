"""fetch-images executes the image-sources.json contract with permission gates."""

from __future__ import annotations

import base64
import json
import sys
import unittest
from pathlib import Path

from shared.pptx_runtime import fetch_images

ROOT = Path(__file__).resolve().parents[1]
TINY_PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


class FetchImagesTests(unittest.TestCase):
    def _make_contract(self, tmp: Path, allow_web: bool) -> Path:
        assets = tmp / "assets"
        assets.mkdir(exist_ok=True)
        (assets / "lab-photo.png").write_bytes(base64.b64decode(TINY_PNG))
        fake_gen = (
            f"{sys.executable.replace(chr(92), '/')} -c "
            f'"import base64,pathlib,sys; '
            f"pathlib.Path(sys.argv[1]).write_bytes(base64.b64decode('{TINY_PNG}'))\" {{output}}"
        )
        sources = {
            "version": "0.8",
            "permission": {
                "allow_web_search": allow_web,
                "allow_generation": True,
                "record_source": True,
            },
            "providers": [
                {
                    "id": "user-photos",
                    "kind": "user-assets",
                    "enabled": True,
                    "assets_dir": str(assets),
                    "permission": "user-provided",
                },
                {
                    "id": "fake-gen",
                    "kind": "image-generation",
                    "enabled": True,
                    "command": fake_gen,
                    "permission": "generated",
                },
                {
                    "id": "web",
                    "kind": "web-search",
                    "enabled": True,
                    "command": "curl -sL {url} -o {output}",
                    "requires": ["curl"],
                    "permission": "licensed",
                },
            ],
        }
        contract = tmp / "image-sources.json"
        contract.write_text(json.dumps(sources, ensure_ascii=False), encoding="utf-8")
        return contract

    def test_user_assets_win_and_generation_fills_gaps(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            contract = self._make_contract(tmp_path, allow_web=False)
            out = tmp_path / "fetched"
            report = fetch_images(
                contract, ["lab photo", "生成封面"], out
            )
            statuses = {r["query"]: r for r in report["records"]}
            self.assertEqual("user-photos", statuses["lab photo"]["provider_id"])
            self.assertEqual("fake-gen", statuses["生成封面"]["provider_id"])
            self.assertTrue((out / "lab-photo-user-photos.png").exists())
            self.assertTrue(any(r["status"] == "fetched" for r in report["records"]))

    def test_web_search_is_gated_by_permission(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            contract = self._make_contract(tmp_path, allow_web=False)
            report = fetch_images(contract, ["campus"], tmp_path / "fetched")
            reasons = " ".join(report["gate_reasons"])
            self.assertIn("allow_web_search", reasons)

    def test_disabled_provider_is_skipped(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            contract = self._make_contract(tmp_path, allow_web=False)
            data = json.loads(contract.read_text(encoding="utf-8"))
            for provider in data["providers"]:
                provider["enabled"] = False
            contract.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            report = fetch_images(contract, ["anything"], tmp_path / "fetched")
            self.assertFalse(report["records"][0]["status"] == "fetched")


if __name__ == "__main__":
    unittest.main()
