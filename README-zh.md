# Student Presentation Suite for Claude Code

中文 | [English](README.md)

**本文件（marketplace README）：** 从 GitHub 安装、验证、更新、卸载，以及短示例和排错。
不承担 skill 契约、视觉规则或插件 CLI——那些在
[`plugins/student-presentation-suite/README-zh.md`](plugins/student-presentation-suite/README-zh.md)。
改文档时按 [AGENTS.md](AGENTS.md) 的 Documentation Ownership 同步。

> 本仓库是专门适配 **Claude Code** 的插件 marketplace：**直接从本仓库的 `main`
> 分支下载安装**（命令见下面“下载与安装”）。安装、依赖和运行方式均以
> Claude Code 为准，不要在 **OpenAI Codex** 中安装本插件。

`student-presentation-suite` 用于大学课程汇报、论文答辩、小组展示等学生学术
场景。它可以在 Claude Code 中检索证据、生成 PPT 大纲和讲稿、创建可编辑 PPTX、
审查已有 PPT，并根据审查结果生成独立改进版。

仓库内含一个可复现的
[黄金样例](plugins/student-presentation-suite/examples/golden-sample/README.md)，
端到端跑通 v0.8 管线并达到 `status: complete`。

插件安装 ID：

```text
student-presentation-suite@claude-personal
```

插件自主拥有完整 PPTX 运行时（创建/编辑/渲染/校验），运行时归属与审计记录见
[`plugins/student-presentation-suite/references/pptx-runtime-provenance.md`](plugins/student-presentation-suite/references/pptx-runtime-provenance.md)。

## 功能

| 需求 | 使用的 Skill | 结果 |
| --- | --- | --- |
| 检索并分级证据 | `sp-research` | 仅 Research Pack，不创建 PPTX |
| 写 PPT 大纲、讲稿或小组分工 | `sp-outline` | Markdown 规划文档，不创建 PPTX |
| 创建、重做或修改可编辑 PPT/PPTX | `sp-deck` | PPTX、讲稿和预览图 |
| 审查、评分或诊断已有 PPT | `sp-review` | 默认只读的审查报告 |

管线、intake、视觉系统和质量门禁见
[插件 README](plugins/student-presentation-suite/README-zh.md)。
PPTX 使用本套件 `pptx_tool.py` 与 `shared/pptx_runtime/`（不依赖 `document-skills`）。
网页编辑与云同步不在本插件声明范围内。

## 环境要求

安装前请确保已安装：

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
- Git
- Python 3.10+
- Node.js 与 npm
- .NET 8 SDK（Open XML validation 必需）
- LibreOffice 和 Poppler（完成渲染 QA 和 `complete` 交付时必需；缺失时仍可生成候选 PPTX）

可先检查基础命令：

```powershell
claude --version
git --version
python --version
node --version
npm --version
```

## 下载与安装

### 推荐方式：直接添加 GitHub 市场（无需克隆）

Claude Code 的插件市场可以直接指向 GitHub 仓库，不必先克隆到本地。在
PowerShell（或任意终端）中执行两条命令：

```powershell
claude plugin marketplace add YFan945/student-ppt-create@main
claude plugin install student-presentation-suite@claude-personal
```

第二条命令的插件 ID 就是前面的 `student-presentation-suite@claude-personal`。
安装后重启 Claude Code（或执行 `/reload-plugins`）即可生效。

插件还需要 Python 与 Node.js 依赖。用安装脚本一次补齐（脚本会自动把依赖装到
Claude Code 实际加载的那份插件副本里）：

```powershell
Invoke-WebRequest `
  -Uri "https://raw.githubusercontent.com/YFan945/student-ppt-create/main/scripts/install_claude_plugin.ps1" `
  -OutFile "$env:TEMP\install_claude_plugin.ps1"
Set-ExecutionPolicy -Scope Process Bypass
& "$env:TEMP\install_claude_plugin.ps1" -Migrate
```

`-Migrate` 会清理旧的 `student-presentation-suite@personal` 注册和缓存，然后：

1. 检查 .NET 8 并安装 Python 与 Node.js 依赖；
2. 注册 GitHub 市场 `claude-personal`（固定 `main` 分支）；
3. 安装并启用 `student-presentation-suite@claude-personal`；
4. 执行严格环境检查并显示插件状态。

以后更新只需：`claude plugin marketplace update claude-personal`。

安装脚本不会静默下载 .NET SDK。如果本机没有 .NET 8，可自行安装，或显式同意下载
固定版本 8.0.423 到用户目录（约 285 MB）：

```powershell
& "$env:TEMP\install_claude_plugin.ps1" -InstallDotNetSdk
```

### 本地克隆方式（开发或离线）

想固定一份本地副本（例如参与开发、或需要离线安装）时，克隆 `main` 分支并用
`-Local` 注册该目录：

```powershell
git clone --branch main --single-branch `
  https://github.com/YFan945/student-ppt-create.git `
  "$env:USERPROFILE\.agents\claude-plugins"

Set-Location "$env:USERPROFILE\.agents\claude-plugins"
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install_claude_plugin.ps1 -Local -Migrate
```

已经克隆过仓库，拉取更新后重装：

```powershell
Set-Location "$env:USERPROFILE\.agents\claude-plugins"
git switch main
git pull --ff-only origin main
.\scripts\install_claude_plugin.ps1 -Local
```

如果只需重新注册插件、不想重复安装依赖（或直接用现有工作副本，如
`E:\student-ppt-create`）：

```powershell
.\scripts\install_claude_plugin.ps1 -Local -SkipDependencies -SkipMarketplaceClone
.\scripts\install_claude_plugin.ps1 -Local -InstallRoot "E:\student-ppt-create" -SkipMarketplaceClone
```

## 验证安装

```powershell
claude plugin marketplace list
claude plugin list
claude plugin details student-presentation-suite@claude-personal
python .\plugins\student-presentation-suite\scripts\check_claude_pptx_env.py --mode create --json --strict
python .\plugins\student-presentation-suite\scripts\pptx_tool.py --help
```

应能看到：

- marketplace：`claude-personal`
- 插件：`student-presentation-suite@claude-personal`

若刚安装或更新后 Claude Code 没有识别插件，请先完全退出并重新启动 Claude
Code。

## 使用方式

进入你的课程项目目录后启动 Claude Code：

```powershell
Set-Location D:\my-course-project
claude
```

直接用自然语言描述任务即可。插件只处理明确的学生学术展示场景；普通商务
演示、宣传 deck 或非学生任务不会自动进入这些 skill。

创建或修改 PPTX 前，Claude 会整理完整的 `Production Summary`，包括主题、
课程、受众、语言、时长、页数、评分要求、资料来源、视觉风格和交付物。你确认
后才会开始生成。这样可避免在关键信息不完整时直接产出错误文件。

生产由确认后的 Production Summary 门禁（`workflow_guard.py` /
`ppt_pipeline.py`）。成本与 spawn 守卫见
[插件 README](plugins/student-presentation-suite/README-zh.md)。

生成结果默认写入当前项目的 `outputs/` 目录，不会写进插件安装目录。修改已有
PPT 时也不会覆盖原文件。

## 使用案例

### 1. 只生成大纲和讲稿

```text
我是软件工程专业学生，要做一次 6 分钟的中文课程汇报。
主题是“AI 辅助软件测试”，请设计 8 页 PPT 大纲，并给出每页讲稿和时间分配。
不要生成 PPTX。
```

适合先确定内容结构，输出通常包括大纲、逐页讲稿、转场和可选 Q&A。

### 2. 创建可编辑 PPTX

```text
为我的大学课程创建一个可编辑 PPTX。
主题是“生成式 AI 学习反思”，中文，个人汇报，5 分钟，8 页。
受众是老师和同学，风格简洁现代，需要 PPTX、逐页讲稿和预览图。
```

Claude 会补问缺失要求，展示完整 `Production Summary`；确认后再生成和
检查 PPTX。

### 3. 小组课程展示

```text
我们 4 人要做 12 分钟的数据库课程展示，主题是“分布式数据库的一致性”。
请创建 12 页英文 PPTX，安排每位成员负责的页面和讲述时间，附 speaker notes
和可能的老师提问。
```

插件会处理成员分工、交接语句、时间预算和 Q&A 准备。

### 4. 论文答辩 PPT

```text
根据当前项目中的论文、实验结果和图片，为我的本科毕业答辩制作 15 页中文
PPTX，控制在 10 分钟。重点突出研究问题、方法、实验结果、贡献和局限。
引用必须来自我提供的材料，不要编造数据。
```

建议先把论文、数据、图片和学校模板放入当前项目，再启动 Claude Code。

### 5. 只审查现有 PPT

```text
请审查 outputs\defense.pptx，检查内容结构、文字密度、字体大小、图表可读性、
时间分配和答辩风险。只输出问题和具体修改建议，不要改动原文件。
```

该请求默认只读。报告会按严重程度列出目标页面、问题、影响和修改方法。

### 6. 审查并生成改进版

```text
检查 outputs\course-report.pptx，然后直接生成一个改进版。
保留学校模板、logo、已有数据和引用，优化叙事、排版和讲稿，不要覆盖原文件，
并提供修改摘要。
```

插件会先诊断，再要求确认编辑目标，最终生成独立 PPTX 和 change summary。

## 输出文件

根据任务不同，`outputs/` 中可能包含：

```text
<topic>-outline.md
<topic>-presentation.pptx
<topic>-speaker-notes.md
<topic>-preview.png
<topic>-presentation-package-report.json
<topic>-actual-content-report.json
<topic>-visual-review.json
<topic>-quality-report.json
<topic>-delivery-report.json
<topic>-change-summary.md
<topic>-presentation.pdf
<topic>-teleprompter.html
<topic>-training-cards.md
<topic>-revision-manifest.json
```

最终回复会说明文件绝对路径、页数、渲染检查结果，以及任务状态：
`complete`、`incomplete` 或 `blocked`。视觉系统、QA 顺序和 CI 渲染矩阵见
[插件 README](plugins/student-presentation-suite/README-zh.md)。

## 更新与卸载

更新仓库和插件：

```powershell
Set-Location "$env:USERPROFILE\.agents\claude-plugins"
git switch main
git pull --ff-only origin main
claude plugin update -s user student-presentation-suite@claude-personal
```

GitHub 市场安装用：`claude plugin marketplace update claude-personal`。

卸载插件：

```powershell
claude plugin uninstall student-presentation-suite@claude-personal
claude plugin marketplace remove claude-personal
```

## 常见问题

### 插件没有触发

确认请求同时包含“学生/课程/答辩”等学术场景和明确的 PPT 意图。也可以在请求
中直接写明希望使用 `sp-research`、`sp-outline`、`sp-deck` 或 `sp-review`。

### 环境检查失败

运行：

```powershell
python .\plugins\student-presentation-suite\scripts\check_claude_pptx_env.py --json --strict
python .\scripts\check_installed_version.py --json
```

根据输出安装缺失的 Python 或 Node.js 依赖。LibreOffice 和 Poppler 是渲染 QA 与
`complete` 交付所必需的；缺失时仍可生成候选 PPTX。

### 工作流状态卡住

如果 QA 发现 blocker，**不要 reset**：用管线返工边重建生成器再进 QA：

```powershell
python .\plugins\student-presentation-suite\skills\sp-deck\scripts\ppt_pipeline.py repair --work-dir <wd>
```

QA 通过后交付：

```powershell
python .\plugins\student-presentation-suite\skills\sp-deck\scripts\ppt_pipeline.py complete --work-dir <wd>
```

`reset` / `unblock` 只作最后手段——会丢掉已确认摘要并迫使全流程重来。因缺失依赖进入
`blocked` 并已修好依赖时：

```powershell
python .\plugins\student-presentation-suite\scripts\workflow_guard.py unblock
```

`unblock` 会回到 `intake_pending`；恢复生产前必须重新确认 Production Summary。

### 生成文件在哪里

默认在启动 Claude Code 时所在项目的 `outputs/`。如果设置了
`CLAUDE_PROJECT_DIR`，则位于 `${CLAUDE_PROJECT_DIR}/outputs`。

### Codex 能否使用本插件

不能。本仓库只适配 Claude Code。

## 开发与发布

验证命令、升版本和 GitHub Release 步骤见 [AGENTS.md](AGENTS.md)。
贡献者环境见 [CONTRIBUTING.md](CONTRIBUTING.md)。只从本仓库的 **`main`** 分支发布。

## License

MIT，见 [LICENSE](LICENSE)。
