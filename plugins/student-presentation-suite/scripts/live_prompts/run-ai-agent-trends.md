# Live E2E — 场景 A：2026 AI Agent 趋势（联网）

**对应评审第 14 项的「真实运行验证 · A 模式」一半。**
目标：在真实 `claude` CLI 会话里，让 `sp-research` 真正 spawn 出 `presentation-researcher` 子代理，完成**联网**检索并产出 Research Pack。

## 1. sp-research 具名入参

```
/student-presentation-suite:sp-research <work_id> <brief_path> <scope> <materials_path>
```

| 参数 | 本场景取值 |
| --- | --- |
| `work_id` | `live-a-2026`（任意稳定标识） |
| `brief_path` | 本目录 `ai-agent-trends-2026.brief.md` 的绝对路径 |
| `scope` | `A` —— 当前 / 时间敏感 → **必须检索**，不得用记忆替代 |
| `materials_path` | `-`（A 模式无用户材料） |

## 2. 运行命令

经 smoke 脚手架（自动断言机制 + 产物，并跑契约校验）：

```bash
python plugins/student-presentation-suite/scripts/smoke_research_fork.py \
  --plugin-dir plugins/student-presentation-suite \
  --scenario ai-agent-trends \
  --model <model> \            # 默认模型限流时，用 --model 切到未被限流的模型
  --max-budget-usd 3 \
  --validate \
  --output outputs/_analysis/live-a-result.json
```

或直接裸跑（手动看 `RESEARCH_DONE` envelope）：

```bash
claude -p "/student-presentation-suite:sp-research live-a-2026 <brief绝对路径> A -" \
  --plugin-dir plugins/student-presentation-suite \
  --output-format json \
  --permission-mode acceptEdits --max-budget-usd 3 --no-session-persistence
```

## 3. 产物后校验链（fork 之后，人工或脚本串起来）

```bash
PACK=outputs/.pptx-work/live-a-2026/research-pack.json

# (a) 形状 + 契约校验
python plugins/student-presentation-suite/scripts/validate_research_pack.py "$PACK" \
  --output /tmp/live-a-validation.json

# (b) 编译到 Evidence Ledger
python plugins/student-presentation-suite/scripts/research_pack_to_evidence.py "$PACK" \
  --output /tmp/live-a-evidence.json

# (c) 冻结 Slide Spec —— 冻结后若改 pack，check 必须失败
python plugins/student-presentation-suite/skills/sp-deck/scripts/slide_spec_guard.py freeze \
  --pack "$PACK" --output /tmp/live-a-freeze.json
python plugins/student-presentation-suite/skills/sp-deck/scripts/slide_spec_guard.py check \
  --pack "$PACK" --freeze /tmp/live-a-freeze.json
```

## 4. 这次要记录的数字（用于事后复盘）

| 项 | 记录 |
| --- | --- |
| 模型（`--model` 实际值） | |
| `total_cost_usd` | |
| `subagent_stats.spawned` | （必须 `>=1`，证明 fork 真发生） |
| `started_in_background` | （必须 `=0`） |
| `terminal_reason` | （应为 `max_turns` / `end_turn`，非 `budget_exhausted`） |
| pack `findings` / `data_points` / `sources` / `quotes` 计数 | |
| `validate_research_pack` 的 `ok` | （必须 `true`，`blockers=0`） |
| 联网检索是否真实发生 | （看 `research/<topic>.json` 是否有 WebFetch 记录） |
| D 模式违规检查 | （A 模式此项应为空；若出现非 `user-file` source 属异常） |
| 总耗时（秒） | |
