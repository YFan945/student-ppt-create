---
name: sp-research
description: Use only for a student-owned academic presentation needing external facts, current data, statistics, citations or a user-material Research Pack. Does not design slides or generate PPTX.
version: 0.33.0
argument-hint: "[work-id] [brief-or-draft-spec-path] [scope:A|B|C|D] [materials-path-or--]"
arguments: [work_id, brief_path, scope, materials_path]
---

# Student Presentation Research

负责学生学术 PPT 的证据层：读取来源、核验论断并交付 Research Pack。排页和讲稿归 sp-outline，PPTX 归 sp-deck。

1. 写 <work-dir>/research-task.json：背景、输入路径、scope、逐条 claim ID及验收要求。work-dir 为项目 outputs/.pptx-work/<work-id> 的绝对路径。运行 validate_research_task.py。
2. A/B 显式调用 Agent，subagent_type 为 student-presentation-suite:presentation-researcher，按 ../../references/spawn-templates.md 传任务路径。不用 context: fork、不创建命名团队、不嵌套研究员。
3. C 不检索、不制造空包。D 禁止联网，默认 import_user_materials.py 导入用户材料；只有用户点名才派研究员。
4. 普通包使用 source-backed-v1；浏览器、PDF解析、OCR、表格和 fetch-text 都可接入。没有必填文本哈希、抓取回执或逐绑定审查表。来源等级仅标注；详细证据规则只由 ../../references/research-workflow.md 所有。
5. 等待研究员交付后运行 research_handoff.py --work-dir <work-dir>，按 ready/partial/insufficient 使用结果。工具重新校验当前包并刷新报告，不重建回执链。核心缺口不得冒充已完成。
6. 有具体缺口时可顺序 resume 或重新派发已结束的任务，复用已有成果。同一时刻只运行一个研究员；需要时 research_control.py --resume --reason <目标> 清除中断标记。普通任务调整不需要 rebind。
7. 主会话不自行重搜整个任务；遇到疑点可读取少量关键证据复核。默认路径/统计信封，不倾倒原始网页。

unknown_payload 不证明后端未执行；backend_not_executed 只暂停 WebSearch，文档读取仍可用。检索日志由 hooks 维护，--audit 可选，不清零诊断。来源支持、真实口径、错误引用和用户禁网约束仍须遵守。

输出：research-pack.json、工具更新的校验报告和 research/ 资料；located/unresolved 不入事实账本。图片获取另走 ../../references/image-sourcing.md。
