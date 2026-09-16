#!/usr/bin/env python3
"""验证独立的 Claude Code 插件发布包结构。"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ROOT.parents[1]
REQUIRED_FILES = [
    ".claude-plugin/plugin.json",
    "README.md",
    "README-zh.md",
    "requirements.txt",
    "requirements-claude-pptx.txt",
    "requirements-lock.txt",
    "package.json",
    "package-lock.json",
    "references/pptx-runtime-provenance.md",
    "references/presentation-intake.md",
    "references/presentation-brief.md",
    "references/presentation-brief.schema.json",
    "references/content-workflow.md",
    "references/evidence-and-citations.md",
    "references/cost-discipline.md",
    "references/research-workflow.md",
    "references/research-pack.schema.json",
    "references/evidence-map.schema.json",
    "agents/presentation-researcher.md",
    "references/revision-training-export.md",
    "skills/sp-outline/SKILL.md",
    "skills/sp-research/SKILL.md",
    "skills/sp-deck/SKILL.md",
    "skills/sp-deck/references/pptx-production.md",
    "skills/sp-deck/references/pptx-runtime.md",
    "skills/sp-deck/references/pptxgenjs-safety.md",
    "skills/sp-deck/references/pptxgenjs-helper-api.md",
    "skills/sp-deck/references/pptx-editing.md",
    "skills/sp-deck/references/pptx-qa.md",
    "skills/sp-deck/references/layout-library.json",
    "skills/sp-review/SKILL.md",
    "skills/sp-review/scripts/pptx_static_check.py",
    "scripts/check_claude_pptx_env.py",
    "scripts/pptx_tool.py",
    "scripts/run_with_pptxgenjs.js",
    "scripts/smoke_pptx.py",
    "scripts/slide_spec_to_pptx_brief.py",
    "scripts/validate_slide_spec.py",
    "scripts/validate_presentation_brief.py",
    "scripts/analyze_presentation_spec.py",
    "scripts/pptx-helpers.js",
    "scripts/pptx-layouts.js",
    "scripts/pptx-visuals.js",
    "scripts/visual_system_smoke_gallery.py",
    "scripts/create_revision_manifest.py",
    "scripts/build_support_outputs.py",
    "scripts/workflow_guard.py",
    "hooks/hooks.json",
    "scripts/cost_guard.py",
    "scripts/assert_research_envelope.py",
    "skills/sp-deck/scripts/ppt_pipeline.py",
    "skills/sp-deck/scripts/generator_scaffold.py",
    "scripts/manage_versions.py",
    "shared/__init__.py",
    "shared/_import_helpers.py",
    "shared/design_tokens.py",
    "shared/handoff_validation.py",
    "shared/presentation_quality.py",
    "shared/pptx_static_core.py",
    "shared/runtime_paths.py",
    "shared/slide_spec_contract.py",
    "shared/slide_spec_validation.py",
    "shared/pptx_runtime/__init__.py",
    "shared/pptx_runtime/charts.py",
    "shared/pptx_runtime/findings.py",
    "shared/pptx_runtime/package.py",
    "shared/pptx_runtime/edit.py",
    "shared/pptx_runtime/normalize.py",
    "shared/pptx_runtime/openxml.py",
    "shared/pptx_runtime/openxml_validator/OpenXmlValidator.csproj",
    "shared/pptx_runtime/openxml_validator/packages.lock.json",
    "shared/pptx_runtime/openxml_validator/Program.cs",
    "shared/pptx_runtime/pptx_slide.py",
    "shared/pptx_runtime/validate.py",
    "shared/pptx_runtime/render.py",
    "shared/pptx_runtime/soffice.py",
    "shared/pptx_runtime/thumbnail.py",
    "shared/pptx_runtime/assets/lo_socket_shim.c",
    "tests/test_pptx_tool.py",
    "tests/test_pptx_runtime.py",
    "tests/test_runtime_paths.py",
]
FORBIDDEN_PATH_PARTS = {
    ".codex-plugin",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "bin",
    "obj",
}
FORBIDDEN_SUFFIXES = {".pyc", ".pptx", ".png"}
REQUIRED_METADATA = ("homepage", "repository", "license", "keywords")
_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*))?"
    r"(?:\+([a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*))?$"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检查 Claude Code 插件结构")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    parser.add_argument(
        "--allow-untracked",
        action="store_true",
        help="仅用于提交前验证；允许磁盘上存在但尚未纳入 Git 的新增必需文件",
    )
    return parser.parse_args()


def run_git(*args: str) -> list[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "git 命令失败").strip())
    return proc.stdout.splitlines()


def tracked_files(errors: list[str]) -> list[str]:
    try:
        return run_git("ls-files")
    except RuntimeError as exc:
        errors.append(f"无法检查已跟踪文件: {exc}")
        return []


def check_structure(errors: list[str]) -> None:
    for rel in REQUIRED_FILES:
        if not (ROOT / rel).is_file():
            errors.append(f"缺少必需文件: {rel}")


def check_manifest(errors: list[str]) -> None:
    try:
        manifest = json.loads((ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"manifest 解析失败: {exc}")
        return
    if manifest.get("name") != "student-presentation-suite":
        errors.append("manifest name 必须为 student-presentation-suite")
    # 版本号非空且符合 semver；版本一致性由 check_marketplace_release.py 权威校验
    version = manifest.get("version", "")
    if not version:
        errors.append("manifest 的版本号为空，必须提供有效版本")
    elif not _SEMVER_RE.fullmatch(version):
        errors.append(f"manifest 的版本号不是合法 semver: {version}")
    author = manifest.get("author") if isinstance(manifest.get("author"), dict) else {}
    if author.get("name") in {None, "", "Local developer"}:
        errors.append("manifest author.name 必须提供发布者名称")
    for field in REQUIRED_METADATA:
        if not manifest.get(field):
            errors.append(f"manifest 缺少必要元数据: {field}")
    # 发布源已统一到本仓库的 main 分支（原 Personal-Student 的 claude-code
    # 分支不再是发布线），manifest 必须指向这里，防止悄悄回退到旧仓库。
    if "student-ppt-create/tree/main" not in str(manifest.get("homepage")):
        errors.append("manifest homepage 必须指向 student-ppt-create 的 main 分支")
    if "student-ppt-create/tree/main" not in str(manifest.get("repository")):
        errors.append("manifest repository 必须指向 student-ppt-create 的 main 分支")
    for skill_file in sorted((ROOT / "skills").glob("*/SKILL.md")):
        match = re.search(
            r"(?m)^version:\s*(\S+)\s*$",
            skill_file.read_text(encoding="utf-8"),
        )
        if not match:
            errors.append(f"{skill_file.relative_to(ROOT)} 缺少 frontmatter version")
        elif match.group(1) != version:
            errors.append(
                f"{skill_file.relative_to(ROOT)} version {match.group(1)!r} "
                f"与 manifest {version!r} 不一致"
            )


def check_script_reference_graph(errors: list[str]) -> dict[str, list[str]]:
    retention_reasons = {
        "check_plugin_release.py": "repository CI invokes this package release gate",
    }
    searchable = []
    for root_name in ("skills", "commands", "tests", "references", "scripts"):
        root = ROOT / root_name
        if not root.exists():
            continue
        searchable.extend(
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in {".md", ".py", ".js", ".json"}
        )
    searchable.extend(path for path in (ROOT / "README.md", ROOT / "README-zh.md") if path.is_file())
    graph: dict[str, list[str]] = {}
    for script in sorted((ROOT / "scripts").glob("*")):
        if not script.is_file() or script.suffix.lower() not in {".py", ".js"}:
            continue
        references = []
        for candidate in searchable:
            if candidate == script:
                continue
            try:
                text = candidate.read_text(encoding="utf-8", errors="ignore")
                if script.name in text or script.stem in text:
                    references.append(str(candidate.relative_to(ROOT)).replace("\\", "/"))
            except OSError:
                continue
        graph[script.name] = references
        if not references and script.name in retention_reasons:
            references.append(f"retained: {retention_reasons[script.name]}")
        if not references:
            errors.append(f"发布脚本没有入口引用或保留理由: scripts/{script.name}")
    return graph


def check_runtime_contract(errors: list[str]) -> None:
    try:
        combined = "\n".join(
            (ROOT / rel).read_text(encoding="utf-8")
            for rel in (
                "skills/sp-deck/SKILL.md",
                "skills/sp-review/SKILL.md",
                "skills/sp-deck/references/pptx-production.md",
            )
        )
    except OSError as exc:
        errors.append(f"运行时契约文件读取失败: {exc}")
        return
    for expected in (
        "${CLAUDE_PLUGIN_ROOT}",
        "${CLAUDE_PROJECT_DIR}",
        "run_with_pptxgenjs.js",
    ):
        if expected not in combined:
            errors.append(f"运行时契约缺失必要的引用: {expected}")
    for forbidden in ("artifact-tool", "Presentations` skill", "agents/openai.yaml"):
        if forbidden in combined:
            errors.append(f"运行时指令包含 Codex-only 文本: {forbidden}")
    if "tokens truncated" in combined:
        errors.append("PPTX 运行时文档包含截断标记")
    qa_contract = (ROOT / "skills/sp-deck/references/pptx-qa.md").read_text(
        encoding="utf-8"
    )
    if "代码允许 `complete`" in qa_contract:
        errors.append("PPTX QA 文档仍包含无预览可 complete 的冲突说明")
    for rel in (
        "skills/sp-deck/SKILL.md",
        "skills/sp-deck/references/pptx-production.md",
        "skills/sp-deck/references/pptx-runtime.md",
        "skills/sp-deck/references/pptxgenjs-safety.md",
        "skills/sp-deck/references/pptx-editing.md",
        "skills/sp-deck/references/pptx-qa.md",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        if text.count("```") % 2:
            errors.append(f"Markdown code fence 未闭合: {rel}")


def check_embedded_runtime(errors: list[str]) -> None:
    probe = subprocess.run(
        [sys.executable, "-B", str(ROOT / "scripts" / "pptx_tool.py"), "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if probe.returncode != 0:
        errors.append(f"suite-owned PPTX runtime 无法启动: {(probe.stderr or probe.stdout).strip()}")
    legacy_runtime = ROOT / "skills/sp-deck/scripts/pptx_skill"
    if legacy_runtime.is_dir() and any(
        path.is_file() and "__pycache__" not in path.parts
        for path in legacy_runtime.rglob("*")
    ):
        errors.append("已移除的上游 pptx_skill runtime 不应出现在发布包中")


def check_tracked_files(errors: list[str], *, allow_untracked: bool = False) -> None:
    files = tracked_files(errors)
    tracked = set(files)
    for rel in REQUIRED_FILES:
        repository_path = f"plugins/student-presentation-suite/{rel}"
        if repository_path not in tracked and not (
            allow_untracked and (ROOT / rel).is_file()
        ):
            errors.append(f"必需发布文件尚未被 Git 跟踪: {rel}")
    folded: dict[str, str] = {}
    for rel in files:
        if not rel.startswith("plugins/student-presentation-suite/"):
            continue
        local = rel.removeprefix("plugins/student-presentation-suite/")
        local_path = Path(local)
        if any(part in FORBIDDEN_PATH_PARTS for part in local_path.parts):
            errors.append(f"禁止的生成文件或 Codex 路径被跟踪: {local}")
        if local_path.suffix.lower() in FORBIDDEN_SUFFIXES:
            errors.append(f"生成的产物被跟踪: {local}")
        key = local.casefold()
        if key in folded and folded[key] != local:
            errors.append(f"大小写冲突的跟踪路径: {folded[key]} 与 {local}")
        folded[key] = local
        disk_path = ROOT / local
        if disk_path.is_file() and disk_path.read_bytes().startswith(b"\xef\xbb\xbf"):
            errors.append(f"不允许 UTF-8 BOM: {local}")


def main() -> None:
    args = parse_args()
    errors: list[str] = []
    check_structure(errors)
    check_manifest(errors)
    check_current_documentation(errors)
    reference_graph = check_script_reference_graph(errors)
    check_runtime_contract(errors)
    check_embedded_runtime(errors)
    check_tracked_files(errors, allow_untracked=args.allow_untracked)
    result = {
        "ok": not errors,
        "error_count": len(errors),
        "errors": errors,
        "script_reference_graph": reference_graph,
        "allow_untracked": args.allow_untracked,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif errors:
        print("插件发布检查失败:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
    else:
        print("插件发布检查通过。")
    if errors:
        raise SystemExit(1)


def check_current_documentation(errors: list[str]) -> None:
    """Current guidance may cite published suite versions, never draft releases.

    Historical changelog sections are intentionally excluded from branch checks.
    Dependency/CLI versions are not suite release numbers.
    """
    changelog = (REPOSITORY_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    published = set(re.findall(r"^## (\d+\.\d+\.\d+)\b", changelog, re.M))
    published.add(json.loads((ROOT / ".claude-plugin/plugin.json").read_text())["version"])
    paths = [REPOSITORY_ROOT / "README.md", REPOSITORY_ROOT / "README-zh.md", ROOT / "README.md", ROOT / "README-zh.md", ROOT / "scripts/live_prompts/README.md", *sorted((ROOT / "skills").glob("*/SKILL.md"))]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"Ruff\s+\d+\.\d+\.\d+", "Ruff", text)
        text = text.replace("v0.7.1", "quality-core")  # quality contract, not a plugin release
        if re.search(r"(?:github\.com/YFan945/Personal-Student/(?:tree|blob)/claude-code|本文件记录\s*`claude-code`)", text):
            errors.append(f"Retired publication source in {path.name}")
        for version in set(re.findall(r"(?<![\d.])0\.\d+\.\d+(?![\d.])", text)) - published:
            errors.append(f"Unpublished suite version {version} in {path.name}")
    introduction = changelog.split("\n## ", 1)[0]
    if "claude-code" in introduction or "Codex 发行" in introduction:
        errors.append("Changelog introduction must describe this repository's main release line")


if __name__ == "__main__":
    main()
