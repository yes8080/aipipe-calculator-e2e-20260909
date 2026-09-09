# aipipe status 只读交接状态

`aipipe status (--issue N | --pr N) --role developer|delivery [--offline] [--json]` 从本地配置与 GitHub 账本读取一个 Issue/PR 的当前交接状态。它不读取身份文件，不写配置、凭据、Git 或 GitHub，也不代替 `doctor` 的 Owner 门禁审计。

状态只描述这次只读观察，不缓存任务状态：

- `ready` 表示当前观察到的必要远端事实均满足，后续写入仍必须重新绑定 head 和规则。
- `pending` 表示事实完整但还在等待 Review、checks、Draft 转 ready 或 PR 创建。
- `failed` 表示配置、角色、关联、Review、checks 或关闭未合并等事实明确阻断。
- `unknown` 表示远端、规则、native reviewDecision、head 结束回读或 GitHub 响应不完整，不能据此继续写入。

退出码：`ready` 返回 0；`pending`、`failed`、`unknown` 返回 1；参数解析错误仍由 CLI 返回 2。`pending/pr_missing` 和离线模式的 `unknown` 是交接状态，不表示项目初始化失败。

在线模式先读取本地配置、兼容性和 Git remote，再只读取所选角色凭据。角色诊断仅说明该角色 token 是否能以对应 App bot 读取当前仓库；它不说明 Owner 审计、业务验收或另一角色可用。离线模式不读取凭据、不访问 GitHub，远端事实固定为 `unknown`。

Issue 目标通过 GitHub cross-reference 与 PR 正文的唯一 `Closes #N` 关联 PR。没有关联 PR 时，developer 视角会返回 `pending/pr_missing` 并提示创建或续接 `aipipe/issue-N` 分支后开 PR；这表示任务等待开发交接，不是初始化失败。多个活动 PR、跨仓库或多重 closing reference 会阻断为 `ambiguous_association`。PR 目标也会反查唯一 Issue，避免续接错误任务。

打开的 PR 会报告 head/base、Draft/closed 状态、原生 `reviewDecision`、`mergeStateStatus`、当前 head 的 Review 摘要，以及可见 rules 和项目配置要求的 required checks。GitHub 接受的 check-run conclusion 是 success、skipped、neutral；输出保留原始 conclusion，不把 skipped/neutral 称为测试已执行通过。该语义来自 GitHub 的 [Troubleshooting required status checks](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks)。同名 check run 与 commit status 同时存在时两者都必须满足；无法可靠读取 required rules、commit status 或最终 head 时返回 `unknown`。

已合并 PR 的 checks 绑定 `merge_commit_sha`，另行展示当前默认分支 head；不能用后续 main 绿色掩盖本次 merge commit 的失败或不可读。
