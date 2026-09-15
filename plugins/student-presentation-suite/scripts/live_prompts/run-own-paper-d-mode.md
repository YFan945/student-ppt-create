# Live E2E — 场景 D：仅用用户论文，禁止联网

**对应评审第 14 项的「真实运行验证 · D 模式」一半。**
目标：在真实 `claude` CLI 会话里，让 `sp-research` spawn 出 `presentation-researcher` 子代理，但**严格不联网**，
只用 `--materials` 指向的用户材料产出 Research Pack。这是验证"检索隔离 / 禁网契约"的关键。

## 1. sp-research 具名入参

```
/student-presentation-suite:sp-research <work_id> <brief_path> <scope> <materials_path>
```

| 参数 | 本场景取值 |
| --- | --- |
| `work_id` | `live-d-paper` |
| `brief_path` | 本目录 `own-paper-d-mode.brief.md` 的绝对路径 |
| `scope` | `D` —— 用户限制来源 → **禁止联网** |
| `materials_path` | 用户论文绝对路径（样例用本目录 `sample-paper.md`） |

## 2. 运行命令

经 smoke 脚手架：

```bash
python plugins/student-presentation-suite/scripts/smoke_research_fork.py \
  --plugin-dir plugins/student-presentation-suite \
  --scenario d-mode \
  --materials plugins/student-presentation-suite/scripts/live_prompts/sample-paper.md \
  --model <model> \
  --max-budget-usd 1 \
  --validate \
  --output outputs/_analysis/live-d-result.json
```

裸跑：

```bash
claude -p "/student-presentation-suite:sp-research live-d-paper <brief绝对路径> D <论文绝对路径>" \
  --plugin-dir plugins/student-presentation-suite \
  --output-format json \
  --permission-mode acceptEdits --max-budget-usd 1 --no-session-persistence
```

## 3. 产物后校验链

```bash
PACK=outputs/.pptx-work/live-d-paper/research-pack.json

python plugins/student-presentation-suite/scripts/validate_research_pack.py "$PACK" \
  --output /tmp/live-d-validation.json
python plugins/student-presentation-suite/scripts/research_pack_to_evidence.py "$PACK" \
  --output /tmp/live-d-evidence.json
python plugins/student-presentation-suite/skills/sp-deck/scripts/slide_spec_guard.py freeze \
  --pack "$PACK" --output /tmp/live-d-freeze.json
python plugins/student-presentation-suite/skills/sp-deck/scripts/slide_spec_guard.py check \
  --pack "$PACK" --freeze /tmp/live-d-freeze.json
```

## 4. 这次要记录的数字（用于事后复盘）

| 项 | 记录 |
| --- | --- |
| 模型（`--model` 实际值） | |
| `total_cost_usd` | |
| `subagent_stats.spawned` | （必须 `>=1`） |
| `started_in_background` | （必须 `=0`） |
| `terminal_reason` | |
| pack `findings` / `data_points` / `sources` / `quotes` 计数 | |
| `validate_research_pack` 的 `ok` | |
| **`queries` 数组长度** | （**必须 `=0`** —— D 模式禁网铁证） |
| **所有 source 的 `type`** | （**必须全为 `user-file`**） |
| `research/<topic>.json` 是否含任何 WebFetch/WebSearch 痕迹 | （**必须无**） |
| 总耗时（秒） | |

> 任一 `queries` 非空、或任一 source 非 `user-file`、或原始检索留盘含联网记录，
> 即判定 D 模式契约被破坏，本场景失败。
