# Item 14 真实 Live E2E — 实测结果与结论

评审第 14 项要求"真实 Claude Code Live E2E"。本目录的 `smoke_research_fork.py` 是为此建的
真实运行脚手架;两份 `run-*.md` 是 A 模式(联网)/ D 模式(禁网)的 Live E2E 提示词与运行单。
以下是**真实 `claude` CLI 会话**跑出来的证据,不是估算。

## 一、做了什么

- `smoke_research_fork.py`:用 `claude -p --plugin-dir ... --output-format json` 加载插件,
  真实调用 `/student-presentation-suite:sp-research`,再用结果 JSON 里的
  `subagent_stats` / `terminal_reason` / `total_cost_usd` 断言机制,去契约路径
  `outputs/.pptx-work/<work-id>/research-pack.json` 断言产物。
- 支持 `--scenario {smoke,ai-agent-trends,d-mode}`、`--stream`(用 stream-json 抓全部事件,
  确定性判断 fork 是否真发生)、`--validate`(跑 `validate_research_pack.py`)。
- 两份 Live E2E 提示词 + 样例材料 + README,串起了
  `sp-research 具名入参 → scope → validate_research_pack.py → research_pack_to_evidence.py
  → slide_spec_guard freeze` 这条校验链,并附"事后复盘要记的数字"表。

## 二、真实运行证据

| 运行 | 模型 | 成本 | pack | validate | Web 检索 | 关键信号 |
| --- | --- | --- | --- | --- | --- | --- |
| A 模式(smoke) | deepseek-flash(默认) | $1.22 | 4F / 4S / 0 blockers | ok | `webSearchRequests=3` 真实发生;WebFetch 被环境拦截 | `RESEARCH_DONE` 信封正确返回 |
| D 模式 | deepseek-flash | $0.77 | 7F / 1S / 0 blockers | ok | **`queries=[]`、source 全 `user-file`** | 明确记录"D 模式硬约束,未执行任何外部检索" |
| A 模式 | claude-sonnet-4-5 | $0.65 | 1F / 2S / 0 blockers | ok | 同 A | artifact 同样成立 |
| A 模式 + `--stream` | claude-sonnet-4-5 | $1.26 | 1F / 2S / 0 blockers | ok | 同 A | **事件流无 subagent/fork 事件** |

> 实测产物(`outputs/_analysis/live-*.json`、`live-*-result.json`)在本机临时目录,
> 仓库 `outputs/` 被 gitignore,不入库。复跑命令见 `README.md` 与 `run-*.md`。

## 三、关键发现:机制/隔离半边在 `-p` 下没有 fork

四次运行,**两次带 `--stream`(抓全部事件)确认**:

- `subagent_stats.spawned = 0`,且事件流**没有任何 subagent/fork 事件**;
- 主会话的 `permission_denials` 里出现的全是研究员该干的活:`ls references/`、`New-Item .../research`
  目录、`python validate_research_pack.py`、`Glob **/research-fork-*/**` —— 说明 skill 是**内联跑在主会话里**,
  不是隔离的子代理;
- **已排除"模型不支持 fork"**:deepseek-flash 与 claude-sonnet-4-5 **都不 fork**;
- 最可能根因:`context: fork` 在 **print(`-p`)模式不被 honor**,skill 在 `-p` 下被内联执行;
  只有**交互/agent 会话**里 `context: fork` 才会真正 spawn 子代理。本脚手架用 `-p`,因此无法演示真实 fork。

## 四、对 Item 14 的结论

- **产物半边 ✅ 已确证**:真实模型 + 真实联网检索(WebSearch 真实发生)→ schema 合法 Research Pack
  → 校验 0 blockers;**D 模式禁网契约成立**(`queries=[]`、source 全 `user-file`、无任何联网痕迹)。
  这一半不再是"没测过",而是"每次真实跑都过"。
- **隔离/机制半边 ⚠️ 本环境无法证实**:`-p` 模式下 `context: fork` 没触发隔离;真实交互会话里大概率成立,
  但本环境(用 `-p`)**没能证实**。这正是评审卡在"真实运行验证 4/10"的那一半。

## 五、建议的下一步(三选一,等 owner 定)

1. **交互模式实测**:owner 在真实 `claude` 会话里手动 `/student-presentation-suite:sp-research`,
   看 `subagent_stats` / 观察 raw 检索是否进入主会话,确认交互下隔离成立。
2. **加固 fork**:把 `sp-research` 改成显式用 Agent 工具 spawn `presentation-researcher`,
   而不依赖 `context: fork` 在 `-p` 下被忽略——这样无论调用方式都隔离。属较大改动,需 owner 点头。
3. **接受产物半边证据**,把"隔离保证"标注为"依赖交互会话 fork,`-p` 不保证",据此关闭 Item 14。

> 本目录的 `smoke_research_fork.py` 已具备 `--stream` 确定性探测能力:任何模型/模式下重跑,只要
> 事件流出现 subagent/fork 事件,即证明 fork 真发生;否则即证明没发生。可作为后续验证的常驻工具。

## 六、0.12.0 的处理:采纳建议 2,改为显式 spawn

上述第五节的三选一,最终选了 **2(加固 fork)**,理由是它让隔离在**所有调用模式**下成立,
而不只是交互会话:

- `skills/sp-research/SKILL.md` 移除 frontmatter 的 `context: fork` / `agent:` / `background: false`,
  正文改为显式契约:**主流程用 Agent 工具 spawn
  `student-presentation-suite:presentation-researcher`,前台等待,并把 work-id、brief 路径、
  scope、materials 路径写进 spawn 的 prompt 文本**(子代理既看不到主对话,也读不到 frontmatter
  的参数绑定)。
- `smoke_research_fork.py` 的判定收紧:**只接受 `subagent_stats.spawned >= 1`**。
  `context: fork` 的 fork 事件不再算替代证据——它恰恰是本次失败的来源。
- 同步更新 `README.md` / `README-zh.md` / `AGENTS.md` / `references/cost-discipline.md`(CD-5) /
  `skills/sp-outline/SKILL.md`,把"靠 `context: fork` 隔离"的表述换成"靠显式 spawn 隔离",并注明
  不得回退到 `context: fork`。

**仍需实测确认的一点**:显式 spawn 之后要重跑一次
`smoke_research_fork.py --scenario smoke --stream`,断言 `spawned >= 1`。
上面的改动是机制层面的;C 类产物证据(Research Pack 校验链)不受影响。


## 七、0.13.0 实测（2026-09-16）

D-mode `sample-paper.md`，Claude Code 2.1.272，预算上限 $1：

- 实际前台 `presentation-researcher` spawned=1、completed=1、background=0。
- 实际 SubagentStart/PostToolUse/SubagentStop 生成 research-execution.json，绑定 pack SHA256。
- pack：9 findings / 5 sources；本地重新运行 validator：0 blockers。
- 消耗 $0.776257。严格 smoke 总体仍失败：存在 Read/PowerShell/Bash 权限拒绝，不能把它说成无障碍 E2E 通过。
- 原始运行 session：d57095b8-84ca-45d5-8bc5-f9df63e6bd05；child：a7e29b796579e99ce。
- pack SHA256：021955feebe9ef0654a9154c0e81e05a52e50f97af5e10dd156c78aaa6b7e14d。

结论：显式 spawn 和运行时产物绑定已有真实证据；完整 E2E 权限路径当时未修（见第八节）。

第二次限定工具权限的补测中，pack validation 通过，但 CLI 返回纯文本 envelope，stderr 报 `unrecognized_model: deepseek-flash[1m]`，没有 subagent_stats 和 runtime receipt。该次不能作为隔离成功证据；保留第一次真实前台 spawn + receipt 的结果，不把补测记为通过。

## 八、headless 权限路径

根因不是 spawn：`acceptEdits` 在 `-p` 下只自动放行工作目录里的写文件和常见 `mkdir`/`mv`/`cp`。
smoke 的 cwd 是临时项目，研究员 Read 插件根（references / `validate_research_pack.py`）以及
Bash / PowerShell 都会弹权限；无人应答即记入 `permission_denials`，严格 smoke 失败。

处理（不使用 `bypassPermissions`）：

- `smoke_research_fork.py` 给 `claude -p` 加上 `--add-dir <plugin-dir>`，并把研究员工具
  （外加父会话的 `Agent` / `Skill`）写入 `--allowedTools`
- 场景 D 同时 `--disallowedTools WebSearch,WebFetch`
- `permission_denials` 非空仍判机制失败
- 裸跑命令见 `README.md` 与两份 `run-*.md`

本节省的是命令构造与文档；要宣称无障碍 Live E2E 通过，仍须用上述命令重跑一次
`smoke_research_fork.py --scenario d-mode`（及 A 模式）并确认 denials 为空。
