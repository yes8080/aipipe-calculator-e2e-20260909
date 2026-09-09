# aipipe 连续流水线设计方案

aipipe 提供 **独立 Skills、项目配置和 Python CLI**。用户选择工具与模型完成设计、拆片、发布、开发和独立验收；GitHub 保存交付账本并执行仓库门禁。用户手工启动、重启和更换开发工具。

当前不包含常驻调度器、模型 API、客户端启动器、任务状态数据库或原子领取服务。“连续流水线”是已启动的独立会话按 GitHub 状态推进任务的工作约定；CLI 不负责让会话持续运行。实际完成与未实现范围见 [aipipe 实现核对与待办清单_20260908](implementation-status.md)。

## 1. 按需要选择能力

| 当前目标 | Skill | 结果 |
|---|---|---|
| 初始化、复用 App、修复凭据或门禁 | aipipe-init | 本次所需配置与核验结果 |
| 设计开发文档或编排切片 | aipipe-plan | 方案、里程碑规划、批次 JSON |
| 发布已确定的切片 | aipipe-publish | GitHub Milestone / Issue |
| 开发指定 Issue 或下一可执行切片 | aipipe-develop | 原任务分支、代码、测试、PR |
| 独立验收现有 PR | aipipe-review | Review、合并请求及收尾记录 |
| 接管现有任务或换工具 | aipipe-resume | 核对现状，续原分支和 PR |

六项是 Markdown Skill，**不是六个同名 CLI 子命令**。初始化、设计、拆片、发布可分开调用；CLI 不读取 docs 调用模型生成设计。

| 项目情况 | 操作 |
|---|---|
| 新模板项目 | 绑定仓库，按需要初始化；已有需求可直接规划 |
| 传统项目首次正式接入 | 生成配置和资源，保留原架构、docs、测试与任务；不生成新的业务方案 |
| 已使用 aipipe 的项目 | 复用配置与账本，只修复缺项 |
| 仅做分析、设计或本地开发 | 不要求先安装 App 或创建批次 |
| 换机器、换工具、凭据过期 | 恢复当前角色凭据映射，继续原任务 |
| 发布部分失败或需求变更 | 先比对远端，避免重复创建或覆盖已开工 Issue |

离线开发或只读评审使用 `doctor --for develop|review --offline`，不读取凭据、不访问 GitHub、不创建配置。准备远端写入或正式交接时再执行对应角色 doctor。ready_for 明确本次就绪用途；business_acceptance.evaluated 为 false，不能推导可合并。

## 2. 文件与执行入口

```text
项目根目录/
├── .aipipe/
│   ├── AGENTS.md / SKILL.md / README.md
│   ├── project.json / compatibility.json
│   ├── skills/              六个独立能力
│   ├── templates/           Issue / PR 正文模板
│   ├── plans/               发布输入，不是状态数据库
│   └── references/          人读与 Agent 使用文档
├── .github/workflows/aipipe-*.yml
├── docs/                    产品需求与开发文档，可沿用原位置
└── 业务源码、测试、构建配置
```

**完整模板检出**另含 `.aipipe/src/`、`scripts/`、`tests/`、`pyproject.toml`，可直接执行 `python3 .aipipe/scripts/aipipe.py`。**使用已安装 CLI 接入传统项目**时，scaffold 仅补 Skills、模板、参考资料及配置，不复制 CLI 源码；该项目须使用已安装的 `aipipe`，不能假定上述脚本存在。

`.aipipe/AGENTS.md` 是内容入口，但多数工具不会因为该文件存在于子目录就自动读取它。启动提示应显式要求先读该文件，再读选定 Skill。原生 Skill 转发入口按需由操作者安装，当前无自动安装命令。

aipipe 文件集中在 `.aipipe/`；GitHub 固定路径例外统一带 `aipipe-` 文件名前缀。已有业务 workflow 保留原名。产品 docs、测试、锁文件和 Wrapper 属于业务交付物，不能随工具删除。

## 3. 初始化与交接条件

Owner 优先使用 gh 完成仓库与 GitHub API 操作；App 注册、安装及必要账号授权通过浏览器引导完成。`init repo/apps/credentials/checks` 可分别执行，也可交互选择；`init repo` 写入成功不等于项目已完全可交接。

初始化 AI 先检查项目配置、remote、原生命令和 Owner 的仓库外 App 元数据。已有 App / 安装直接复用；只增加已授权仓库，不重新创建身份。跨 Owner 或权限更宽的共享 App 需 Owner 通过 auth trust-app 登记仓库外明确信任；项目配置不能自我授权，token 仍只申请当前仓库与最小角色权限。注册中断后核对已生成对象，补登记并续接。

配置只记录 repository、default_branch、App / Installation ID、slug、credential_ref、commands、ci、可选 preferences、最低 CLI 版本与可选 attribution 策略。凭据引用映射由宿主在仓库外保存。日常角色操作不读 Owner 私钥；`auth issue-token` / 初始化凭据步骤由 Owner 读取私钥签发并保存短期 token。**不应笼统声称整个 CLI 永远不读取私钥。**

| 核验用途 | 实际检查边界 |
|---|---|
| doctor --for plan | 读取可解析的项目配置，不访问 GitHub；不是需求或方案质量检查 |
| doctor --for publish | 目标 remote、Delivery 身份与单仓库 token |
| doctor --for develop / review | 本角色身份、可见的工作流与规则结构 |
| doctor --for handoff | 两角色身份，加 Owner 对完整规则的读取与核对 |

GitHub App 读取 ruleset 时隐藏 bypass 名单，接收端不为此获取管理权限。完整 handoff 的 Owner 审计补足该视图。doctor 通过不代表产品测试有效、批次完整或凭据永不过期；批次完整性由 release 另行核对。多个 required_checks、传统默认分支保护及有效仓库/组织规则可以只读审计；无法读取或存在冲突时停止，不能当作任意保护模型都已兼容。

## 4. 空项目与已有项目的 CI

模板自带 `.github/workflows/aipipe-ci.yml`，检查名 `aipipe-template-checks`，只运行 aipipe 的测试。它不是产品业务 CI。

Developer / Delivery 都没有 Workflows 写权限。空项目交给 Developer 前，**Owner 或初始化 AI 必须先写好调用约定原生命令的业务工作流**；首片再实现代码、锁文件与有效测试。`init checks` 只核对 check 来源、设置 rulesets 及仓库合并选项，不生成 YAML、业务命令或测试用例。

先确定测试契约、完成工具配置与必要维护，再启用和核验业务门禁。例如空前端项目的业务工作流调用约定的 npm 脚本，源码和测试尚未交付时检查应真实失败，由首片实现使其通过。已有保护规则不能为初始化或维护自动降级；Owner 应按现有规则设计前置维护步骤。

已有项目先运行 `init checks --audit`，只读核对实际有效的仓库/组织规则、传统默认分支保护、角色写入限制及额外约束；支持多个必需检查。未知来源、检查源冲突或写入限制冲突会停止。当前支持传统主分支保护与 feature ruleset 组合，不自动迁移任意旧通配保护，不覆盖或降低原规则。

## 5. 方案、切片与发布

用户选择的 AI 从需求、docs、代码或现有 Issue 编写所需开发方案；按模块拆成可验收行为，写明依赖、范围、验收条件、测试要求、实际执行目录与命令。近期片写到可执行程度，远期保留概要。

初期构思可使用 Obsidian；定稿后方案与发布计划进入 GitHub，后续只维护仓库正式版本，原笔记冻结。详见[文档与账本](documentation.md)。方案先提交到目标仓库。批次 JSON 的 design_path 指向方案文件，发布使用固定的完整 commit SHA。发布器离线预览，显式 apply 才通过 Delivery 写 GitHub，按序创建 Milestone 和 Issue；内容一致时复用，不同则停止。外部依赖、跨仓库协调不由发布器自动解析。

发布成功仍保持 released=false。放行用 `release --milestone N --plan FILE --design-ref SHA --apply`：核对身份与门禁，并只读比对实际 Milestone、原计划切片完整内容、依赖和重复标记。缺片、额外任务、错误依赖或内容冲突均拒绝；编辑器末尾换行不算 Milestone 内容变化。不传 apply 只核对，检查不补发或改写任务。测试契约是否足够仍须发布者和独立验收者判断。

Issue / PR 正文与权限要求见 [Issue/PR 契约与权限规范](issue-pr-contract.md)。

## 6. 开发、验收与推进

一个实际开发切片 Issue 使用一个固定分支 `aipipe/issue-N`。App 没有 Workflows 写权限；Owner 的独立工作流安装任务使用 `aipipe/owner-issue-N` 并经过原有质量与审批规则，不扩大 App 权限。Developer 领取时已知 N，创建 PR 直接写 `Closes #N`。接管原任务时续接原分支和 PR，不建立额外编号服务。

默认一个仓库同时推进一个开发切片。该串行规则由操作者和 Skill 遵守；同一个 Developer App 的多个会话仍可能同时推送，没有原子 Claim、租约或 fencing。

开发者在同一个 PR 交付业务实现与有效测试，记录实际自检命令、结果和 SHA。未完成保持 Draft。独立验收会话使用 Delivery 身份核对当前提交与测试，给出原生 Review；新提交使旧批准失效。GitHub 能区分账号身份，不能证明两个 AI 上下文确实独立。

验收与 required CI 均满足后，使用带 reviewer 身份和明确 head SHA 的即时 squash 入口；CLI 将原提交作者及 trailers 汇入合并正文。带身份的入口不接受 auto 或 admin；回读确认实际合并、分支删除、Issue 关闭和必要回归，再处理下一片。

返修沿用原 PR 和轮次，默认三轮后记录阻塞；轮次与重启恢复是 Skill 约定，CLI 不执行计数器。没有下一任务、验收者未启动、凭据失效或需要决策时停在明确边界，由用户继续会话。

### 阶段与里程碑（0.4.4 起）

Issue 是里程碑计数单位，PR 不加入 milestone，通过 Closes 关联，避免同一交付重复计数。阶段标签跟随分支、Draft、Review、合并和取消事实；ready 不等于已放行，批准不等于已合并，关闭不等于已交付。取消任务按正式范围调整处理；件数进度不等于工时完成率。

metadata 可独立检查或显式修复；init metadata 可独立生成 Owner 安装工作流。默认分支受信任自动化更新标签，Developer 保留 Issue 只读；Delivery 的 Review/merge 后同步。直接外部 Review 由半小时巡检恢复，受 GitHub 调度延迟影响。没有新增 App、模型客户端或常驻服务。工作流未合并时使用 CLI 核对修复，不宣称自动更新已生效。详细状态与权限见模板规范及源码 references/metadata.md。

### 代码作者与实际处理人

两个 GitHub App 继续隔离权限。每个会话显式声明工具、实际模型（不可确认写 unknown）、角色和 Agent UUID；身份文件是 `.aipipe/.runtime/agents/` 下的非秘密参数，事实记录留在 GitHub。模型不能从 App 或项目偏好推断，身份声明不是不可伪造证明。

`identity create` 创建身份，`commit --identity FILE --issue N --message-file FILE` 以 `工具 / 模型` 为 Author，以实际执行者加角色为 Committer，使用 UUID 声明邮箱并写 trailers；不修改 Git 全局配置、不自动暂存、不改写旧历史。代提交和多作者分别保留来源。PR、规划发布、放行与 Review 写入使用同一身份参数；Review 通过 REST commit_id 绑定验收 SHA。初始化或本地设计用 identity show 的 operation 段落随非秘密文档提交。

项目可启用 attribution.required，并以启用前完整 SHA 作为 legacy_before；新写入须带身份，push 检查基线后的新提交。换工具、模型或角色创建新身份，旧 PR 记录保留。辅助标签等无正文接口沿用平台账号并由对应交接记录关联，不为每次查询或测试额外发表评论。具体命令与边界见 [身份记录](identity.md)。

## 7. 语言与规模

CLI 使用 Python 3.9+ 标准库，调用外部 gh / git；Owner JWT 签名依赖 openssl。已采用可安装包与模块拆分，当前没有因 Vue 或 Java 业务栈而重写 Node.js 的必要。

业务测试通过原生命令接入：Vue 的单元、组件、类型、构建与必要 E2E；Java 的 Maven / Gradle 单元与实际绑定的集成测试；混合仓库按模块与契约组织回归。CLI 的 commands 是 cwd + argv 配置，不自动推断语言或生成测试。

Vue、Java 和大型多模块项目属于可接入设计，尚没有完整业务闭环的实测证明。先完成独立开发/验收的一条真实业务链路，再验证多模块集成与回归范围；测试 job 可以并行，任务调度和跨仓库原子合并不在当前实现范围。

## 8. 移除与维护

停用时先保存工作、移交业务 CI 与 required checks，再移出 `.aipipe/` 和 aipipe 前缀工作流，清理当前项目专属 App 规则、安装关联和宿主入口。共享 App 保留其他仓库；业务 docs、源码、测试、锁文件和 GitHub 账本保留。全局 CLI 另行卸载。

每次 aipipe 新版本交付必须同步当前验证项目，同步范围与完成条件见 [文档与账本的同轮同步约定](documentation.md)；不得留下全局与项目内置版本差异让接收工具自行处理。

升级时先 inspect，核对真实入口、CLI/资源/内置源码版本。compatibility.json 与项目最低 CLI 要求取更严格值；版本不足会在执行或读取角色凭据前停止，旧资源不会被重标为新版。旧于 0.3.0 的二进制尚不识别该契约，接收者须先升级已核实入口。升级仍需审查并保留 project.json、计划和定制约定，没有自动升级、回滚或移除命令。

后续改进按[渐进重构实施设计](refactoring.md)分片交付；其中目标接口在对应版本发布前不代表当前 CLI 已具备该能力。
