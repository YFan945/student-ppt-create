from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from test_helpers import load_module

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bump_version.py"


class BumpVersionTests(unittest.TestCase):
    def test_set_key_updates_dict(self) -> None:
        module = load_module(SCRIPT)
        data = {"version": "0.4.0", "name": "test"}
        result = module._set_key(data, "version", "0.5.0")
        self.assertEqual("0.5.0", result["version"])
        self.assertEqual("test", result["name"])

    def test_current_version_reads_plugin_json(self) -> None:
        module = load_module(SCRIPT)
        version = module.current_version()
        self.assertIsInstance(version, str)
        self.assertNotEqual("0.0.0", version)

    def test_bump_dry_run_does_not_write_files(self) -> None:
        module = load_module(SCRIPT)
        hashes = {path: path.read_bytes() for path, _, _ in module.FILES_TO_UPDATE}
        hashes.update({path: path.read_bytes() for path in module.SKILL_FILES})
        result = module.bump("99.99.99", dry_run=True)
        self.assertEqual(0, result)
        for path in hashes:
            self.assertEqual(hashes[path], path.read_bytes(), f"{path} should not be modified during dry-run")

    def test_update_skill_version_updates_frontmatter_only(self) -> None:
        module = load_module(SCRIPT)
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "SKILL.md"
            path.write_text(
                "---\nname: demo\ndescription: demo\nversion: 0.5.1\n---\n\nVersion 0.5.1 in prose.\n",
                encoding="utf-8",
            )
            module.update_skill_version(path, "0.6.0")
            text = path.read_text(encoding="utf-8")
            self.assertIn("version: 0.6.0", text)
            self.assertIn("Version 0.5.1 in prose.", text)

    def test_bump_rejects_invalid_semver(self) -> None:
        module = load_module(SCRIPT)
        result = module.bump("banana", dry_run=True)
        self.assertEqual(1, result)

    def test_bump_invalid_file_returns_error(self) -> None:
        module = load_module(SCRIPT)
        with mock.patch.object(module, "FILES_TO_UPDATE", [
            (Path("/nonexistent/file.json"), "version",
             lambda data, ver: module._set_key(data, "version", ver)),
        ]):
            result = module.bump("99.99.99", dry_run=True)
            self.assertEqual(1, result)

    def test_update_plugin_entry_raises_on_missing_plugins(self) -> None:
        module = load_module(SCRIPT)
        with self.assertRaises(ValueError):
            module._update_plugin_entry({}, "1.0.0")

    def test_update_plugin_entry_raises_on_wrong_plugin(self) -> None:
        module = load_module(SCRIPT)
        with self.assertRaises(ValueError):
            module._update_plugin_entry(
                {"plugins": [{"name": "other-plugin", "version": "0.1.0"}]},
                "1.0.0",
            )

    def test_update_plugin_entry_updates_correct_plugin(self) -> None:
        module = load_module(SCRIPT)
        result = module._update_plugin_entry(
            {"plugins": [{"name": "student-presentation-suite", "version": "0.4.0"}]},
            "0.5.0",
        )
        self.assertEqual("0.5.0", result["plugins"][0]["version"])

    def test_updaters_do_not_mutate_their_input(self) -> None:
        """回滚依赖升级前的对象保持不变；原地更新会让回滚变成静默空操作。"""
        module = load_module(SCRIPT)
        original = {"version": "0.4.0", "name": "test"}
        snapshot = copy.deepcopy(original)
        module._set_key(original, "version", "0.9.0")
        self.assertEqual(snapshot, original)

        manifest = {"plugins": [{"name": "student-presentation-suite", "version": "0.4.0"}]}
        manifest_snapshot = copy.deepcopy(manifest)
        module._update_plugin_entry(manifest, "0.9.0")
        self.assertEqual(manifest_snapshot, manifest)

    def test_sync_package_lock_updates_both_version_fields(self) -> None:
        module = load_module(SCRIPT)
        with TemporaryDirectory() as tmp:
            lock = Path(tmp) / "package-lock.json"
            lock.write_text(
                json.dumps(
                    {
                        "name": "student-presentation-suite",
                        "version": "0.8.0",
                        "lockfileVersion": 3,
                        "packages": {
                            "": {"name": "student-presentation-suite", "version": "0.8.0"},
                            "node_modules/pptxgenjs": {"version": "3.12.0"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(module, "LOCKFILE", lock):
                self.assertEqual("updated", module.sync_package_lock("0.9.0"))
                self.assertEqual("unchanged", module.sync_package_lock("0.9.0"))
            data = json.loads(lock.read_text(encoding="utf-8"))
            self.assertEqual("0.9.0", data["version"])
            self.assertEqual("0.9.0", data["packages"][""]["version"])
            # 依赖条目不得被这次升级碰到
            self.assertEqual("3.12.0", data["packages"]["node_modules/pptxgenjs"]["version"])

    def test_sync_package_lock_reports_a_missing_lockfile(self) -> None:
        module = load_module(SCRIPT)
        with TemporaryDirectory() as tmp:
            with mock.patch.object(module, "LOCKFILE", Path(tmp) / "absent.json"):
                self.assertEqual("missing", module.sync_package_lock("0.9.0"))

    def test_every_version_source_is_synchronized(self) -> None:
        """bump_version 覆盖的字段必须与 check_installed_version 读取的字段一致。"""
        module = load_module(SCRIPT)
        covered = {path.name for path, _, _ in module.FILES_TO_UPDATE}
        covered.add(module.LOCKFILE.name)
        self.assertIn("package-lock.json", covered)
        for name in ("marketplace.json", "plugin.json", "package.json"):
            self.assertIn(name, covered)


if __name__ == "__main__":
    unittest.main()
