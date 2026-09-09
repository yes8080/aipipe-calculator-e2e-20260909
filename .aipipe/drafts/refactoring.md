# aipipe 轻量化重构评估

状态：历史评估草稿；A–C 已采纳为 [实施契约](../references/refactoring.md)，代码实现状态以 GitHub 为准。评估基线：0.4.6，提交 `857a0e453aacdd1162f28efccb9501b87d42b13a`。日期：2026-09-08。

本文件是维护者审查用草稿，不进入安装包或项目 scaffold。当前行为仍以 `references/`、CLI help 和代码为准。文中的新增命令、字段和指标均为设计目标；通过设计评审后再登记实施 Issue。实际执行状态只在 GitHub 中维护。

## 1. 结论与取舍

建议渐进重构，不重写语言、不扩大平台边界。核心问题是重复准备、状态散落、部分成功表达不清和手工分发，而不是 Python 执行速度。当前约 2,805 行 Python 实现已有有效回归，整体重写会重开已解决的权限、发布恢复和合并续接问题。

| 决策 | 理由 |
|---|---|
| 保留 Python + 标准库 + gh/git/openssl | 主要成本在远端往返、环境准备与 Agent 阅读；Vue/Java 的原生命令无需 CLI 使用同一语言 |
| 保留两个 GitHub App | 区分开发写入和独立审批已足够；Owner 负责初始化，Actions 使用仓库 GITHUB_TOKEN，不新增第三个常驻 App |
| 保留六个独立 Skill，但缩短入口 | 初始化、规划、发布、开发、验收、恢复是不同能力，不能强制串成固定流程 |
| 保留一个 Issue 一个分支、同片实现与测试、独立 Review、SHA 绑定合并 | 这些约束避免错误交付，不属于应删除的冗余；PR 不计入里程碑 |
| 合并重复的事实读取、归属记录和资源生成 | 让 CLI 处理确定性步骤，让 AI 做方案、实现、测试质量与验收判断 |
| 删除正式资源中的项目案例流水账 | 项目名称、实例 ID、业务 CI 记录与处理历史属于原项目，通用回归用匿名夹具 |
| 延后常驻调度、数据库、分布式抢占、跨仓库原子合并 | 当前没有证据证明这些复杂度能解决主要成本；先优化单仓库完整闭环 |

两 App 是凭据边界，不是模型或进程隔离。用户可授权宿主用独立子智能体连续执行；也可自行启动外部客户端。aipipe 提供同一 Skill 与 CLI 契约，不负责调用模型 API。一个宿主进程能读两个 token 并不等于操作系统隔离。

## 2. 代码证据与问题优先级

这里记录通用代码证据，不复制下游项目日志。早期初始化误报、命令 schema 诊断、squash 后续接、单一关闭引用及重复 DELETE 404 已有修复与回归，不能再次列为“尚未实现”。

| 优先级 | 当前证据 | 影响与建议 |
|---|---|---|
| P0 | `runner.execute` 在确认 Review/merge 成功后同步 metadata；失败最终以异常退出 | 调用者必须解析文本才能判断是否重试。分开主操作和附属同步结果，避免重复 Review/merge |
| P0 | `runner` 与 metadata workflow 都会写阶段标签；workflow 无 concurrency | 有重复写和竞态；0.4.6 只修复已证实的重复删除场景，不代表多写入源问题消失 |
| P0 | `inspect`、`doctor`、PR/Issue/CI/metadata 分开查询 | 每次接手都由 AI 拼装状态。提供一次调用、按用途读取的只读状态入口 |
| P1 | `initialize.scaffold` 仅补缺少文件，`compatibility` 诊断版本但不升级 | 维护者手工同步源码、资源、生成文件和全局 CLI；缺少差异预览与定制冲突处理 |
| P1 | `metadata.workflow` 的巡检逐 Issue 调用 facts；一个错误直接终止循环 | 大批任务读放大，单个坏关联会阻止其余任务处理；要逐项隔离错误、最后汇总失败 |
| P1 | `.github/workflows/aipipe-ci.yml` 监听所有 push 与 PR，安装并跑全部工具测试 | 业务改动也重复验证工具；按路径区分工具检查，保留业务必需检查 |
| P1 | `GhError` 主要只保留 HTTP/退出码；HTTP 请求经 gh 每次启动子进程 | 保留资源、请求 ID、限流信息和明确错误分类；先优化往返，不据此换 HTTP SDK |
| P1 | 文档入口、Skill、多个 references 重复讲凭据、版本、身份和收尾 | Agent 阅读长、维护容易漂移；一个主题一个规范来源，角色 Skill 只列操作和异常出口 |
| P2 | 完整模板含 CLI 源码、工具测试；安装后的 scaffold 不含源码 | 两种接入产物的可用命令不同。定义清晰的轻量运行资源与完整维护检出 |

### 可复现的读放大基线

在 `tests/test_metadata_events.py::EventAPI` 上加请求计数、运行当前 `Reconciler.reconcile`：单 Issue、一个开放 PR、没有分页扩展时，修复 PR 标签及错误 milestone 需要 **13 次读取、2 次写入**；已经一致时仍需 **6 次读取、0 次写入**。

这 6 次读取是 Issue、仓库、关联 GraphQL、PR、Reviews、开发分支。不是网络延迟或成本账单实测，不外推为所有项目的固定请求数。CLI 的 PR 解析和收尾查询还可能增加请求。当前每半小时巡检开放任务；同样夹具下 N 个任务至少重复 N 次仓库读取。

验证和优化目标必须用同一夹具及相同正确性条件比较，不以删除分页、省略冲突检测或使用旧审批换取更少调用。

## 3. 目标结构：保留现有模块，抽出三个边界

不先大规模搬文件。沿调用链把三类职责明确分开：

1. **读取 GitHub 事实**：`github` 负责传输、分页、错误；新增薄的事实读取模块供 doctor、metadata、状态入口复用。一次调用内部复用已读的 repository 信息；没有跨进程业务缓存或本地任务账本。
2. **计算动作**：现有 `metadata.plan`、发布比对、角色与版本校验尽量是纯函数，输入明确的事实，输出差异和阻断。身份声明生成不直接决定工作流阶段。
3. **执行并确认**：保留现有 commit、push、发布、Review、merge 入口，返回结构化结果。CLI 路由只解析参数，不再用字符串异常同时表达业务成功和同步失败。

`identity.py` 只在确有测试保护后分离“记录格式”与“GitHub 操作适配”；`initialize.py` 不因行数直接拆十几个文件。继续从同一源码生成可信自动化文件，CI 检查生成结果与源码一致，不手工维护第二份实现。

## 4. 一次接手：只读状态与稳定输出

建议新增一个入口，名称在接口实施时固定：

```text
aipipe status --issue N --role developer --json
aipipe status --pr N --role delivery --json
aipipe status --issue N --role developer --offline --json
```

输入是项目、明确角色、Issue 或 PR；从现有配置和 GitHub 恢复任务，不另造 Claim ID。输出最小字段：`schema_version`、repository、issue、pr、head、base、阶段及其事实来源、required checks、原生 Review 概况、角色就绪用途、阻断、建议下一动作与可复制命令。所有字段区分 `unknown`、`pending`、`failed`，不能把未知视为通过。

- 在线状态按本轮目的读取；计划/本地编码不要求完整 Owner 审计。离线模式不访问网络，不读凭据，不暗示已验证远端。
- 结果只用于接手与诊断。批准和合并仍重新读当前 head，最终由 GitHub 原生规则裁决；状态输出不授权合并。
- 记录 `observed_at` 与 head。一次多请求快照不是 GitHub 原子事务；发生变化就明确标为需刷新。
- Agent 明确传入本会话身份，不使用仓库级共享 `current-agent`。长参数由宿主会话变量保存，不建立全局隐式角色。
- Skill 不再每次要求依次运行 inspect、config validate、多个 doctor、metadata 和重复 gh 查询；只有状态指出具体缺项时才打开对应诊断。
- 不加 `develop`、`review`、`next` 等虚假的模型启动子命令。规划和验收仍是 AI 工作，CLI 只提供事实与受控操作。

目标：同一用途接手从多步人工拼装收敛到一条状态命令；只读重复执行写入数为零。测量 API 请求数与 elapsed，但暂不承诺网络端到端秒数。

## 5. 主操作、附属同步与重试

建议所有远端写入口最终支持统一 `--json` 结果，先覆盖 Review/merge：

```json
{
  "schema_version": 1,
  "operation": "merge",
  "primary": {"status": "succeeded", "head": "FULL_SHA", "merge_sha": "FULL_SHA"},
  "metadata": {"status": "pending"},
  "retry": {"scope": "metadata", "command": "aipipe metadata --pr N --role delivery --identity FILE --apply"}
}
```

建议退出码：0 表示该命令的主请求已确认成功；明确失败为 1；结果未知为 2。附属同步 pending/failed 必须同时输出警告和可恢复步骤，不能声称完整交付。`status`/验收收尾单独判断 `delivery_complete`：实际合并、目标分支检查和分支清理条件全部成立才是 true。旧脚本的退出码语义保留在兼容期，不能静默改变。

| 情况 | 处理 |
|---|---|
| 本地配置/身份错误、401/403 权限不足 | 不重试，不重建 App；指出准确字段或角色，必要时交 Owner |
| 429、明确限流、可重试的只读 5xx | 读取 Retry-After / rate-limit headers，有限等待与重试；超出本轮时间预算返回可恢复结果 |
| POST Review / PUT merge 超时 | 标记 unknown，先回读匹配当前 SHA/事件/操作人的记录；没有证据就不自动再次写入 |
| 主操作成功，metadata 不一致 | 只补 metadata，不重复 Review/merge |
| DELETE 标签返回 404 | 保留 0.4.6 的完整回读确认；不能泛化成所有 404 均成功 |
| 关联暂未索引或状态在读写间改变 | 有界刷新事实后重新计算；不能用之前的计划盲重放 |

批量写保持串行并节流。错误输出保留 method、repository-relative path、status、GitHub request ID 和重试分类；不打印 token、JWT、认证头或未经清洗的请求体。优先扩展 `gh api --include/--paginate/--slurp` 适配，不复制完整 GitHub SDK；仍须检查分页完整性和结构。[GitHub API 最佳实践](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api)、[gh api](https://cli.github.com/manual/gh_api)。

## 6. 元数据以事件为主，修复可独立执行

推荐稳态由可信默认分支的 Actions 同步展示状态；CLI 保留只读核对和显式修复，移除正常 Review/merge 后必然执行的第二次标签写入。迁移期间只有在确认对应 workflow 已安装且可运行后才启用此模式，未安装项目继续明确的 CLI 同步模式，不能静默丢失更新。

- 标签是原生 Issue/分支/PR/Review 事实的投影，不是合并门禁。短暂延迟显示 pending，下一任务资格仍读依赖的实际合并事实。
- 普通 PR、Issue、开发分支事件只针对相关 Issue。非任务分支、tag 和无关事件显式忽略，不能落入全量扫描分支。
- Review 提交/撤销的事件覆盖需要补齐；使用默认分支可信代码，绝不 checkout 或执行 PR 代码。事件上下文的 GITHUB_TOKEN 权限限制要真实验证，不能为补标签扩展两个 App 的权限。
- workflow 的标签写入用仓库 GITHUB_TOKEN；这类写入不会再触发标签工作流，因此不能把现状说成无限递归。App 写标签仍可能额外触发事件。[GitHub 工作流触发规则](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)。
- 同一 Issue 的工作流使用同一 concurrency group，先解析规范 Issue 号再进入写步骤；不取消正在写入的执行。同 Issue 的后续事件以最新事实收敛，不依赖事件顺序。全量巡检拆成相同目标执行，显式 CLI 修复仍可能并发，因此幂等和回读不可删除。
- GitHub 默认 concurrency 可能替换 pending 任务，不等于可靠队列。必须覆盖“事件合并后仍处理最新事实”和“不同 Issue 不互相丢失”的验证；不要只加仓库级 `cancel-in-progress` 就宣布竞态已解决。[Concurrency 语义](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)。
- 定时巡检作为漏事件恢复，不承担日常调度。第一步保持现有频率获得基线；事件覆盖通过后再按观测降频。仅扫开放任务无法恢复遗漏的最终 closed 事件，应补近期关闭窗口；人工全量历史修复仍单独执行。
- 一个任务的非法关联不能阻止其他任务；逐项记录结果，最终工作流仍以失败结论暴露未修复项。无变化不追加评论。

优化预算：单任务的 repository 信息每轮最多读一次；有无 PR 已足以确定 active 时省略无用分支读取；批量过程中共享不变信息。同一夹具无变化检查目标从 6 次降至不超过 5 次读取；写后仍刷新受影响事实。不要为多合一 GraphQL 查询删除其他显式关联的歧义检查。

## 7. 初始化、凭据与资源升级

### 初始化保持可组合

保留 `init repo/apps/credentials/checks`，每步输出 `unchanged / applied / blocked` 以及真实资源 ID。交互输入只是参数收集，最终与非交互调用走同一实现。只读规划、已有项目接入、已有方案拆片互不强制依赖。

空项目先由 Owner 在保护建立前准备工具配置和真实业务 CI 契约；首片把真实测试从红变绿。已有保护不能为了 bootstrap 临时关闭，工具维护也不能伪造业务 ci 成功，存在冲突应设计正常维护 PR 或明确 Owner 前置步骤。

### 凭据按需准备

installation token 有一小时有效期，长期任务必须把凭据准备视为正常运行条件。[GitHub token 文档](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app)。

建议扩展 Owner 的既有 `auth issue-token`，增加到期阈值与 no-op 行为；宿主在准备角色上下文或收到明确到期结果时调用。Developer/Reviewer 不自动读取 Owner 私钥，不回退个人 gh，不增加 token broker。没有受信签发宿主时，只暂停远端写入，本地开发/只读验收继续。

多角色签发避免相互覆盖 registry，保存使用锁和同目录临时文件原子替换；只保留已授权的 repository/role 范围。token 视为不透明字符串，不依赖固定长度或自行解码得到权限。

### 可预览的资源同步

建议新增：

```text
aipipe upgrade --from TRUSTED_WHEEL --project PATH
aipipe upgrade --from TRUSTED_WHEEL --project PATH --apply
```

默认输出差异，不访问模型、不写 GitHub、不自动提交。artifact 路径或版本必须明确；不下载不明同名包。

1. 包内清单声明工具管理的资源、版本与哈希；项目内 `.aipipe/installed.json` 只保存安装基线，不保存任务状态或秘密。
2. 对每个管理文件比对“旧发布哈希 / 当前文件 / 新发布文件”。当前仍等于旧版才可更新；用户修改则冲突停下，已与新版一致则 no-op。已移除旧管理文件也按同样规则处理。
3. `project.json`、plans、项目专属交接、业务文件默认保留；有 schema 迁移时显示字段级计划。草稿、实测案例和维护账本绝不分发。
4. 老项目没有安装基线时，先识别明确旧版 artifact；无法证明来源的文件列为冲突，不直接以“模板较新”覆盖。
5. workflow 差异独立列出，需 Owner 正常 PR 安装；升级工具不借个人登录绕过 App 限制。默认分支生效前不得宣称新事件处理已启用。
6. 文件批量写入前完成校验；失败回滚本地文件，不回滚 GitHub 事实。版本标记最后更新。全局 CLI 按当前 venv 的已核实路径单独安装与验证。

新版本的模板、安装产物、活动验证项目及生成运行文件必须同轮核对；该验证清单由维护环境指定，正式资源不硬编码任何下游项目名称。没有新版本发布的设计草稿不触发安装升级。

## 8. Skills、文档和 CI 的减量

入口分两层：AGENTS 只写共同不变量和路由；单个 Skill 写本角色输入、最短正常路径、异常出口和输出位置。凭据、身份、metadata、版本各只有一份规范；角色入口链接过去，不全文复制。人读 README 负责安装与场景选择，维护手册不作为每次开发的必读材料。

正式仓库只放通用规范与匿名测试夹具；项目专属操作记录留在各自 GitHub。草稿放 `.aipipe/drafts/`，既不 force-include 到 wheel，也不经 scaffold 复制。定稿后按主题取代旧规范，不永久叠加一篇新的“最终方案”。

CI 分类：

- 工具 CI 对工具源码、资源、测试及工具 workflow 变化运行；pull_request 验证合并候选，默认分支 push 验证实际合并结果，普通开发分支 push 不重复跑同一套工具测试。
- 业务 required check 保留稳定名称和真实执行入口，不因工具路径过滤处于永久 pending。旧项目额外 required checks 必须先审计，不能盲删。
- 工具专属仓库执行完整安装产物/资源一致性验证；业务仓库按相关变更跑工具兼容 smoke 与原生产品 CI。测试项目用于候选版本验证，仍需要完整工具回归，不因“轻量”省略。
- 开发自检、独立验收、PR CI、main CI 目的不同，应保留；同一上下文同 SHA 的无意义重复 npm ci/全量测试可省。跨 SHA 或环境变化不能沿用过期证据。
- 已有验收暴露过“类型命令成功但没有覆盖源码/测试”和“成功路径替身实际走保存失败”的通用风险。首片验收应验证命令确实覆盖目标、成功路径确实发生预期副作用，必要时用临时错误探针；这类独立检查发现的返修是质量收益，不能归为工具冗余。不要为每个后续小改动机械重复同一探针。
- 后续默认用户模板可分发轻量资源，完整源码检出留给维护者；先交付升级和兼容检测，再迁移旧完整模板项目，不直接删除其可用脚本。

## 9. 实施顺序与完成标准

下表是提案中的依赖顺序，不是已发布的任务账本。不在本次评估中创建各实施切片。

| 阶段 | 交付 | 验收与停止条件 |
|---|---|---|
| A：减少误判 | 统一结果协议，先覆盖 Review/merge；通用错误与请求诊断 | 成功后 metadata 失败只建议补同步；未知写结果先回读；原权限/署名/分页/旧历史回归保持 |
| B：减少接手步骤 | 只读 status、用途化诊断、短 Skill 路径 | 一条命令可说明原 Issue/PR 当前事实和下一动作；离线不触网；写前 head 变化被识别 |
| C：减少重复同步 | 事件主写模式、逐项错误隔离、按 Issue 并发协调、CI 触发减量 | 先 shadow 只计算差异，对齐旧结果；真实事件/漏事件/并发修复通过后切换；回退仅恢复旧同步模式，不回滚 merge |
| D：减少版本漂移 | 可预览 upgrade、资源基线、Owner 到期阈值与原子保存 | 定制文件不被覆盖；无基线不猜；第二次升级零差异；失败不留下新版本标记；两角色 registry 并发无丢失 |
| E：证明可推广 | 轻量产物、新项目/传统项目/已有配置续接矩阵 | 匿名 Node 前端与 Java Maven/Gradle 最小项目各完成真实原生命令；跨工具独立上下文有 GitHub 证据；未实测的平台如实标记 |

A–C 是第一阶段推荐实施范围；D 单独评审文件迁移；E 不与基础重构捆绑为一次大 PR。每片同时交付实现、行为测试、CLI help、唯一规范的更新及版本同步。

### 必须保留或补齐的回归

- 初始化部分完成不放行、缺片/冲突不重复发布、角色和 repository 不匹配在写前拒绝。
- 多页 Issues/PR/Reviews、改名分支、多个关闭引用、索引延迟、重复事件与过时事件。
- 重复 DELETE 的不存在确认、标签仍在/读取失败不误吞、其他 4xx 不当成功。
- 主操作成功后同步失败、写入超时但服务端成功、head 改变、过期批准、main CI 失败。
- token 到期与权限缺失区分；续签失败不覆盖有效旧文件，测试进程不带写 token。
- 同次巡检包含一个坏任务和多个好任务：好任务完成，最终仍报告失败任务。
- 资源生成可重复、wheel 不含草稿/项目实例、升级冲突/删除/中断/重复执行。

效率验收使用固定匿名夹具：记录 API 读取数、写入数、gh 子进程数、工作流触发数、正常接手命令数和 Agent 必读字数。目标为重复执行零写入、每轮仓库信息只读一次、业务源码变更不重复跑工具全量测试、标准接手一条命令可得必要事实。API 路径优化须与行为断言同时通过；真实耗时按环境记录，不先承诺百分比。

## 10. 本次变更与范围边界

本次完成评估、正式文档通用化清理，以及打包验证发现的草稿排除修正：旧 sdist include 会匹配草稿中的 README，现已显式排除 drafts。没有发布 CLI 新版本，也没有实施上述新命令或修改权限、工作流、业务代码。GitHub 中保留原始 Issue/PR/Review 历史，不通过改写历史制造“从未发生问题”的记录。

下一步是评审本提案的 A–C 接口与迁移顺序，再发布有限实施切片。若实施中数据表明新抽象增加命令、文件或人工恢复成本，停止扩展并收回该抽象，不能用继续加补丁替代评估。
