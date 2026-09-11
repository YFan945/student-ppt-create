from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.runtime_paths import get_pptx_runtime_root, output_root


def load_env_checker():
    path = ROOT / "scripts/check_claude_pptx_env.py"
    spec = importlib.util.spec_from_file_location("check_claude_pptx_env", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RuntimePathTests(unittest.TestCase):
    def test_output_root_honors_explicit_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            requested = Path(tmp) / "custom deliverables"
            self.assertEqual(requested.resolve(), output_root(requested))

    def test_output_root_falls_back_to_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                Path(tmp).resolve() / "outputs",
                output_root(env={}, cwd=Path(tmp)),
            )

    def test_output_root_ignores_msys_style_project_dir(self) -> None:
        """CLAUDE_PROJECT_DIR 是 Git-Bash 的 /e/... 形式时不得拼接到当前盘符。

        旧实现的两个缺陷叠加会把输出写到 `E:/e/student-ppt-create/outputs`：
        `env or os.environ` 让空 dict 泄漏真实环境变量；`Path('/e/x').resolve()`
        在 Windows 上错误拼接到当前盘符根。
        """
        self.assertEqual(
            Path("E:/student-ppt-create/outputs"),
            output_root(env={"CLAUDE_PROJECT_DIR": "/e/student-ppt-create"}, cwd=Path("C:/")),
        )

    def test_output_root_uses_project_and_never_plugin_cache(self) -> None:
        with tempfile.TemporaryDirectory(prefix="Claude Project ") as tmp:
            result = output_root(env={"CLAUDE_PROJECT_DIR": tmp})
            self.assertEqual(Path(tmp).resolve() / "outputs", result)
            self.assertNotEqual(ROOT / "outputs", result)

    def test_get_pptx_runtime_root_returns_suite_owned_path(self) -> None:
        root = get_pptx_runtime_root()
        self.assertTrue(root.is_dir())
        self.assertTrue((root / "__init__.py").is_file())
        self.assertTrue((ROOT / "scripts" / "pptx_tool.py").is_file())

    def test_pptxgenjs_resolution_order(self) -> None:
        module = load_env_checker()
        success = json.dumps({"path": "X:/node_modules/pptxgenjs/index.js", "version": "4.0.1"})
        with mock.patch.object(module, "command_path", side_effect=lambda name, *_: name):
            with mock.patch.object(module, "npm_global_root", return_value=Path("G:/npm")):
                with mock.patch.object(module, "run_probe", return_value=(True, success)):
                    self.assertEqual("project", module.resolve_pptxgenjs(Path("P:/project"))["module_source"])
                with mock.patch.object(
                    module, "run_probe", side_effect=[(False, "no"), (True, success)]
                ):
                    self.assertEqual("plugin", module.resolve_pptxgenjs(Path("P:/project"))["module_source"])
                with mock.patch.object(
                    module,
                    "run_probe",
                    side_effect=[(False, "no"), (False, "no"), (True, success)],
                ):
                    self.assertEqual("global", module.resolve_pptxgenjs(Path("P:/project"))["module_source"])

    def test_env_modes_report_distinct_workflow_capabilities(self) -> None:
        module = load_env_checker()
        with mock.patch.object(module, "build_openxml_validator", side_effect=RuntimeError("skip")):
            outline = module.inspect_environment(Path.cwd(), "outline")
            review = module.inspect_environment(Path.cwd(), "review")
        for name in (
            "outline_ready",
            "review_static_ready",
            "review_visual_ready",
            "create_ready",
            "edit_ready",
            "package_validation_ready",
            "visual_qa_ready",
        ):
            self.assertIn(name, outline["capabilities"])
        self.assertEqual(["jsonschema", "PyYAML"], outline["active_requirements"])
        self.assertNotIn("node", review["active_requirements"])
        self.assertEqual("optional-unknown", review["checks"]["External image generation"]["status"])

    def test_bridge_runs_from_space_path_and_targets_project_outputs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="Claude Project ") as project_tmp:
            project = Path(project_tmp)
            other_cwd = project / "nested working dir"
            other_cwd.mkdir()
            spec_path = project / "spec.yaml"
            spec_path.write_text(
                """
meta:
  duration_min: 1
  slide_count: 1
  format: individual
  output_prefix: portable-demo
slides:
  - id: 1
    title: Demo
    layout: title
    content: Point
    timing_sec: 60
    owner: Individual
""",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["CLAUDE_PROJECT_DIR"] = str(project)
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/slide_spec_to_pptx_brief.py"),
                    str(spec_path),
                    "--json",
                ],
                cwd=other_cwd,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            result = json.loads(proc.stdout)
            self.assertEqual(str((project / "outputs").resolve()), result["output_dir"])
            self.assertIn(str(project / "outputs" / "portable-demo-presentation.pptx"), result["brief"])
            self.assertNotIn(str(ROOT / "outputs"), result["brief"])

    def test_node_wrapper_loads_installed_plugin_dependency(self) -> None:
        wrapper = ROOT / "scripts/run_with_pptxgenjs.js"
        if not (ROOT / "node_modules/pptxgenjs").exists():
            self.skipTest("npm dependencies are not installed")
        # 临时项目必须放在祖先链上没有 pptxgenjs 的位置：wrapper 的 project
        # 候选会从项目目录向上走。默认 %TEMP% 在用户 home 之下——若 home 被
        # npm 装过 pptxgenjs（C:\\Users\\<user>\\node_modules），probe 会误判
        # 为 project 命中；插件目录内的 outputs 同样会命中插件自己的
        # node_modules。仓库根的 outputs/（.gitignore 内）祖先链是干净的。
        repo_root = ROOT.parents[1]
        outputs_tmp = repo_root / "outputs" / "_tmp-fixture"
        outputs_tmp.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(dir=outputs_tmp) as tmp:
                env = os.environ.copy()
                env["CLAUDE_PROJECT_DIR"] = tmp
                # NODE_PATH 会兜底 require.resolve 的查找，同样会让空项目
                # 误判命中；清掉它，"空项目 → 插件回退"的契约才可稳定验证。
                env.pop("NODE_PATH", None)
                proc = subprocess.run(
                    ["node", str(wrapper), "--probe"],
                    cwd=tmp,
                    env=env,
                    check=True,
                    capture_output=True,
                    text=True,
                )
        finally:
            shutil.rmtree(outputs_tmp, ignore_errors=True)
        result = json.loads(proc.stdout)
        self.assertEqual("plugin", result["source"])
        self.assertTrue(result["version"])


if __name__ == "__main__":
    unittest.main()
