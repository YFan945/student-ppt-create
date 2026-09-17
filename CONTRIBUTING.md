# 贡献指南

感谢您对 Student Presentation Suite 的兴趣！

## 开发设置

```bash
# 克隆仓库（发布源是本仓库的 main 分支）
git clone https://github.com/YFan945/student-ppt-create.git
cd student-ppt-create

# Python 依赖
pip install -r plugins/student-presentation-suite/requirements.txt
pip install -r plugins/student-presentation-suite/requirements-claude-pptx.txt

# Node.js 依赖
npm --prefix plugins/student-presentation-suite ci
```

## 运行测试

```bash
cd plugins/student-presentation-suite
PYTHONPATH=. python -m unittest discover -s tests
```

## 代码质量

- Python 代码使用 Ruff（`ruff check .`）
- JavaScript 代码使用 ESLint + Prettier（`npx eslint scripts/*.js`）
- 提交前运行测试确保无回归

## PPTX 运行时验收

插件自主实现 PPTX 创建/编辑/渲染/校验（`scripts/pptx_tool.py` + `shared/pptx_runtime/`），
不依赖外部 `document-skills` 或上游缓存路径；用户产物只能写入 `outputs/`。
所有权与审计记录见
`plugins/student-presentation-suite/references/pptx-runtime-provenance.md`。

开发验收命令见根目录 `AGENTS.md`（完整验证套件）与插件
`plugins/student-presentation-suite/AGENTS.md`（插件内快捷命令）。
改说明文档时按 `AGENTS.md` 的 Documentation Ownership 同步，不要把同一段
复制进四份 README。

## 工作流

1. 从 `main` 创建功能分支
2. 实施修改并添加测试
3. 运行全部测试确保通过
4. 提交 PR 到 `main` 分支

## 版本发布

版本号遵循 semver，使用 `bump_version.py` 统一更新。
