"""Page-specific author review prompts; no aesthetic score or shape quota."""
from __future__ import annotations

import re
from typing import Any


def planning_review(spec: dict[str, Any]) -> dict[str, Any]:
    pages, findings = [], []
    for index, slide in enumerate(spec.get("slides", []), 1):
        visual = slide.get("visual") or {}
        requirements = slide.get("semantic_requirements") or {}
        core = [item.get("text", "") for item in requirements.get("must_convey", [])]
        if spec.get("template_sources") and not slide.get("template_refs"):
            findings.append({"slide": index, "code": "template_adaptation_unmapped", "severity": "advisory",
                             "action": "本任务已选择模板，但本页未关联参考页；对照封面/正文原型完成适配，或在现有规划说明本页为何采用其他结构。登记引用本身不证明视觉落实。"})
        pages.append({"slide": index, "planned_title": slide.get("title"), "core_information": core,
                      "support": slide.get("content", []), "main_visual": visual,
                      "template_refs": slide.get("template_refs", []),
                      "questions": ["本页回答什么问题，标题给出什么有依据的发现？",
                                    "主要图像/图解/表格怎样解释这个回答，哪些细节必须可见？",
                                    "学生先指哪里、再解释哪里，其他内容怎样支撑重点？"]})
    return {"scope": "author decisions, not automatic aesthetic acceptance", "pages": pages, "findings": findings}


def reference_comparisons(spec: dict[str, Any], rendered: list[dict]) -> list[dict]:
    """Pair actual final pages with their chosen references; never certify looks."""
    from shared.bundled_templates import metadata

    sources = {source["id"]: source for source in spec.get("template_sources", [])}
    pairs = []
    for index, page in enumerate(spec.get("slides", [])):
        if index >= len(rendered):
            continue
        for ref in page.get("template_refs", []):
            source = sources.get(ref["source_id"], {})
            path = source.get("path", "")
            preview = None
            if path.startswith("builtin:"):
                entry = metadata(path)
                preview = next((p.get("preview") or entry.get("preview") for p in entry["slides"]
                                if p["slide"] == ref["slide"]), None)
            pairs.append({"slide": index + 1, "reference_source": path, "reference_page": ref["slide"],
                          "reference_preview": preview, "actual_render": rendered[index].get("path"),
                          "borrowed_structure": ref.get("reason"), "verified": False,
                          "inspect": "对照实际参考图和最终页，检查主体、支撑组、层级、色彩与正文布局；先修重叠。引用登记与技术通过不证明适配完成。"})
    return pairs


def review_actual(spec: dict[str, Any], actual: dict[str, Any], geometry: dict[str, Any]) -> dict[str, Any]:
    review = planning_review(spec)
    for page in actual.get("slides", []):
        number = page.get("slide")
        if not isinstance(number, int) or not 1 <= number <= len(review["pages"]):
            continue
        target = review["pages"][number - 1]
        target["actual_title"] = page.get("headline")
        texts = [str(text).strip() for text in page.get("text_runs", []) if str(text).strip()]
        target["visible_content"] = texts
        target["speaker_notes"] = page.get("speaker_notes", "")
        title = re.sub(r"\s+", "", str(page.get("headline") or ""))
        planned = spec["slides"][number - 1]
        claim = re.sub(r"\s+", "", str(planned.get("claim") or ""))
        if title and claim == title and sum(re.sub(r"\s+", "", text) == title for text in texts) > 1:
            review["findings"].append({"slide": number, "code": "title_claim_repetition_review", "severity": "advisory",
                                       "action": "检查是否把标题重复画成副标题或结论带；同一句只展示一次即可"})
        if title in {"背景介绍", "研究背景", "实验结果", "总结", "方案介绍"}:
            review["findings"].append({"slide": number, "code": "topic_title_review", "severity": "advisory",
                                       "action": "材料支持时将分类标题改为具体发现；保留用户指定标题"})
    review["readability_findings"] = [item for item in geometry.get("warnings", [])
                                       if item.get("code") in {"text_size_review", "text_size_tiers", "font_family_mix"}]
    review["deck_questions"] = ["整套是否有丰富且协调的配色，颜色含义、字体和同级标题是否一致？",
                                 "逐页是否新增解释或证据，主体是否随关系变化，是否用空容器或放大短句代替内容？",
                                 "模板参考的图文层次与素材承载能力是否保留，多套组合是否协调？"]
    return review
