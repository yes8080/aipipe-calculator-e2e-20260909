# Issue 与 PR 元数据

GitHub 是账本。阶段标签反映已有事实，不授予领取、验收或合并权限。`ready` 只表示尚未开始；领取仍须检查批次放行、依赖真实合并及是否已有活动切片。

| 阶段标签 | 事实 |
|---|---|
| `aipipe:ready` | Issue 开放，尚无任务分支或活动 PR |
| `aipipe:active` | 已推送任务分支，或 PR 仍为 Draft |
| `aipipe:review` | 非 Draft PR 等待验收、CI 或合并；批准不等于交付 |
| `aipipe:changes-requested` | 活动 PR 存在尚未被批准或撤销的 REQUEST_CHANGES |
| `aipipe:blocked` | Owner/Delivery 显式标记阻塞；解除时移除此标签 |
| `aipipe:done` | PR 已合并；Issue 已关闭且有关联合并 PR |
| `aipipe:cancelled` | PR 未合并关闭，或 Issue 关闭且没有关联合并 PR |

同一对象只保留一个已知阶段标签；保留所有其他标签。PR 继承 Issue 的非阶段标签，milestone 必须为空。一个 Issue 是一个交付任务，只有 Issue 计入里程碑；PR 是实现和验收记录，通过 `Closes #N` 追踪同一任务，不能重复计数。同步会清除受管理 PR 的 milestone，但不改变 Issue 的里程碑归属。不删除 PR 原有业务分类标签，避免误删人工信息；源 Issue 分类标签被移除后，需人工确认是否也移除 PR 上的同名标签。未合并 PR 关闭不代表对应 Issue 交付；Issue 重开恢复待办/开发状态。多个活动 PR 对应一个 Issue 时停止同步，先解决任务归属。

只处理目标为仓库默认分支的 PR。PR 事件先读取当前 PR 和实际默认分支；目标不符或来自外部仓库时直接跳过，不触发 Issue 写入。PR 正文必须有唯一独占一行的 `Closes #N`。接受这行之前，先使用同一套规则收集全文中的关闭引用；段落内、带冒号、大写、仓库限定名及 GitHub Issue/PR URL 都不能隐藏额外引用，也不允许重复关闭同一 Issue。不能使用跨仓库编号或一 PR 关闭多片。普通关联使用 `Related #N`，不使用关闭关键词。此为保守的正文校验，不执行 Markdown 渲染；代码示例和引用块里的关闭指令也计入，避免把额外关闭指令放在 PR 正文示例中。CLI 已知编号仍来自开发任务；自动化用该关联查找目标，避免从标题猜测。普通提及不计为任务关联；涉及本 Issue 的无效或歧义关闭指令在计算阶段前报错，不能当成没有 PR 而将任务降为 ready。PR 事件与 CLI 都绑定明确的 expected_pr；GitHub 尚未索引对应关联时零写入并报错，稍后重试 metadata，不重复创建 PR。Issue、分支事件、巡检与 dispatch 复用同一关联校验。

## 安装与更新

```bash
aipipe init metadata --non-interactive             # 预览
aipipe init metadata --non-interactive --apply     # 生成本地文件
```

生成 `.github/workflows/aipipe-metadata.yml` 和 `.aipipe/automation/{metadata,github}.py`。后两者是从当前 CLI 的唯一源码生成的运行文件，不手工修改；不依赖项目 npm、Java 或 Python 包安装。更新前审查差异并移除这三个旧生成文件，再重新生成；命令拒绝覆盖不同内容。Owner 通过正常 PR 安装，主分支合并后才生效，不给两个 App 增加 Workflows 权限。分支写规则限制 `aipipe/issue-*` 时，Owner 工作流安装使用独立的 `aipipe/owner-issue-N` 维护分支，每项仍绑定一个 Issue，质量与独立审批要求不变。

工作流只检出默认分支上的受信任自动化文件，以仓库 `GITHUB_TOKEN` 更新元数据；只声明 Actions read、Contents read、Issues/PR write。Actions read 仅用于在 `workflow_run` 路径按 run id 重读原生 run 事实，不扩大 App 权限。不运行 PR 源码、业务安装或测试，不读取两个 App 的凭据，不批准或合并 PR。GitHub 原生事件记录执行账号，Actions 日志记录 run、触发者、实际变更；不把 github-actions 伪装成开发 Agent。

PR、Issue、分支创建/删除触发即时同步；独立验收 CLI 在 inline 模式下于原生 Review/merge 成功后立即同步。项目配置 `metadata.mode` 缺省为 `inline`；Owner 通过普通 PR 安装并验证默认分支可信工作流后，才可显式设为 `workflow`。workflow 模式下 Review/merge 的结构化结果只报告 `metadata.status=pending`，不重复写标签；后续由默认分支工作流或显式 `aipipe metadata` 修复。模式选择写在 `project.json`，启用证据写在 GitHub，不增加本地运行账本或“已验证”布尔字段。

Review 信号使用独立的 `aipipe review signal` workflow：监听 `pull_request_review`，无写权限、不 checkout、不上传/下载 artifact、不使用 cache，只产生一个轻量 run。GitHub 官方事件表说明 `pull_request_review` 的 `GITHUB_REF` 是 PR merge branch，`workflow_run` 在默认分支运行；因此不能在信号 workflow 中执行可信 metadata 写入，必须由 `aipipe metadata` workflow 通过 `workflow_run` 使用默认分支源码。[Events that trigger workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)。metadata workflow 只从 event payload 取 run id，再用 Actions API 重读原生 run facts，严格验证 workflow name、event、conclusion、repository 和唯一 PR 关联；随后重读当前 PR 与 Issue ledger。缺失或多个 PR 关联、run 未完成、失败或事实不可读时返回不可判定并非零退出，绝不退回全仓扫描；跨仓库或非默认 base 属于无关事件，跳过并说明原因。

绕过 aipipe CLI 直接写 Review 的工具由 Review 信号或每小时 17、47 分的巡检补齐，GitHub schedule 可能延迟，不能保证实时。schedule 与默认 workflow_dispatch 都扫描开放且带 aipipe 阶段标签的 Issue，并扫描最近 14 天内按更新时间倒序的 closed Issue。开放扫描上限为 10 页，近期关闭窗口上限为 2 页；超过分页安全限制会输出 `scan_truncated` 并以非零退出，但已发现的有效任务仍继续逐项同步。人工历史修复使用 workflow_dispatch 的 `closed_scope=history`，与近期窗口分离，扫描 closed Issue 的较大有界窗口，上限为 10 页；它用于补历史账本，不表示自动巡检会覆盖任意久远状态。不声称任意长时间漏事件都能自动恢复。工作流写入不会自触发无限标签循环。尚未推送的纯本地分支不可观测，应尽早发布任务分支或 Draft PR。

metadata workflow 使用 GitHub 原生 concurrency `queue: max` 串行同仓库 metadata run。GitHub workflow syntax 说明 `queue: max` 最多保留 100 个 pending run；队列满后的取消、GitHub 调度顺序和外部 CLI 写入不构成全局互斥。[Workflow syntax: concurrency](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#concurrency)。重复执行仍依赖写前事实和写后回读确保收敛。

## 检查与修复

```bash
aipipe metadata --pr 42 --role developer                       # 只读；有差异退出 1
# 独立 Delivery 上下文（或获授权 Owner 使用 --role owner）
aipipe metadata --pr 42 --role delivery --identity FILE --apply
aipipe metadata --issue 7 --role delivery --identity FILE --apply
```

Issue 缺 milestone 时报告 `milestone_missing: true` 并退出 1，由规划者/Owner 补齐，不擅自分配业务里程碑。默认只读；Developer 不得加 apply，不能为改 Issue 标签获取 Delivery token。手工写入必须提供当前执行身份，实际有变更时在 Issue 记录处理人。写后重新读取 GitHub 事实，重复执行无变化不写入；权限错误、关联歧义、状态竞争或部分失败明确退出，检查后重跑 metadata。Review/merge 已成功但同步失败时不会重复 Review/merge。

0.4.6 对重复删除阶段标签做有限的幂等处理：DELETE 返回 404 后，完整分页读取该 Issue/PR 的当前标签；仅在读取成功且目标标签已不存在时继续，不重试 DELETE。标签仍在、读取失败或其他 HTTP 错误仍报错；随后继续原有的最终 GitHub 事实核验，生命周期发生变化时也不报告同步成功。REST 错误包含请求方法、仓库、资源编号和编码后的标签路径，不包含 token 或请求正文。

该行为处理 CLI 与事件工作流交错同步时已删除标签的情况，不吞掉所有 404，不重复成功的 Review/merge。历史日志未记录具体资源的 404 不能统一归因；失败记录与实际 API 验证见[Issue #14](https://github.com/yes8080/aipipe-template/issues/14)。

验收工具提交 Review 后、请求合并前、合并收尾时核对 metadata；开发工具创建 PR 后检查对应 Issue、labels、Issue 的 milestone 及 PR 的空 milestone，工作流未完成时报告待同步，交给 Delivery/Owner 修复。PR 的空 milestone 是正确状态；缺少阶段标签或 Issue 的 milestone 则需修复。一次 workflow 巡检中单个任务失败不会阻断其他任务同步，但最终退出失败并逐项输出结果。

维护 Issue 也须明确范围、验收条件、阶段和里程碑。没有业务批次时建立独立维护里程碑，例如“aipipe 工具维护”；不要把工具升级加入已有业务发布计划的 Milestone，避免破坏切片集合校验。PR 不加入 milestone，通过关联 Issue 追溯其所属里程碑。

## 进度与交付口径

GitHub 的原生 milestone 百分比按关闭条目数统计，不按工时、复杂度或业务价值加权。aipipe 只纳入 Issue，避免 PR 重复计数；例如三片完成一片应为 1/3，而非再计一个已合并 PR 后的 2/4。大型项目要比较工作量时，需另行估算，不能把件数百分比称为工时完成率。

取消任务不算交付。Owner 确认移出本期范围后，再移除其 milestone 并以 not planned 关闭，在原 Issue 留下范围调整原因；同步器只标 cancelled，不擅自缩减计划范围。已发布批次有取消或拆分时，先按发布契约调整计划，不能通过改标签使完整性检查通过。误关闭、重开、取消或默认分支 CI 失败都必须单独核实；milestone 100% 不是验收证明。开发任务正常由目标默认分支的合并关闭，验收仍以独立 Review、必需 CI 和实际合并为准。
