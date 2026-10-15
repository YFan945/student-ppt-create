# Image Sourcing Contract — v0.8

## New-task policy (2.1)

For new tasks, [model-led-design.md](model-led-design.md) owns design modes, frozen semantic
requirements and measured text. Its policy overrides legacy template/scale/
verbatim-copy guidance below. `auto` is the default; user brand/template/logo
and actual readability remain binding. Treat fixed sizes, proportions and
gallery treatments here as optional design suggestions for new tasks.


本文件把"搜图/生图"从隐式假设变成**显式能力**。`image-strategy.md` 说明该不该用图和用什么图；本文件说明**当前会话到底有没有这个能力、怎么声明、怎么留痕、拿不到时怎么办**。

插件不内置、不承诺任何图片服务。能力是否存在由会话声明决定；未声明时一律按"不可用"处理，不得假装有图。

## 配置就绪与实际获取

`search_ready` / `generation_ready` 保留兼容含义：声明、权限和所需命令满足配置条件，不代表网络、凭据或实际成图成功。环境报告用 `readiness_scope` 明确此边界，检查环境不会自动联网或收费。

首次需要图片时，优先让实际所需的一张图成为能力验证，按已有授权执行provider；成功后复用素材，不另做无用探针。fetch-images报告记录契约哈希、可解码图像格式/尺寸与素材哈希；非图片响应拒绝并尝试后备provider。环境命令可用 `--image-fetch-report <fetch-images-report.json>` 读取已有结果，区分not-tested、succeeded、partial、failed及契约/素材过期。成功表示该次获取及当前文件有效，不保证以后每次调用成功，也不证明图片内容适合页面；作者仍须看图。

本轮失败时保留实际原因，执行已有授权的替代图源、原生主题图解或设计占位方案。不能把声明可用写成“图片已生成”，不能反复重试同一失败服务，也不能因为服务失败自动取消所有视觉支撑。

## 1. Declaration file

在项目根目录放置 `image-sources.json`（可用 `SPS_IMAGE_SOURCES` 环境变量覆盖路径）来声明本会话可用的 provider。schema 见 `image-sources.schema.json`，示例见 `image-sources.example.json`。

```json
{
  "version": "0.8",
  "permission": {"allow_web_search": false, "allow_generation": true, "record_source": true},
  "providers": [
    {"id": "user-photos", "kind": "user-assets", "enabled": true, "assets_dir": "assets", "permission": "user-provided"},
    {"id": "concept-imagegen", "kind": "image-generation", "enabled": true, "capability": "skill:imagegen", "permission": "generated"},
    {"id": "web-image-search", "kind": "web-search", "enabled": false, "capability": "websearch", "command": "curl -sL {url} -o {output}", "url_template": "https://example.invalid/search?q={query}", "requires": ["curl"], "permission": "licensed"}
  ]
}
```

发现顺序（首个命中即用）：`SPS_IMAGE_SOURCES` → `<project>/image-sources.json` → 无配置。

无配置时 `check_claude_pptx_env.py` 报告 `External image generation: optional/unknown`，`image_search_ready` 与 `image_generation_ready` 均为 `false`。**这是安全默认值，不是错误。**

## 2. Provider kinds

| kind | 可用条件 | 适用内容 | 禁止内容 |
| --- | --- | --- | --- |
| `user-assets` | `assets_dir` 存在 | 用户提供的照片、截图、研究图 | — |
| `web-search` | `enabled` 且 `allow_web_search` 显式为 `true` 且 `requires` 中命令均存在 | 真人、地点、产品、时事、来源明确的真实素材 | 未确认授权的图片、无法记录来源的图片 |
| `image-generation` | `enabled` 且 `allow_generation` 显式为 `true` 且 `capability` 非空 | 封面/结尾主视觉、抽象概念、氛围性但内容相关的插图 | 图表、流程图、架构图、任何需要准确文字/数字或事实的 evidence visual |

> 权限字段**缺省即拒绝**（fail-closed）。早期文档写成 `!= false`，导致字段缺失时
> 环境检查报 ready、执行侧却跳过，两侧口径不一致；现统一为"必须显式 `true`"。

`capability` 是会话自述的调用方式（如 `skill:imagegen`、`websearch`、`command:<binary>`）；插件不校验其内部实现，只校验声明是否完整、权限是否放行。`url_template` 供 `fetch_images` 把 `{query}` 填进 `{url}`；`assets_dir` 必须解析到项目根目录之内，越界拒绝。执行前 `fetch_images` 与环境检查都按 `image-sources.schema.json` 校验契约。

## 3. Permission gate（硬规则）

1. **联网搜图必须先获得用户许可**。`allow_web_search` 为 `false`、provider 未声明或用户明确拒绝时，不得发起联网搜图。
2. **生图不得作为事实证据**。生成画面只能承担氛围/概念角色；任何数据、引文、人物、事件事实必须有真实来源。
3. **`record_source: true` 时，每张外部图片必须写入来源**；无法记录来源的图片不得进入 composition。
4. 用户说"无图/仅图表/用户素材"时，转为 deterministic visual stack（见 `image-strategy.md`），不因缺图阻断生产。

## 4. Acquisition workflow

```text
env check → 读取 image-sources.json，确认 search/generation/user-assets 哪些 ready
→ 主会话按真实可用素材选择各页表达（Art Direction 的 asset_plan 可选）
→ 对每个外部 asset：选 provider → 校验 permission → 获取
→ 记录 provenance（来源 URL / 生成 prompt / 授权）
→ 写入 asset-manifest.json 并运行 validate-asset-manifest
→ 只把校验通过的 asset 交给 composition
```

保持"先解析能力，再规划构图"的顺序：不要先画好版式再发现拿不到图。

使用可选 Art Direction 时，`art_direction_check.py` 可校验 `asset_plan` 的
`hero_visuals` / `evidence_visuals` 计数 > 0 而本会话**没有任何 image-sources.json** 时直接
拒绝（`asset_plan_visuals_unavailable`，undeclared = unavailable）；已声明但 provider 都不
ready 时只给一条 minor（`asset_plan_visuals_not_ready`）——这几页由 deterministic visual
stack 或已确认允许的设计占位图交付是合法的，只需在构图前确认。新 model-led 任务的图源缺失是素材获取提醒，不以缺少外部 provider 阻断设计占位；旧任务仍保留冻结要求。不能反复保留无法兑现的真实图片计划，不能把未实现页面伪装为设计占位。

外部事实研究按 `sp-research` 由研究员执行。图片选取、工具生图、构图与视觉检查由主会话负责；批量处理获取结果，记录文件路径与来源，不把图片构图派给研究员。获取仍须满足第 3 节权限与来源要求，已有明确授权不重复询问。

## 5. Provenance recording

每张外部或生成 asset 除了 schema 必填字段（`slide`、`purpose`、`source`、`permission`、`alt_text`、`fallback`），还应记录：

| 字段 | 含义 |
| --- | --- |
| `source_url` | 联网图片的原始 URL；生图填 provider 标识或 `generated://<prompt-hash>` |
| `license` | 授权说明，如 `CC-BY-4.0`、`public-domain`、`user-owned`、`model-generated` |
| `provider_id` | 对应 `image-sources.json` 中的 provider `id` |
| `retrieved_at` | 获取时间（ISO 8601） |
| `prompt` | 生成图的 prompt（若为生成） |

`fallback` 必填：写清该 asset 不可用时改用哪种 deterministic visual（diagram/chart/typography 等），避免生产时临时降级成卡片。

## 6. Fallbacks when unavailable

`image_search_ready=false` 或 `image_generation_ready=false` 时，优先选择适合页面的信息表达；已确认允许时保留有设计的占位图：

1. 用户提供的其他素材；
2. 工具制作的概念图、原生图表 / 关系图 / 流程图 / 架构图 / 时间线；
3. 已获允许的主题占位图、可替换照片/截图区域或无虚构数值的表格骨架；
4. custom SVG、native shape、语义 icon 或 typography-led 版式。

### Designed placeholder record

Production Summary 明确是否允许素材占位并保留历史禁止要求。`asset-manifest.json` 顶层 `placeholder_policy` 为 `allow` 或 `forbid`；省略默认为 `forbid`，仅在用户已允许时写 `allow`。每个有意占位 asset 用 `source: "placeholder:<id>"`；原生绘制用 `permission: "suite-original"`，工具生成用 `permission: "generated"` 并附生成 prompt，另附 `placeholder`：

```json
{"kind":"photo-slot","label":"素材待替换","replacement":"实验装置的实拍照片","reason":"尚未提供装置照片"}
```

kind 为 `photo-slot` / `screenshot-slot` / `concept` / `data-skeleton`。该页实际显示 label；素材文件存在则记录 path、真实尺寸，无独立文件的原生占位可省略 path。仍填写 slide、purpose、alt_text、fallback。`validate-asset-manifest` 验证策略、记录及文件；`run` 验证对应页的标记并返回占位/替换清单。修改素材记录后重新 run；占位存在本身不阻断已允许的交付，缺失的真实核心证据仍准确说明。

用户允许在占位区域写生图提示词时，将计划提示词写入asset的`prompt`，并设`placeholder.prompt_visible: true`。验证器要求prompt非空且完整出现在对应页，不能仅在备注或manifest隐藏；这不表示图片已经生成。提示词具体说明主体/场景、构图、风格/配色与限制，不仅写“生成配图”。`examples/main-session-visuals/rich-pages.js`的`promptPlaceholder(ctx, options, box)`可绘制可编辑的标记与提示词并返回asset记录；调用方仍须有允许占位的授权并登记记录。旧记录未设prompt_visible时保持兼容，不追溯要求已有PPT展示提示词。

短标记说明素材性质即可，不反复堆叠“替换内容”“到位后替换”“保持可编辑”等制作说明。具体替换对象、操作和清单放工作记录/交付说明，面向听众的备注继续讲主题。占位场景中的箭头不能暗示材料未支持的步骤、因果或数据关系；并列工具可以并列呈现。

## 7. Verification

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/check_claude_pptx_env.py" --json --strict
# 关注 checks.Image sourcing 与 capabilities.image_search_ready / image_generation_ready

python "${CLAUDE_PLUGIN_ROOT}/scripts/pptx_tool.py" validate-asset-manifest <manifest> --json
```

env check 报告"ready"不等于已获用户许可；许可仍需在 intake 阶段由用户确认。

## Executing the contract: `fetch-images`

`pptx_tool.py fetch-images` turns the contract into real files:

```bash
python scripts/pptx_tool.py fetch-images \
  --sources image-sources.json \
  --query "校园入口" --query "实验设备" \
  --out-dir assets/fetched
```

- `user-assets` providers are searched first: files in `assets_dir` whose
  filename contains a query token are copied (user material always wins).
- `image-generation` / `web-search` providers run their declared `command`
  template with `{query}`, `{url}` and `{output}` placeholders; the command
  must write a non-empty file into the output directory.
- Permission gates are enforced at run time: web-search providers need
  `permission.allow_web_search`, generation needs `allow_generation`, and
  every skipped or failed attempt is recorded in
  `fetch-images-report.json` next to the assets.
- The report's records already carry `provider_id`, `permission`,
  `source_url`, `license` and `retrieved_at`; copy them into
  `asset-manifest.json` entries when assigning images to slides.

## Independent command approval

Project JSON permissions do not authorize local command execution. Before executing a
provider, show its exact command and obtain user/session approval, then supply
`--approve-command-sha256 <sha256-of-command-utf8>` to fetch-images. Never derive
approval from the JSON itself. A command change invalidates the approval; user-assets
copying needs no command approval. Unapproved providers are skipped with their hash.

## 从实际工具接入声明

第一次遇到无配置时，检查当前会话已经暴露的工具/技能和本地素材，不把未声明解释为用户禁止。已有获取授权且工具明确可调用时，由主会话写入准确provider声明，再获取实际需要的一张图；capability填写真实工具/技能名，不照抄示例中的imagegen来虚构能力。已有配置只补充本任务需要的provider，保留其他配置及权限，不自动放宽false。缺授权才集中澄清，缺工具则选择已有授权的替代。

`skill:`/MCP能力由主会话调用；Python fetch-images不能调用宿主工具时，不制造shell包装或假成功。把真实工具返回的文件、来源/提示词、尺寸写入asset-manifest后正常验证；fetch报告仅证明走过fetch的路径，其他真实获取证据仍需对应工具结果。核心素材验证成功后复用，不重复探测或每页重新询问。
