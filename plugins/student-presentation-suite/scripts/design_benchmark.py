#!/usr/bin/env python3
"""Reproducible runtime fixtures and explicit, bounded real-Claude comparisons."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/sp-deck/scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))

import generator_scaffold  # noqa: E402
import live_cost_canary as live  # noqa: E402
import pptx_actual_content_check as content  # noqa: E402
import session_cost  # noqa: E402

FIXTURES = ROOT / "examples/design-benchmarks/cases.json"


def save(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cli_cost_summary(attempts: list[dict]) -> dict:
    """Resume responses contain cumulative session cost, not a new invoice."""
    sessions: dict[str, float] = {}
    complete = bool(attempts)
    for index, attempt in enumerate(attempts):
        value = attempt.get('total_cost_usd')
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            complete = False
            continue
        key = str(attempt.get('session_id') or attempt.get('uuid') or attempt.get('response_path') or index)
        sessions[key] = max(sessions.get(key, 0), float(value))
    estimate = round(sum(sessions.values()), 6)
    return {'reported_cost_usd': estimate if complete else None, 'known_cli_estimates_usd': estimate, 'cli_cost_aggregation': 'maximum cumulative reported USD per session; actual provider billing unknown', 'cli_session_estimates_usd': sessions, 'actual_provider_cost_usd': None}


def collect_attempts(directory: Path) -> list[dict]:
    attempts = {}
    for path in [*directory.glob('intake*.stdout.json'), *directory.glob('production*.json'), *directory.glob('stage-*.stdout.json')]:
        attempt = live.parse_result(path.read_text(encoding='utf-8'))
        if attempt:
            attempts[attempt.get('uuid') or sha(path)] = {'response_path': str(path), **attempt}
    return list(attempts.values())


def collect_evidence(work: Path, config: Path, session: str | None) -> dict:
    """Record observed inputs and usage without estimating unknown model prices."""
    artifacts = {}
    for pattern in ("slide-spec.*", "*.pptx", "presentation-copy.json", "speaker-notes.md", "visual-review.json", "render/*.png", "renders/*.png", "*registry*.json", "*layout*.json"):
        for path in work.glob(pattern):
            if path.is_file():
                artifacts[str(path.relative_to(work))] = sha(path)
    transcripts = list((config / "projects").glob(f"*/{session}.jsonl")) if session else []
    profiles = []
    models = set()
    if len(transcripts) == 1:
        main = transcripts[0]
        paths = [main, *main.with_suffix("").glob("subagents/*.jsonl")]
        for path in paths:
            records = session_cost.read_records(path)
            profile = session_cost.profile(records)
            profiles.append({"transcript": str(path), "is_main": path == main, **profile})
            for row in records:
                message = row.get("message")
                model = message.get("model") if isinstance(message, dict) else None
                if isinstance(model, str):
                    models.add(model)
    geometry = {}
    for path in work.glob("*registry*.json"):
        geometry[path.name] = json.loads(path.read_text(encoding="utf-8"))
    return {"artifact_sha256": artifacts, "observed_models": sorted(models), "usage_profiles": profiles, "registered_geometry": geometry, "cost_policy": "CLI reported USD only; unknown provider prices remain unavailable"}


def prepare(case: dict, directory: Path, mode: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    save(directory / "case.json", case)
    spec = {"schema_version": "2.1", "research_scope": "C", "meta": {"topic": case["topic"], "language": "Chinese", "visual_style": "Academic Rigorous", "quality_level": "standard", "design_freedom": mode, "citation_style": "none", "include_speaker_notes": True, "duration_min": 6, "slide_count": 6}, "slides": []}
    for index, page in enumerate(case["pages"], 1):
        spec["slides"].append({"id": index, "title": page["title"], "claim": page["fact"], "content": [page["fact"]], "layout": "claim-focus", "kind": "cover" if index == 1 else "closing" if index == 6 else "content", "timing_sec": 60, "owner": "speaker", "semantic_requirements": {"must_convey": [{"id": f"fact-{index}", "text": page["fact"], "placement": "slide"}], "must_show_exact": page["exact"]}})
    path = directory / "slide-spec.json"
    save(path, spec)
    if case["image"]:
        # Suite-original source diagram; every box is meaningful and protected.
        from PIL import Image, ImageDraw, ImageFont
        image = Image.new("RGB", (1200, 300), "white")
        draw = ImageDraw.Draw(image)
        font_path = "C:/Windows/Fonts/msyh.ttc" if os.name == "nt" else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        font = ImageFont.truetype(font_path, 34)
        for index, label in enumerate(["Query", "Retrieve", "Rerank", "Answer"]):
            x = index * 290 + 25
            draw.rectangle((x, 70, x + 250, 230), outline="#254B72", width=4)
            draw.text((x + 25, 132), label, fill="#17344D", font=font)
            if index < 3:
                draw.line((x + 251, 150, x + 284, 150), fill="#B87437", width=6)
        image.save(directory / "figure.png")
        save(directory / "image-sources.json", {"version": "0.8", "providers": [{"id": "fixture", "kind": "user-assets", "enabled": True, "assets_dir": ".", "permission": "suite-original"}]})
        save(directory / "asset-manifest.json", {"deck": "benchmark.pptx", "assets": [{"slide": 3, "purpose": "Full synthetic paper process figure", "path": str(directory / "figure.png"), "source": "design_benchmark.py", "permission": "suite-original", "width": 1200, "height": 300, "content_focus": "Query to Answer chain", "focal_point": {"x": 0.5, "y": 0.5}, "preserve_region": {"x": 0, "y": 0, "w": 1, "h": 1}, "crop_suggestion": "contain", "alt_text": "Query, Retrieve, Rerank, Answer", "fallback": "Draw native process shapes"}]})
    return path


def runtime_case(case: dict, directory: Path, mode: str, render: bool) -> dict:
    spec_path = prepare(case, directory, mode)
    generator_scaffold.scaffold_generator(directory, spec_path)
    for index, (page, module) in enumerate(zip(case["pages"], sorted((directory / "pages").glob("*.js")), strict=True), 1):
        text = json.dumps(page["fact"], ensure_ascii=False)
        title = json.dumps(page["title"], ensure_ascii=False)
        if mode == "auto":
            body_box = "{x:.5,y:2.1,w:9,h:1.3}"
            if case["id"] == "typography-stress":
                body_box = "{x:.5,y:2.1,w:2.8,h:3.0}"
                text = json.dumps([{"text": page["fact"][:4], "options": {"bold": True}}, {"text": page["fact"][4:]}], ensure_ascii=False)
            image = ""
            if case["image"] and (case["id"] == "image-heavy" or index in {3, 5}):
                image = f"H.addPlannedImage(slide,{{path:{json.dumps(str(directory / 'figure.png'))},width:1200,height:300,preserve_region:{{x:0,y:0,w:1,h:1}}}},{{x:.5,y:3.6,w:9,h:1.6}},ctx.pptx);"
            source = f"""'use strict';
module.exports=function(ctx){{const {{slide,H,tokens}}=ctx;
H.addFittedText(slide,{title},{{x:.5,y:.6,w:9,h:1.3}},tokens,'chinese','title',{{fontSize:36,margin:0}});
H.addFittedText(slide,{text},{body_box},tokens,'chinese','body',{{fontSize:24,margin:0}});
{image}
}};
module.exports.presentation_copy={{headline:{title},visual_labels:[{json.dumps(page['fact'], ensure_ascii=False)}]}};
module.exports.notes={json.dumps(page['fact'], ensure_ascii=False)};
"""
        else:
            data = {"kind": "content", "layout": "claim-focus", "slots": {"title": page["title"], "claim": page["fact"], "body": []}, "notes": page["fact"], "presentation_copy": {"headline": page["title"], "visual_labels": [page["fact"]]}}
            if mode == "guided":
                data["move"] = "thesis"
                data["typography"] = {"stat_pt": 32, "body_pt": 22, "title_pt": 28}
            source = "module.exports=" + json.dumps(data, ensure_ascii=False) + ";\n"
        module.write_text(source, encoding="utf-8")
    output = directory / "benchmark.pptx"
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(ROOT), "PPTX_HELPERS_DIR": str(ROOT / "scripts")}
    commands = [["node", str(ROOT / "scripts/run_with_pptxgenjs.js"), "--output", str(output), str(directory / "deck.js")]]
    if render:
        commands.append([sys.executable, str(ROOT / "scripts/pptx_tool.py"), "render", str(output), "--output-dir", str(directory / "render"), "--prefix", "page", "--dpi", "110"])
    logs = []
    for command in commands:
        process = subprocess.run(command, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        logs.append({"command": command, "returncode": process.returncode, "stdout": process.stdout, "stderr": process.stderr})
        if process.returncode:
            break
    save(directory / "runtime-log.json", logs)
    result = {"case": case["id"], "mode": mode, "ok": all(item["returncode"] == 0 for item in logs), "semantic_acceptance": "independent critic required; deterministic runtime fixture does not certify meaning"}
    if result["ok"]:
        actual = content.extract_pptx_text(output)
        report = content.check(content.load_structured(spec_path), actual)
        strict_path = directory / "full-content-check.json"
        strict_check = subprocess.run([sys.executable, str(SCRIPTS / "pptx_actual_content_check.py"), str(output), str(spec_path), "--strict", "--output", str(strict_path)], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if strict_check.returncode:
            report["ok"] = False
            report["presentation_copy_failure"] = strict_check.stderr
        result.update({"ok": report["ok"], "content": report, "pptx_sha256": sha(output), "actual_text": actual, "rendered_pages": len(list((directory / "render").glob("*.png")))})
        save(directory / "content-check.json", report)
    save(directory / "summary.json", result)
    return result


def continue_live(directory: Path, work: Path, config: Path, claude: str) -> list[dict]:
    """Continue frozen work at agent boundaries without replaying main history."""
    turns = []
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(directory), "CLAUDE_PLUGIN_ROOT": str(ROOT)}
    interrupted = None
    outputs = sorted(directory.glob("stage-*.stdout.json"), key=lambda path: int(path.name.split('-')[1].split('.')[0]))
    if outputs:
        previous = live.parse_result(outputs[-1].read_text(encoding="utf-8"))
        previous_dispatch = outputs[-1].with_name(outputs[-1].name.replace('.stdout.json', '.dispatch.json'))
        if (previous.get("is_error") or previous.get("stage_incomplete")) and previous_dispatch.is_file():
            if previous.get("terminal_reason") == "operator_interrupted_gate_defect":
                previous_dispatch = previous_dispatch.with_name(previous_dispatch.name.replace('.dispatch.json', '-refreshed.dispatch.json'))
            interrupted = json.loads(previous_dispatch.read_text(encoding="utf-8"))
            import builder_packet

            renewed = []
            for packet in interrupted.get("packets", []):
                path, fresh = builder_packet.write_packet(work, interrupted.get("mode", "initial"), packet.get("slides"), packet.get("shard"), interrupted.get("dispatch", {}).get("pre_qa", {}).get("reports", []))
                renewed.append({"packet": str(path), "slides": fresh["assigned_slides"], "shard": fresh.get("shard"), "speaker_notes_target": fresh["speaker_notes_target"]})
            if renewed:
                builder_packet.record_active_round(work, interrupted.get("mode", "initial"), renewed)
                interrupted["packets"] = renewed
                interrupted["dispatch"]["builder_packets"] = renewed
    for _ in range(8):
        index = len(list(directory.glob("stage-*.stdout.json"))) + 1
        dispatch_file = directory / f"stage-{index}.dispatch.json"
        if interrupted:
            dispatch = interrupted
            interrupted = None
            save(dispatch_file, dispatch)
        else:
            process = subprocess.run([sys.executable, str(SCRIPTS / "ppt_pipeline.py"), "advance", "--work-dir", str(work), "--json"], env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
            dispatch_file.write_text(process.stdout, encoding="utf-8")
            try:
                dispatch = json.loads(process.stdout)
            except json.JSONDecodeError:
                break
        if dispatch.get("status") != "needs_agent":
            manifest = json.loads((work / 'build-manifest.json').read_text(encoding='utf-8'))
            pre_qa = manifest.get('pre_qa') or {}
            build = manifest.get('build') or {}
            if dispatch.get('status') == 'refused' and str(dispatch.get('error', '')).startswith('build failed') and manifest.get('state') == 'producing' and pre_qa.get('ok') is False and not build.get('pending_repair') and int(build.get('repair_count') or 0) < int(build.get('repair_limit', 2)):
                save(directory / f"stage-{index}-build-refused-{len(list(directory.glob('stage-*-build-refused-*.json'))) + 1}.json", dispatch)
                continue  # Construction failure was recorded; the next boundary registers its budgeted repair.
            break
        prompt = f"""继续已确认的同一任务，不重建、不重置预算。当前 work-dir={work}，派发结果={dispatch_file}。
只读取该派发 JSON，按其 agent/mode/packets 字段调用对应的插件 Agent；不得指定 name，必须 run_in_background=false，等待返回后结束本回合。不要运行其他管线阶段，不要读取冻结 Spec 或 Art Direction；Builder 只读 packet，critic 只读 critic-preview-map 及其指定文件。原修复上限仍为1，禁止加轮次、重置工作目录或伪造验收。页数6，事实为合成演示；不得新增未支持的事实。"""
        command = live.build_command(claude, ROOT, prompt, 4.0 if "builder" in str(dispatch.get("agent")) else 2.0, scope="C")
        _, payload = live.run_turn(command, project_dir=directory, config_dir=config, stdout_path=directory / f"stage-{index}.stdout.json", stderr_path=directory / f"stage-{index}.stderr.txt")
        if "BUILDER_BLOCKED" in str(payload.get("result") or ""):
            payload["stage_incomplete"] = True
            save(directory / f"stage-{index}.stdout.json", payload)
        turns.append(payload)
        if payload.get("terminal_reason") == "budget_exhausted" or payload.get("is_error") or payload.get("stage_incomplete"):
            break
    return turns


def live_case(case: dict, directory: Path, mode: str, resume_existing: bool = False, stage_only: bool = False) -> dict:
    if resume_existing and (directory / "summary.json").is_file():
        saved = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
        if saved.get("ok"):
            saved['all_attempts'] = collect_attempts(directory)
            saved.update(cli_cost_summary(saved['all_attempts']))
            save(directory / 'summary.json', saved)
            return saved
        save(directory / f"summary-before-resume-{len(list(directory.glob('summary-before-resume-*.json'))) + 1}.json", saved)
    if not resume_existing:
        prepare(case, directory, mode)
    work_id = f"comparison-{case['id']}-{mode}"
    prompt = f"""/student-presentation-suite:sp-deck
请制作6页中文课程展示，work-id={work_id}，研究范围C，只使用本地case.json与figure.png（若有）。所有成果和论文数字均是合成演示，不得声称是真实发表或真实个人成果。
听众为本科教师与同学，6分钟，16:9，quality_level=standard，design_freedom={mode}，新Slide Spec必须为2.1并逐页保留case.json中的核心信息和精确项。模型可压缩标题与表达。要求PPTX、讲稿、逐页预览。
将本地slide-spec.json复制到work-dir，原样保留semantic_requirements与meta.design_freedom；只可补充缺少的meta。图片来源已在image-sources.json声明（若有）；图片需完整保留流程。art-direction由你根据实际内容制定。plan时传--repair-limit 1 --design-freedom {mode}，不扩充修复预算。每条路径最多一轮修复，失败则记录incomplete；不得伪造critic结论或屏蔽门禁。
本回合只准备完整Production Summary和intake文件，然后停止；不要提前生成或渲染。路径：{directory}。请自行选择可合理默认的细节。
"""
    (directory / "prompt.md").write_text(prompt, encoding="utf-8")
    claude = live.find_claude()
    if not claude:
        raise RuntimeError("Claude CLI unavailable")
    # Use the already authenticated user configuration without copying credentials.
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    receipts = list((directory / "outputs").rglob("seen-*.json")) if resume_existing else []
    recovered = receipts[0].stem.removeprefix("seen-") if len(receipts) == 1 else None
    session_path = directory / "session-id.txt"
    if session_path.is_file():
        recovered = session_path.read_text(encoding="utf-8").strip()
    if recovered and (stage_only or any((directory / "outputs").rglob("production-summary.*"))):
        intake_file = directory / "intake.stdout.json"
        payload1 = live.parse_result(intake_file.read_text(encoding="utf-8")) if intake_file.is_file() else {}
        if not payload1.get("session_id"):
            payload1 = {"session_id": recovered, "infrastructure_recovery": "resume saved intake; Windows batch launcher did not emit structured cost/result", "total_cost_usd": None}
        first = subprocess.CompletedProcess([], 0)
    else:
        command = live.build_command(claude, ROOT, prompt, 1.0, scope="C", resume=recovered)
        intake_output = directory / ('intake-recovered.stdout.json' if recovered else 'intake.stdout.json')
        if intake_output.is_file():
            archive = directory / f"intake-before-resume-{len(list(directory.glob('intake-before-resume-*.stdout.json'))) + 1}.stdout.json"
            archive.write_bytes(intake_output.read_bytes())
        first, payload1 = live.run_turn(command, project_dir=directory, config_dir=config, stdout_path=intake_output, stderr_path=directory / ("intake-recovered.stderr.txt" if recovered else "intake.stderr.txt"))
    session = payload1.get("session_id")
    if session:
        session_path.write_text(str(session), encoding="utf-8")
    payload2 = {}
    stage_turns = []
    if stage_only:
        manifests = list((directory / "outputs").rglob("build-manifest.json"))
        if len(manifests) != 1:
            raise RuntimeError("stage continuation requires one frozen existing manifest")
        stage_turns = continue_live(directory, manifests[0].parent, config, claude)
        production_file = directory / "production.stdout.json"
        if production_file.is_file():
            payload2 = live.parse_result(production_file.read_text(encoding="utf-8"))
    elif first.returncode == 0 and session:
        confirmation = live.CONFIRMATION + f"\n必须meta.design_freedom={mode}。用户已经批准的是{mode}。如果尚未构建且此前plan遗漏该字段，请只纠正meta，然后使用合法plan --force重新冻结，传--design-freedom {mode} --repair-limit 1。不要以默认auto替代用户选择。新任务须保留本地slide-spec.json逐页冻结信息。最多一轮修复；不扩预算，耗尽落盘incomplete。"
        command = live.build_command(claude, ROOT, confirmation, 6.0, scope="C", resume=session)
        command[2] += "\n本次对照所有 Agent 必须前台执行（run_in_background=false）并等到返回；不要在代理仍运行时结束主回合。前次初始 Builder 被 CLI 后台等待时限终止，可 resume 原 Builder 或继续当前 initial round；保留已写页面，不增加正式修复轮数。初始源码和 gate-side 修正无需重启一条路径。完整图文事实都是合成演示；讲稿也不得添加未经本地 case/Spec 支撑的事实。"
        production_file = directory / "production.stdout.json"
        if production_file.is_file():
            saved_output = directory / f"production-before-resume-{len(list(directory.glob('production-before-resume-*.json'))) + 1}.json"
            saved_output.write_text(production_file.read_text(encoding="utf-8"), encoding="utf-8")
        _, payload2 = live.run_turn(command, project_dir=directory, config_dir=config, stdout_path=directory / "production.stdout.json", stderr_path=directory / "production.stderr.txt")
    manifests = list((directory / "outputs").rglob("build-manifest.json"))
    manifest = json.loads(manifests[0].read_text(encoding="utf-8")) if len(manifests) == 1 else {}
    work = manifests[0].parent if len(manifests) == 1 else directory
    review = json.loads((work / "visual-review.json").read_text(encoding="utf-8")) if (work / "visual-review.json").is_file() else {}
    result = {"case": case["id"], "mode": mode, "actual_design_freedom": manifest.get("design_freedom"), "state": manifest.get("state"), "ok": manifest.get("state") == "complete" and manifest.get("design_freedom") == mode and int((manifest.get("build") or {}).get("repair_count", 0)) <= 1, "repair_count": (manifest.get("build") or {}).get("repair_count"), "reported_cost_usd": round(sum(float(value.get("total_cost_usd") or 0) for value in [payload1, payload2]), 4) if all(value.get("total_cost_usd") is not None for value in [payload1,payload2]) else None, "semantic_coverage": [{"slide": entry["slide"], "decisions": entry.get("semantic_coverage", [])} for entry in review.get("slides", [])], "composition": [{"slide": entry["slide"], "visual_structure": entry.get("visual_structure"), "scores": entry.get("scores"), "issues": entry.get("issues")} for entry in review.get("slides", [])], "session_id": session, "work_dir": str(work), "prompt_sha256": sha(directory / "prompt.md"), "turns": [payload1, payload2]}
    result["observed_evidence"] = collect_evidence(work, config, session)
    result["continuation_turns"] = stage_turns
    result["continuation_evidence"] = [collect_evidence(work, config, turn.get("session_id")) for turn in stage_turns]
    result['all_attempts'] = collect_attempts(directory)
    result['all_attempt_evidence'] = [collect_evidence(work, config, sid) for sid in sorted({turn['session_id'] for turn in result['all_attempts'] if turn.get('session_id')})]
    result.update(cli_cost_summary(result['all_attempts']))
    save(directory / "summary.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=["auto", "guided", "deterministic"], default="auto")
    parser.add_argument("--case", default="all")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--live-claude", action="store_true")
    parser.add_argument("--resume-live", action="store_true", help="resume infrastructure-interrupted intakes, preserving saved evidence")
    parser.add_argument("--continue-stages", action="store_true", help="continue an existing live manifest at bounded agent boundaries; retains repair counts")
    parser.add_argument("--typography-stress", action="store_true", help="render six narrow measured rich-text cases (auto runtime only)")
    parser.add_argument("--live-mode", choices=["auto", "guided"], help="continue only one existing live path")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.is_relative_to(ROOT.parent.parent):
        parser.error("benchmark artifacts must be outside the marketplace repository")
    cases = json.loads(FIXTURES.read_text(encoding="utf-8"))["cases"]
    if args.typography_stress:
        if args.live_claude or args.mode != "auto":
            parser.error("typography stress is an auto runtime fixture")
        samples = ["提升9 分贝（条件一致），达到12.5%。", "共计1,233个样本，小数3.14保持完整。", "中文（开头标点）与结尾，避免孤字。", "中英混排English words保持完整，9 分贝作为一个单位。", "强调数值1,233与12.5%，保留rich-text样式。", "首行显式换行\n降低-9 分贝，达到12.5％。"]
        cases = [{"id": "typography-stress", "topic": "中文实测断行", "image": False, "pages": [{"title": f"排版用例 {index}", "fact": value, "exact": [value]} for index, value in enumerate(samples, 1)]}]
    if args.case != "all":
        cases = [case for case in cases if case["id"] == args.case]
        if not cases:
            parser.error("unknown case")
    if args.live_claude:
        cases = [case for case in cases if case["id"] in {"chinese-defense", "illustrated-paper"}]
    summaries = []
    for case in cases:
        for mode in ([args.live_mode] if args.live_claude and args.live_mode else ["guided", "auto"] if args.live_claude else [args.mode]):
            directory = output / ("live" if args.live_claude else "runtime") / case["id"] / mode
            if directory.exists() and not (args.live_claude and args.resume_live):
                parser.error(f"preserve existing results; choose a fresh output root: {directory}")
            print(f"START {case['id']} {mode}", flush=True)
            result = live_case(case, directory, mode, args.resume_live and directory.exists(), args.continue_stages) if args.live_claude else runtime_case(case, directory, mode, args.render)
            summaries.append(result)
            print(f"END {case['id']} {mode}: {'PASS' if result['ok'] else 'FAIL'}", flush=True)
    save(output / ("live-summary.json" if args.live_claude else f"runtime-{args.mode}-summary.json"), summaries)
    return 0 if all(item["ok"] for item in summaries) else 2


if __name__ == "__main__":
    raise SystemExit(main())
