# aipipe Issue、PR 模板与 App 权限规范

本规范对应 `.aipipe/templates/issue.md`、`pr.md` 与实际 App / ruleset 实现。总体流程见 [aipipe 连续流水线设计方案_20260907](design.md)，未实现与待验证边界见 [aipipe 实现核对与待办清单_20260908](implementation-status.md)。

## 1. Issue 正文与发布输入

Issue 模板是供发布器填充的 `string.Template` 文件，网页不会自动发现它。实际字段结构如下；这是源码模板，不能作为已经填写完成的任务直接发布。

```markdown
$marker

## 任务
- 批次：$batch
- 切片：$slice_id
- 顺序：$sequence
- 前置 Issue：$dependencies
- 方案：[$design_url]($design_url)

## 目标
$goal

## 范围
$scope

## 不包含
$out_of_scope

## 验收条件
$acceptance

## 测试要求
$test_requirements

## 验证命令
$verification

## 交付物
$deliverables
```

批次 JSON 顶层包含 batch、milestone、design_path、slices。每片包含 slice_id、sequence、depends_on、title、goal、scope、out_of_scope、acceptance、test_requirements、verification、deliverables。verification 是 directory / command 对象列表；depends_on 当前只接受本批次前面的 slice_id，不是任意跨仓库依赖解析器。

发布器实际校验顺序为 1..N、ID 唯一、依赖只指向前片，以及必填文本；正式 apply 还确认固定 design-ref 下确实有方案文件。测试命令字段存在不代表命令已运行或有效。具体机器可读示例以 [batch.example.json](../plans/batch.example.json) 为准。

每个 Issue 的 marker 供同一计划重复发布时识别，不是任务锁。初次创建时添加 aipipe:ready，但只有对应 Milestone released=true 且前置任务真实交付后才能领取。手工关闭前置 Issue 不能替代合并证据。

## 2. PR 正文

以下与当前模板一致：

```markdown
Closes #<已领取的 Issue 编号>

## 实现
<完成的业务行为、涉及模块及主要改动>

## 测试
- 新增或更新：<测试文件和行为场景>
- 验收条件：<本次覆盖的条件>
- 执行目录与命令：<实际执行内容>
- 结果：<通过、失败或未执行；附必要证据>
- 自检提交：<实际 commit SHA>

## 元数据核对
- 对应 Issue：<领取时已知编号，与首行一致>
- milestone：<仅 Issue 加入；PR 保持为空，避免重复计数>
- labels：<阶段及 Issue 分类，创建后用 aipipe metadata 核对>

## 未完成与交接
- 未完成：<无，或具体工作>
- 下一步：<验收或返修内容>
- 返修轮次：<首次提交填 0；后续延续原记录>
```

Developer 已领取 #N，就从当前目标基线建立 aipipe/issue-N，并填写 Closes #N。PR body 使用文件传入，避免 shell 改写正文。已有分支/PR 则续接；Draft 可以未完成，转待验收前完成实现与自检。

GitHub 合并到默认分支时处理关闭关联；必须回读 Issue 实际状态。原 gh 封装不解析测试结果。0.4.4 的 metadata 同步入口先扫描全文关闭引用，再校验唯一独占行的 Closes #N 和 GitHub 关联记录，拒绝额外关闭引用（含段落内、同号重复、跨仓库及 URL），限定默认分支 PR；它不猜测开发者已知的编号，不建立编号数据库。开发与验收 Skill 仍核对实际任务和测试。规范行前后均扫描；普通关联写 Related #N。扫描保守处理文本，代码示例或引用块中的明文关闭指令也计入，不模拟 Markdown 渲染。

## 3. 阶段与里程碑计量

**只有 Issue 加入 milestone，PR 的 milestone 保持为空。** Issue 是交付任务，PR 是同一任务的实现与验收记录，通过 `Closes #N` 关联；两者一起加入会重复计数。GitHub 的原生进度包含关联的 Issue 和 PR；例如三个 Issue 中完成一个，进度为 1/3；再将它的已合并 PR 计入后会显示 2/4，使同一交付被重复统计。[GitHub milestone 说明](https://docs.github.com/en/issues/using-labels-and-milestones-to-track-work/about-milestones)。

阶段为 `aipipe:ready`、`active`、`review`、`changes-requested`、`blocked`、`done`、`cancelled`，同一对象只保留一个阶段。Issue 从实际分支和活动 PR 推导；Draft 为 active，等待验收/CI/合并为 review，未解决的 REQUEST_CHANGES 为返修，合并才是 PR done。Issue 手工关闭不作为交付证明。ready 不代表批次已放行或依赖已交付。

PR 添加 Issue 的非阶段标签，同时保留自己的人工分类标签。同步器不擅自修改 Issue 的 milestone 或发布计划；维护任务使用独立维护里程碑，不混入业务 M1。取消任务需要 Owner 确认范围调整后移出本期，再以 not planned 关闭；不能把取消当交付，也不能以 milestone 100% 代替 Review、CI 或合并证据。件数进度不代表工时或复杂度加权进度。

0.4.4 提供 `metadata --pr N --role developer` 只读检查；Delivery/Owner 带实际身份和 `--apply` 修复并回读。Developer 不得写 Issue，也不持有 Delivery 凭据。`init metadata` 独立生成 `.github/workflows/aipipe-metadata.yml` 和 `.aipipe/automation/` 下两个运行文件，Owner 经正常 PR 安装，主分支合并后才生效。现有 App 权限不增加。

工作流只运行默认分支的可信自动化，使用 GITHUB_TOKEN 的最小 Issues/PR 写权限；不执行 PR 业务代码或测试、不读取 App 私钥、不执行批准或合并。inline 模式下 Review/merge CLI 成功后立即同步；workflow 模式下只返回 metadata pending，由默认分支 workflow_run 或显式 metadata 修复。外部直接 Review 由轻量信号 workflow 和有界巡检恢复，不保证实时。详细状态规则、安装更新和限制见 [元数据指南](metadata.md)。

## 4. 两个 App 的实际职责

| 权限 | Developer | Delivery |
|---|---|---|
| Contents | Write | Write |
| Pull requests | Write | Write |
| Issues | Read | Write |
| Actions / Checks | Read | Read |
| Metadata | Read | Read |
| Workflows / Administration / Commit statuses Write | 不授予 | 不授予 |

Developer 读任务、推分支、维护 PR；Delivery 发布与维护任务、独立验收、请求合并并收尾。Owner 维护 App、安装、规则和工作流。两角色足以满足当前分工，但不提供字段级隔离；Delivery 的规划发布与验收使用同一权限集，没有按阶段收窄 token。

默认新 App 与角色 token 使用表中的最小权限。同 Owner 且恰好匹配角色的 App 直接复用；跨 Owner 或权限更宽的 App 需 `auth trust-app` 核对真实 ID、Owner、完整权限并按授权保存仓库外信任记录。记录绑定仓库和角色，权限漂移会拒绝；实际签发仍只申请当前仓库及最小角色权限，并检查返回权限。该模型已有确定性测试，真实组织安装/SSO 尚需对应账号环境验证。

普通角色命令只读取本角色 token；测试执行器清除已知及声明的凭据环境变量，但同一系统账号仍可能读取凭据文件或钥匙串。真正的开发/验收/Owner 隔离需要宿主账号或容器；CLI 不创建这种隔离环境。

## 5. GitHub 门禁与检查边界

| 规则 | 当前生成行为 |
|---|---|
| 主分支质量 | 至少 1 个批准、旧批准失效、最后推送需其他身份批准、严格 required check，禁止强推和删除；无 bypass |
| 主分支写入资格 | Delivery 仅在 PR 路径获得更新资格；不能绕过上面的质量规则 |
| aipipe/issue-* 写入资格 | Developer 获得创建和更新资格；这条规则不限制删除 |

ci.required_checks 可保存多个 context / integration_id，旧单检查字段继续兼容。Owner 的 `init checks --audit` 只读审计实际仓库/组织规则、传统默认分支保护与额外约束，来源或写入资格冲突时停止；不会覆盖旧规则。App 看不到 legacy 管理字段及完整 bypass，完整 handoff 仍由 Owner 审计。

规则限制的是 GitHub 身份和分支，不保证验收者用了独立 AI 上下文、不保证单个开发会话占有分支，也不判断测试质量。独立上下文和有效测试仍须按 Skill 执行。

## 6. 测试、合并与收尾

业务实现与有效测试同 PR：新功能检查正常与边界行为；缺陷修复用回归测试证明；跨模块变更核对接口与集成行为。测试使用项目原生目录和入口，不放入 aipipe 工具测试目录。业务 CI 应识别空测试并失败，这属于项目测试配置要求，不是 CLI 自动提供的保证。

Owner 预置业务 workflow；Developer 无 Workflows 写权限，不通过重试推送解决权限缺口。模板检查 aipipe-template-checks 只测试工具；业务项目的 ci 由首片真实实现和测试使其通过。

Delivery 独立核验当前 SHA，使用 reviewer 身份和 --match-head-commit 提交 APPROVE 或 REQUEST_CHANGES。批准与 CI 均满足后用带身份、指定 SHA 的即时 squash 入口合并，保留原作者与合并处理人；不使用 auto/admin。返修时取消已有自动合并请求，续原分支、原 PR 和轮次。

合并后核对合并提交、目标分支检查、Issue 关闭与开发分支删除。用户授权的一次初始化维护例外不构成日常自动放宽门禁的权限。

## 7. 作者、验收与其他处理人的记录

| 场景 | 记录内容及位置 |
|---|---|
| 代码开发 | Git Author 为工具 / 实际模型；Committer 为执行者及角色，trailers 关联 Agent UUID 和 Issue；代提交与共同作者分开 |
| 创建或编辑 PR | 保留业务正文及 Closes #N，追加执行身份；编辑保留前任有效记录 |
| 规划、切片发布、放行 | 设计署名段落、Issue/Milestone 发布身份、放行身份；幂等核验剥离有效身份段落后仍检查业务内容 |
| 验收 | Review 原生 commit_id 及正文 SHA、报告、工具、模型、reviewer、UUID；实际账号为 Delivery App |
| 合并 | 明确 head SHA，squash 正文汇总原作者、原提交 SHA/trailers 和实际合并人 |
| 初始化、配置维护 | identity show --operation initialization 生成段落进入非秘密交接记录；不记录 token 或私钥 |

示例：先运行 `aipipe identity create --tool codex --model unknown --role developer --credential-role developer`，后续 `commit`、`push`、GitHub 写命令显式使用返回的 identity_file。验收身份使用 reviewer/delivery。Agent UUID 区分执行上下文，GitHub App 决定权限；换 UUID 不能把同一会话伪装成独立验收。

旧历史不猜测模型或修改作者；0.4.0 起使用 `<UUID>@agents.aipipe.invalid` 声明邮箱，让提交作者显示工具/模型。完整操作方法见 [正式身份指南](identity.md)。
