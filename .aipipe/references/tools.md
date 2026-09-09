# 使用 aipipe 模板与开发工具

本模板把 aipipe 的 Skill、规则、脚本和配置集中在 `.aipipe/`。产品需求、架构和开发方案保留在项目的 `docs/`；业务代码与测试沿用项目本来的目录结构。GitHub Issue、PR、Review、Milestone 和 Actions 记录交付过程。

## 1. 建立项目并准备输入

在模板仓库页面选择 **Use this template → Create a new repository**，然后将新仓库 clone 到本地。也可以下载模板 ZIP 后建立自己的 GitHub 仓库，注意保留隐藏目录 `.aipipe/`。传统项目首次接入需引入 `.aipipe/` 并使用 init 生成项目配置、复用原有命令与权限，不生成新的开发方案；已有 aipipe 项目直接恢复，仅修复当前缺口。

新项目可以把需求、设计草稿、接口约定等输入放入项目 `docs/`。已有 Vue、Java 或其他项目应保留原来的构建文件、依赖锁文件、Wrapper、代码和测试；不需要为使用 aipipe 重排业务目录。需求也可以来自已有 Issue、现有代码或当前会话，`docs/` 是文档位置，不是启动门槛。

本地目录只是工作区。领取任务、恢复工作和判断完成情况时，以 GitHub 上的 Issue、固定开发分支、PR、验收记录与 CI 结果为准。

## 2. Skill 入口

| 入口 | 职责 |
| --- | --- |
| `.aipipe/skills/aipipe-init/SKILL.md` | 按当前需要补齐项目配置、GitHub Apps、CI 或仓库规则 |
| `.aipipe/skills/aipipe-plan/SKILL.md` | 读取产品输入，编写开发方案，规划 Milestone，批量发布 Issue |
| `.aipipe/skills/aipipe-publish/SKILL.md` | 只发布已有切片计划，无需重写方案 |
| `.aipipe/skills/aipipe-develop/SKILL.md` | 按顺序领取 Issue，沿固定分支开发、自检并提交 PR |
| `.aipipe/skills/aipipe-review/SKILL.md` | 独立验收 PR，记录结论，满足条件后发起合并 |
| `.aipipe/skills/aipipe-resume/SKILL.md` | 从 GitHub 与本地工作区恢复已有 Issue、PR 或开发分支 |
| `.aipipe/SKILL.md` | 可选总入口，按请求选择以上独立 Skill |

每个入口都必须先读取当前项目的 `.aipipe/AGENTS.md`，再读取该阶段需要的配置与资料。`.aipipe/AGENTS.md` 位于工具目录中，不能假设开发工具会自动将其当作项目根规则加载。

最轻的使用方法是让工具明确读取上述路径，不安装全局 Skill，也不向项目根目录增加各工具的入口文件。这是手工加载 Skill 内容；是否支持原生 Skill 发现和快捷调用，由各开发工具决定。

按当前工作选择入口，不要求按表格顺序依次执行：

| 当前场景 | 直接选择 |
| --- | --- |
| 新项目只有需求，需要方案与开发切片 | `aipipe-plan`；需要配置 GitHub 或 CI 时再用 `aipipe-init` |
| 传统项目首次接入 | `aipipe-init`；生成接入配置，保留既有方案与任务 |
| 已有 aipipe 项目，只缺 App、配置、CI 或仓库规则中的一项 | `aipipe-init`，明确只补该项 |
| 已有切片，仅需发布 | `aipipe-publish`，复用原方案 |
| 已有明确 Issue，需要接着开发 | `aipipe-develop`，提供 Issue 编号 |
| 已有 PR，需要独立验收 | `aipipe-review`，提供 PR 编号 |
| 换工具、换机器，或中断后接续分支 | `aipipe-resume`，提供已知 Issue、PR 或分支 |

只在当前操作确实需要而尚不具备相应能力时补配置。阅读代码、讨论方案和编写设计不以 App、CI 或仓库规则全部配置完成为前提；已有 Issue 或 PR 不需要先重新规划、批量发布任务。

## 3. 直接可用的启动提示

先让开发工具在目标项目根目录开始工作。下列提示中的路径都相对于该项目；Issue 编号、PR 编号和输入文件名按实际情况替换。

### 补齐初始化配置

```text
当前工作目录是目标业务仓库。读取 .aipipe/skills/aipipe-init/SKILL.md，
先遵循 .aipipe/AGENTS.md，再检查当前项目。
本次需要补齐的范围是：项目配置、GitHub Apps、CI、仓库规则中缺失且本次需要的部分。
结合已有代码、文档和会话需求，识别技术栈、构建和业务测试入口。
保留已有有效配置，按 Skill 补齐缺口并验证本次配置结果。
需要我提供的账号配置或决策集中列出，不把私钥、令牌写入仓库或日志。
```

### 设计与批量下发

```text
读取 .aipipe/skills/aipipe-plan/SKILL.md，并先遵循 .aipipe/AGENTS.md。
根据当前会话需求、docs/ 文档、现有代码和已有 Issue，为本轮开发补齐可执行的方案。
按模块拆分顺序可领取的 Issue，写明依赖、范围、验收条件与测试要求，
建立 Milestone，并按 Skill 将确定的方案和任务批量发布到 GitHub。
在发布前检查现有 Milestone 和 Issue，避免重复创建。
```

### 只发布已有切片

```text
读取 .aipipe/skills/aipipe-publish/SKILL.md，预览已有 batch.json。
本次仅发布已确定的切片，复用原方案，不重新设计；按本次授权写入 GitHub。
```

### 开发

```text
读取 .aipipe/skills/aipipe-develop/SKILL.md，并先遵循 .aipipe/AGENTS.md。
开发 GitHub Issue #123；未指定 Issue 时，领取下一个满足依赖条件的 Issue。
按 Skill 完成开发、自检与 PR 提交，不要求先重新规划或发布一批 Issue。
一个 Issue 使用一个固定开发分支；已有分支或 PR 时接续原有工作。
自检使用项目配置中的业务测试与构建命令，在 PR 中记录命令、结果和提交 SHA。
依照 Skill 的推进规则继续处理任务；遇到需要决策的阻塞时记录到 GitHub。
```

### 独立验收

```text
读取 .aipipe/skills/aipipe-review/SKILL.md，并先遵循 .aipipe/AGENTS.md。
以独立验收身份检查 GitHub PR #456；未指定 PR 时，选择等待验收的 PR。
读取对应 Issue 与适用的方案基线，缺少当前验收必需信息时按 Skill 处理。
针对当前 PR 提交独立核验实现、测试证据与验收条件，把结论记录到 GitHub。
有问题则提出具体修改要求；验收及 CI 满足条件后，按 Skill 发起合并。
确认合并结果与开发分支清理状态，再处理下一项。
```

开发与验收分别启动会话，并按项目配置使用各自身份。启动提示本身不提供身份隔离，也不会使开发工具自动成为常驻服务；需要连续执行时，遵循对应 Skill 的循环、停止和恢复规则。

### 换工具或恢复中断

```text
读取 .aipipe/skills/aipipe-resume/SKILL.md，并先遵循 .aipipe/AGENTS.md。
恢复 GitHub Issue #123（如已有 PR，请同时读取该 PR）。
从 GitHub 核对任务、固定开发分支、最新提交、验收意见与 CI 状态，
先检查本地未提交改动，再接续原分支和原 PR；不要为换工具另建 Issue 或分支。
按 Skill 判断下一步，并把新进展记录到 GitHub。
```

远端分支只能恢复已经 push 的提交。更换机器或工具前，应按开发 Skill 保存并推送允许保存的工作，记录未完成事项；本地未提交改动需要单独保留并交接。

## 4. 可选：安装原生 Skill 入口

原生入口只是快捷方式，真正的流程仍来自当前业务仓库 `.aipipe/`。建议使用下面的轻量转发入口，避免在每个开发工具中维护一份流程副本。

| 工具 | 用户级入口位置 | 调用方式 |
| --- | --- | --- |
| Codex | `~/.agents/skills/<name>/SKILL.md` | CLI / IDE 使用 `$aipipe-init` 等 Skill 名称，或从 `/skills` 选择；图形界面以实际提供的 Skill 选择入口为准 |
| OpenCode | `~/.config/opencode/skills/<name>/SKILL.md`；也兼容 `~/.agents/skills/` 和 `~/.claude/skills/` | 提示“使用 aipipe-init Skill 初始化当前仓库”；由 agent 通过原生 `skill` 工具加载 |
| Claude Code | `~/.claude/skills/<name>/SKILL.md` | `/aipipe-init`、`/aipipe-plan`、`/aipipe-publish`、`/aipipe-develop`、`/aipipe-review`、`/aipipe-resume` |

这些路径和调用方式来自各工具官方文档：[Codex Skills](https://learn.chatgpt.com/docs/build-skills)、[OpenCode Agent Skills](https://opencode.ai/docs/skills)、[Claude Code Skills](https://code.claude.com/docs/en/skills)。OpenCode 的 Skill 并不等同于自定义 slash command，不假设存在 `/aipipe-init` 命令。

### 一次创建转发入口

以 Codex 的初始化入口为例，在 `~/.agents/skills/aipipe-init/SKILL.md` 写入：

```markdown
---
name: aipipe-init
description: 按需补齐当前业务仓库的 aipipe 项目配置、GitHub Apps、CI 或仓库规则。
---

1. 确认用户正在操作的业务仓库根目录；本全局 Skill 所在目录不是项目目录。
2. 读取该仓库的 .aipipe/AGENTS.md。
3. 读取该仓库的 .aipipe/skills/aipipe-init/SKILL.md，并执行其中的初始化流程。
4. 所有项目相对路径以当前业务仓库为基准。
5. 如果当前仓库缺少上述文件，报告缺失入口，不从其他仓库代用。
```

按需建立以下入口，仅替换 `name`、`description` 和第 3 步的目标路径；第 3 步的执行要求改为对应角色的流程：

| name | description 示例 | 第 3 步目标 |
| --- | --- | --- |
| `aipipe-plan` | 使用当前仓库 aipipe 规划方案、Milestone 和开发 Issue。 | `.aipipe/skills/aipipe-plan/SKILL.md` |
| `aipipe-publish` | 使用当前仓库配置发布已有切片计划。 | `.aipipe/skills/aipipe-publish/SKILL.md` |
| `aipipe-develop` | 使用当前仓库 aipipe 领取 Issue、开发、自检并提交 PR。 | `.aipipe/skills/aipipe-develop/SKILL.md` |
| `aipipe-review` | 使用当前仓库 aipipe 独立验收 PR 并按条件发起合并。 | `.aipipe/skills/aipipe-review/SKILL.md` |
| `aipipe-resume` | 使用当前仓库 aipipe 恢复已有 Issue、PR 或开发分支。 | `.aipipe/skills/aipipe-resume/SKILL.md` |

目录名必须与 `name` 一致。Claude Code 将入口放在其个人 Skill 目录；OpenCode 可以复用已有的 `.agents` 或 `.claude` 全局入口，无须再安装相同名称的一份。已同时安装多种工具时，检查 OpenCode 能发现的位置，避免同名入口重复或相互遮蔽。已有同名 Skill 时先检查其内容，不直接覆盖。

转发入口是本模板的接入约定，由模型按 Markdown 指令读取项目文件，不是开发工具提供的特殊重定向功能。它不携带 App 凭证，也不改变各宿主的命令权限和批准设置。

### 可选软链及适用边界

Codex 和 Claude Code 官方明确支持将 Skill 目录软链到其他位置。例如，把某个原生入口目录软链到 `/绝对路径/项目/.aipipe/skills/aipipe-init`，可以直接使用该项目的 Skill 内容。[Codex 发现规则](https://learn.chatgpt.com/docs/build-skills)、[Claude Code 存放位置](https://code.claude.com/docs/en/skills#where-skills-live)

全局软链始终指向指定 checkout，不会因切换仓库或 worktree 自动换目标。同名 Skill 用于多个项目时，优先采用上述转发入口或显式读取当前仓库路径；并行会话期间不要通过反复改软链切换来源。OpenCode 官方 Skill 文档未明确承诺软链发现行为，本指南不把软链作为它的必需安装方式。

## 5. ZCode 手工加载

在 ZCode 中打开目标项目，直接使用第 3 节提示，要求它读取相应的 `.aipipe/skills/<name>/SKILL.md` 和 `.aipipe/AGENTS.md`。不依赖未经确认的自动发现目录、slash command 或启动参数。

本指南没有探测或调用 ZCode，也未把 Codex、OpenCode 或 Claude Code 的官方能力描述为本模板的端到端实测。实际接入情况以所选 Skill 的检查结果和目标仓库中的验证记录为准。

## 配置执行能力

所有角色都可以由用户选择的 AI 工具与模型承担，包括开发文档、拆片与发布。工作流调用相同的 `aipipe` 配置执行入口，读取项目仓库/命令/credential_ref，并按角色解析外部凭据。配置例子和可直接运行的 GitHub 命令见 [配置执行说明](configuration.md)，完整人类开发者入口见 [使用指南](developer-guide.md)。全局 Skill 转发入口也应按需包含 aipipe-publish。
