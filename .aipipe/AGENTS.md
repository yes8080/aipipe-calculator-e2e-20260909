# aipipe 工作入口

先遵循用户本次目标和仓库现有约定，再选择下列能力。它们独立调用，没有固定先后顺序；不因某一能力尚未配置而阻塞无关工作。

| 当前目标 | 读取 |
|---|---|
| 创建或复用 App、写项目配置、补 CI 或分支规则 | [aipipe-init](skills/aipipe-init/SKILL.md) |
| 从需求、docs、代码或 Issue 设计方案、编排里程碑、发布切片 | [aipipe-plan](skills/aipipe-plan/SKILL.md) |
| 发布已有切片计划，不重新设计 | [aipipe-publish](skills/aipipe-publish/SKILL.md) |
| 开发已有 Issue 或按序领取下一切片 | [aipipe-develop](skills/aipipe-develop/SKILL.md) |
| 独立验收已有 PR、批准或退回、请求合并 | [aipipe-review](skills/aipipe-review/SKILL.md) |
| 接管已有项目、续接分支、换工具恢复 | [aipipe-resume](skills/aipipe-resume/SKILL.md) |

场景细分见 [场景选择](references/scenarios.md)。**传统项目首次接入须使用 init 生成项目配置并登记原有能力，不生成开发方案；已有 aipipe 项目复用配置并恢复任务。** 普通只读分析不隐含安装 aipipe。

用户自行选择规划、拆片、发布、开发、验收所用的 AI 工具与模型；不固定由 GPT-6 或任何特定客户端承担。aipipe 只提供 Skill、配置生成及执行能力。

统一命令入口为 `aipipe`（[安装与初始化](references/cli.md)），读取 project.json 和仓库外凭据映射。使用方式见 [配置执行](references/configuration.md)；接手前的只读状态核对见 [status 只读交接状态](references/status.md)，面向人的文档入口为 [开发者使用指南](references/developer-guide.md)。

命令发现：先 `command -v aipipe`；不可见时检查 `~/.local/bin/aipipe`，完整模板检出可直接用 `python3 .aipipe/scripts/aipipe.py`。不要因宿主没有加载登录 shell PATH 就反复安装。所有示例的 `aipipe` 均可替换为这个已核实的入口。

## 代码作者与处理人

发生提交、发布或验收写入前，读取 [执行身份](references/identity.md)，为本上下文创建 tool / 实际 model / 工作 role 的身份。未知模型写 unknown，不沿用本机人名或把默认偏好当实际模型。普通提交用 `aipipe commit` 记录代码作者；push、PR、Review、publish、release 传明确的 `--identity FILE`。验收使用独立 reviewer 身份并绑定当前 SHA。Owner 维护也记录实际工具与模型，身份声明不授予额外权限。

## 共同约定

- `.aipipe/project.json` 保存仓库、App ID、Installation ID、凭据引用和检查名称等静态配置。先核对它与当前 Git remote 一致；模板复制后的旧仓库绑定必须纠正后才能写 GitHub。
- 定稿后仅使用 GitHub：正式方案与发布输入随仓库保存，初始 Obsidian 原稿冻结。执行所需内容不能依赖私人笔记、聊天或本机路径；具体归属见 [文档与账本](references/documentation.md)。
- 运行账本是 GitHub Issue、Milestone、分支、PR、Review 和 Checks。本地计划是发布输入，不是另一个任务数据库。不要凭本地计划推断远端任务完成。
- 新项目可以把设计输入放进根目录 `docs/`。已有项目可以直接从代码、现有文档、Issue 或用户需求开始。业务开发文档、接口契约和测试属于产品，沿用原目录；缺少约定时才使用 `docs/`。
- 开发 Agent 领取 Issue 就知道编号。实际开发切片使用 `aipipe/issue-N`；创建 PR 直接填写 `Closes #N`。接管已经存在的任务则续接原分支和 PR，不为了改名丢弃工作。不建立额外 Issue/PR 编号校验服务。
- 离线开发/只读评审用 `doctor --for develop|review --offline`，不读取凭据或访问 GitHub；远端写入前切回相应角色检查。初始化完成与任务已发布分开验收。仅有 repository/default_branch 不算可交接；初始化宿主用 `doctor --for handoff` 核实两角色及门禁，发布后用 `release --milestone N --plan FILE --design-ref SHA --apply` 放行。不能因用户准备启动开发工具，就将尚缺 App 或凭据的批次标为 released。
- 默认每仓库一个活动开发切片；同一 Issue 的代码与有效测试一并交付，测试用项目原生入口。业务测试不放进 `.aipipe/tests/`。
- Developer 与验收者使用独立上下文和不同 GitHub App 身份。写入凭据按角色从仓库外注入；测试进程不携带写 token 或 App 私钥。Skill 指令本身不能提供操作系统进程隔离。
- 独立批准及必需 CI 均满足后才合并；新代码使旧批准失效。禁止管理员强制合并或绕过质量规则。启用执行身份后，按验收 Skill 等待条件满足，再用携带身份与指定 SHA 的即时 squash 合并，保留原作者与处理人；回读合并状态并确认开发分支删除。旧配置的原生 auto-merge 路径仍保留。
- 换工具前 commit、push，在原 PR 记录 SHA、完成项、测试结果和下一步，并停止旧执行器。需要用户启动外部工具时，明确时点并提供项目路径、Skill、Issue/PR、角色和实际命令入口的可复制提示词。用户手工启动、重启和更换 ZCode、OpenCode、Claude Code 等工具；不探测、调用或调度这些客户端。
- 已获授权的必要动作继续执行；缺少信息或身份只暂停依赖它的操作。未经用户授权不发布新任务、不创建外部资源、不扩大权限；用户已要求批量发布或初始化时不重复要求泛泛确认。
- 返修默认最多三轮，次数记在原 PR，重启不清零。明确阻塞则记录并停下，不无限重试；没有下一任务则结束会话。

## 文件边界

aipipe 自有规则、Skills、模板、脚本、工具测试和使用指南全在 `.aipipe/`。GitHub 固定路径例外统一为 `.github/workflows/aipipe-*.yml` 或 `.yaml`。保留已有业务工作流名称，不把它们变成 aipipe 文件。

停用见 [移除指南](references/removal.md)。删除工具时保留业务源码、测试、docs、锁文件和 Wrapper；如果移除了 aipipe 提供的业务 CI，先移交测试步骤及 required checks。

## 任务元数据

阶段、PR 标签及 Issue 里程碑约定、Owner 工作流安装及手工修复见 [元数据约定](references/metadata.md)。新版本须同轮同步模板、全局 CLI、测试项目及生成的自动化文件。
