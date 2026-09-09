# aipipe 模板

aipipe 提供可独立调用的 Skills、项目配置生成和配置执行能力，使用 GitHub 原生 Issue、PR、Review、CI 组织开发。设计、拆片、发布、开发与验收由用户选择的 AI 工具和模型完成。没有常驻调度服务，不调用或启动 ZCode、OpenCode、Claude Code；用户自行打开所选工具。

当前版本 0.5.3 修正同步合并拒绝的结构化结果，补充脱敏 API 诊断及默认关闭的[自动缺陷上报](references/error-reporting.md)；详见 [身份结果契约](references/identity.md)与[CLI 诊断](references/cli.md)。

## 从当前任务开始

真正的入口是 [.aipipe/AGENTS.md](AGENTS.md)。以下能力独立使用，不需要按顺序执行：

| 需要做什么 | 读取并调用 |
|---|---|
| 创建或复用 GitHub App、登记项目配置，或仅补 CI / 规则 | [aipipe-init](skills/aipipe-init/SKILL.md) |
| 从需求、docs、现有代码或 Issue 设计并批量下发切片 | [aipipe-plan](skills/aipipe-plan/SKILL.md) |
| 只发布已有切片，无需重新设计 | [aipipe-publish](skills/aipipe-publish/SKILL.md) |
| 开发指定 Issue，代码和测试一起提交 | [aipipe-develop](skills/aipipe-develop/SKILL.md) |
| 独立验收一个 PR，按授权批准并请求合并 | [aipipe-review](skills/aipipe-review/SKILL.md) |
| 接管已有项目或续接原分支 / PR | [aipipe-resume](skills/aipipe-resume/SKILL.md) |

最直接的调用方式是在目标项目根目录打开工具，输入：

```text
读取 .aipipe/skills/aipipe-init/SKILL.md。
本次只补 GitHub App 与项目配置。先检查复用已有对象，保留现有 CI 和业务布局。
```

或者：

```text
读取 .aipipe/skills/aipipe-resume/SKILL.md。
接手现有 Issue #27 和 PR #31，先核对代码、测试及交接记录，继续原分支。
```

原生 Skill 安装、Codex / OpenCode / Claude Code 的调用方式，以及 ZCode 手工提示见 [工具接入](references/tools.md)。

## 新项目与已有项目

- **新项目**：在 GitHub 模板页选择 Use this template 创建自己的仓库，或下载 ZIP（保留隐藏目录）。把设计输入放在根目录 `docs/`，按需要调用规划 Skill。App 配置可以单独补齐；不必先完成全部初始化才能写方案。
- **传统项目首次接入**：引入 `.aipipe/` 后使用 init 识别原有能力、生成配置、接入所需 App；不生成新的开发方案或重建历史任务。
- **已有 aipipe 项目**：通过 resume 复用配置和原任务，换机器时只补本机凭据映射；原有 CI 与保护规则先检查再复用。

`docs/` 是产品资料目录，生成的开发方案、架构说明和契约可以放在这里；已有项目沿用其文档位置。App ID、Installation ID、仓库和检查名称写入 [.aipipe/project.json](project.json)。私钥和 token 不进仓库。

## 实际提供的工具

统一入口为 `aipipe`，Python 3.9+，运行时无第三方 Python 依赖。GitHub 操作使用 `gh`，推送使用 `git`，App 签名使用 `openssl`。从可信模板检出安装（包尚未发布到 PyPI）：

```bash
python3 -m venv ~/.local/share/aipipe/venv
~/.local/share/aipipe/venv/bin/python -m pip install /absolute/path/aipipe-template/.aipipe
~/.local/share/aipipe/venv/bin/aipipe --help
```

将该环境的 bin 加入 PATH 或建立个人命令链接后，使用 `aipipe --help`、`aipipe init`。完整安装和各场景命令见 [CLI 指南](references/cli.md)。初始化只写缺少的 aipipe 资源和配置，不生成开发方案。

| 命令 | 行为 |
|---|---|
| `doctor --for handoff/develop/review`、`release` | 只读核实角色接入与远端门禁，检查通过后放行既有批次 |
| `init repo / apps / credentials / checks` | 独立创建或接入仓库、注册复用 App、保存凭据、核对合并设置 |
| `config set / validate`、`inspect` | 合并与验证非秘密配置，查看当前目标项目 |
| `run`、`github`、`api`、`push` | 执行配置中的原生命令，以选定 App 身份操作 GitHub |
| `status` | 只读读取一个 Issue/PR 的交接状态，支持在线角色诊断和离线模式 |
| `auth status / issue-token` | 查看本机凭据可用性；Owner 刷新限仓库的角色 token |
| `publish` | 默认离线预览；`--apply` 通过 Delivery 发布并复用已有批次 |

旧 `scripts/` 四个入口保留为同一实现的薄包装，便于已有模板过渡。示例批次 [batch.example.json](plans/batch.example.json) 解释 Vue + Java 切片格式，不能原样发布到无关项目。

GitHub App 的实际创建字段、安装、凭据与规则操作见 [App 初始化指南](references/github-apps.md)。初始化 Skill 执行这些步骤并登记结果；模板本身没有替使用者注册 App，也没有携带任何账号凭据。

## CI 的边界

模板自带 `.github/workflows/aipipe-ci.yml`，其中 `aipipe-template-checks` 只测试模板工具。它不是业务检查 `ci`。业务项目按技术栈替换为真实业务 CI，或直接复用现有 CI；不要把模板测试作为业务合并门禁。0.5.2 后工具 CI 仅在 PR、默认分支 push 和手工触发时运行，避免普通任务分支 push 重复消耗。

metadata 工作流仍由 Owner 通过普通 PR 安装。默认 inline 模式保持 Review/merge 后即时同步；显式 workflow 模式使用无写权限的 Review 信号 workflow 和默认分支 `workflow_run` 同步；定时巡检覆盖 open 与近期 closed，人工 history dispatch 提供较大有界历史修复窗口。成本、队列和补漏边界见 [元数据约定](references/metadata.md)。

[测试接入指南](references/testing.md)给出 Vue、Java、同仓库前后端的原生入口、空测试要求与大型项目回归范围。工作流文件统一有 `aipipe-` 前缀，业务测试和构建配置独立于工具。

## 人读文档

- [文档与 GitHub 账本](references/documentation.md)：定稿迁移、任务归属和跨工具交接。
- [正式设计](references/design.md)与[Issue/PR 权限规范](references/issue-pr-contract.md)：当前工具设计与执行约束。
- [status 只读交接状态](references/status.md)：Issue/PR 接手、Review/checks/head 核对和 unknown 边界。
- [实现与验证范围](references/implementation-status.md)：已验证能力、历史证据和未覆盖边界。

- [开发者使用指南](references/developer-guide.md)：从接入到日常开发的实际操作。
- [场景选择](references/scenarios.md)：传统项目、已有 aipipe 项目、只设计、只发布、换机器、升级与停用。
- [配置与凭据执行规范](references/configuration.md)：JSON 字段、外部 registry、角色调用命令。
- [维护与开发说明](references/contributing.md)：源码结构、扩展边界、测试和迁移规则。

## 验证与移除

```bash
python3 -m unittest discover -s .aipipe/tests -v
```

上述测试验证工具行为，包含离线预览、重复发布、部分失败恢复、配置隔离和 JWT 签名。两个 App 在指定验证仓库的注册、权限阻拦、PR 审批、合并及删分支已实测；证据与未覆盖场景见 [初始化实测](references/initialization-validation.md)。业务完整交付不能用工具测试替代。

移除范围为 `.aipipe/` 与 `.github/workflows/aipipe-*.yml` / `.yaml`。业务 docs、代码、测试、依赖锁文件与 Wrapper 留在产品中；CI 和仓库设置按 [移除指南](references/removal.md)处理。
