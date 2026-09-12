# Image Sourcing Contract — v0.8

本文件把"搜图/生图"从隐式假设变成**显式能力**。`image-strategy.md` 说明该不该用图和用什么图；本文件说明**当前会话到底有没有这个能力、怎么声明、怎么留痕、拿不到时怎么办**。

插件不内置、不承诺任何图片服务。能力是否存在由会话声明决定；未声明时一律按"不可用"处理，不得假装有图。

## 1. Declaration file

在项目根目录放置 `image-sources.json`（可用 `SPS_IMAGE_SOURCES` 环境变量覆盖路径）来声明本会话可用的 provider。schema 见 `image-sources.schema.json`，示例见 `image-sources.example.json`。

```json
{
  "version": "0.8",
  "permission": {"allow_web_search": false, "allow_generation": true, "record_source": true},
  "providers": [
    {"id": "user-photos", "kind": "user-assets", "enabled": true, "assets_dir": "assets", "permission": "user-provided"},
    {"id": "concept-imagegen", "kind": "image-generation", "enabled": true, "capability": "skill:imagegen", "permission": "generated"},
    {"id": "web-image-search", "kind": "web-search", "enabled": false, "capability": "websearch", "requires": ["curl"], "permission": "licensed"}
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

`capability` 是会话自述的调用方式（如 `skill:imagegen`、`websearch`、`command:<binary>`）；插件不校验其内部实现，只校验声明是否完整、权限是否放行。

## 3. Permission gate（硬规则）

1. **联网搜图必须先获得用户许可**。`allow_web_search` 为 `false`、provider 未声明或用户明确拒绝时，不得发起联网搜图。
2. **生图不得作为事实证据**。生成画面只能承担氛围/概念角色；任何数据、引文、人物、事件事实必须有真实来源。
3. **`record_source: true` 时，每张外部图片必须写入来源**；无法记录来源的图片不得进入 composition。
4. 用户说"无图/仅图表/用户素材"时，转为 deterministic visual stack（见 `image-strategy.md`），不因缺图阻断生产。

## 4. Acquisition workflow

```text
env check → 读取 image-sources.json，确认 search/generation/user-assets 哪些 ready
→ Art Direction 的 asset_plan 标注每页期望的 asset 类型
→ 对每个外部 asset：选 provider → 校验 permission → 获取
→ 记录 provenance（来源 URL / 生成 prompt / 授权）
→ 写入 asset-manifest.json 并运行 validate-asset-manifest
→ 只把校验通过的 asset 交给 composition
```

保持"先解析能力，再规划构图"的顺序：不要先画好版式再发现拿不到图。

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

`image_search_ready=false` 或 `image_generation_ready=false` 时，按此顺序降级，不得留占位符：

1. 用户提供的其他素材；
2. 原生图表 / 关系图 / 流程图 / 架构图 / 时间线；
3. custom SVG 或 native shape；
4. `pptx-icons.js` 小型语义 icon（仅作辅助）；
5. typography-led 版式。

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
