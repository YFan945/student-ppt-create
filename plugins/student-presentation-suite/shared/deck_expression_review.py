"""Advisory expression checks; never an aesthetic score or delivery gate."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

PATTERNS = (
    ("defensive_contrast", re.compile(r"不是[^。！？\n]{1,60}?而是")),
    ("defensive_disclaimer", re.compile(r"(?:仅供参考|仅作为[^。！？\n]{0,40}?参考|不(?:是|能作为|代表)[^。！？\n]{0,30}?(?:真实|依据|证据))")),
    ("generic_inference", re.compile(r"(?:由此可见|需要说明的是|本页旨在)")),
)


def _planned_texts(slide: dict[str, Any]) -> list[str]:
    """User-supplied/planned wording for one slide; hits here are informational."""
    texts: list[str] = []
    requirements = slide.get("semantic_requirements") or {}
    texts.extend(str(item) for item in requirements.get("must_show_exact", []))
    texts.extend(str(item.get("text", "")) for item in requirements.get("must_convey", []) if isinstance(item, dict))
    for key in ("title", "claim", "key_line"):
        if slide.get(key):
            texts.append(str(slide[key]))

    def collect(value: Any) -> None:
        if isinstance(value, str):
            texts.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(slide.get("content"))
    return texts


def review_expression(spec: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    icons: dict[str, list[dict[str, Any]]] = defaultdict(list)
    findings = []
    for index, page in enumerate(actual.get("slides", []), 1):
        number = page.get("slide", index)
        planned = spec.get("slides", [])[index - 1] if index <= len(spec.get("slides", [])) else {}
        frozen = (planned.get("semantic_requirements") or {}).get("must_show_exact", [])
        planned_texts = _planned_texts(planned)
        for field, value in (("body", "\n".join(map(str, page.get("text_runs", [])))),
                             ("notes", str(page.get("speaker_notes") or ""))):
            for code, pattern in PATTERNS:
                for match in pattern.finditer(value):
                    if any(match.group() in str(text) for text in frozen):
                        continue  # User-frozen quotations are not silently rewritten.
                    if any(match.group() in text for text in planned_texts):
                        findings.append({"code": code, "slide": number, "field": field,
                                         "excerpt": match.group(), "severity": "info",
                                         "action": "源自规划或用户提供的文本，确认展示意图即可"})
                    else:
                        findings.append({"code": code, "slide": number, "field": field,
                                         "excerpt": match.group(), "severity": "advisory",
                                         "action": "按共享行文规范改写为具体主张；保留必要事实和用户原文要求"})
        for item in page.get("visual_usage", []):
            if item.get("kind") == "icon" and item.get("key"):
                icons[str(item["key"])].append({"slide": number, "box": item.get("box")})
    for key, uses in icons.items():
        pages = sorted({item["slide"] for item in uses})
        if len(pages) > 1:
            findings.append({"code": "reused_icon", "key": key, "slides": pages, "occurrences": len(uses),
                             "severity": "advisory",
                             "action": "检查是否把同一小图标当作多页主要视觉；优先改用图片、表格、数据图或具体机制图，必要身份/同义指代可保留"})
    return {"scope": "advisory; registered icon usage and actual copy only", "findings": findings,
            "icon_usage": dict(icons),
            "limitation": "未登记或复制绘制的图标不能据此认定不存在；布局多样性、内容充实度和图片适用性仍需看整套渲染；提醒不阻断交付。severity: info 为规划/用户提供文本的命中，advisory 才需按行文规范处理。"}
