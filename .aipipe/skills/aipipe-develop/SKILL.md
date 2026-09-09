---
name: aipipe-develop
description: 开发指定 GitHub Issue，或在已放行批次中按顺序领取切片；在原任务分支同步实现业务代码和测试、自检并提交包含已知 Issue 编号的 PR。可直接处理已有项目。
---

# Issue 开发

读取 [公共入口](../../AGENTS.md)、[status 只读交接状态](../../references/status.md) 和 [配置执行入口](../../references/configuration.md)。传统项目首次正式接入先用 init 登记原有能力；已经接入的项目复用配置。用户给出 Issue 时直接处理它，不强迫重新规划。需要按批领取时，读取 GitHub Milestone 的放行说明、切片顺序、前置 Issue 的真实合并结果和现有活动 PR，选择第一个可执行切片。不要把手工关闭的 Issue 当作已交付。

仅做离线开发时运行 `aipipe doctor --for develop --offline`，不要求 App 或远端门禁；这不授权 GitHub 写入。准备正式远端领取、推送或创建 PR 前运行 `aipipe doctor --for develop`，核实本宿主的 Developer 身份与远端门禁；不读取 Delivery token。App/安装/本机凭据缺失时按 init 补具体缺项，token 过期请 Owner 刷新，不能回退个人 gh 登录。项目尚无业务代码时允许原生测试待首片建立，但不能缺少可用角色身份。

## 领取与开发

1. 读取目标 Issue、相关设计版本和已有 PR；优先用 `aipipe status --issue N --role developer --json` 建立只读交接事实。记录已知编号；若已有活动分支或 PR，继续使用它。新任务从最新目标基线创建 `aipipe/issue-N`。
2. 核对工作区，保留用户未提交内容。已有脏工作区先使用不冲突的隔离检出；不能覆盖或自动清理用户改动。
3. Developer token 只用于任务读取、分支推送和 PR 操作。阶段由 GitHub 元数据工作流更新，Delivery 负责核对与修复；放行和 Issue 管理由 Delivery 执行；Developer 在 PR 正文和 Review COMMENT 中记录自检与交接，不因缺 Issue 写权限去索取 Delivery 私钥。
4. 通过 `aipipe run NAME` 运行配置的原生检查；GitHub 使用 `aipipe github --role developer -- ...`，推送使用 `aipipe push --role developer BRANCH`。执行器解析外部凭据，不要求每个工具另写认证逻辑。
5. `.github/workflows/` 已由 Owner 预置；需要改工作流时明确交给 Owner 按原 PR 流程处理，不用 Developer 推送后反复重试权限错误。同步实现业务代码和有效测试。项目采用 Vue、Java 或其他语言，沿用其原生构建、配置与测试目录；参见 [项目测试接入](../../references/testing.md)。
6. 在不带 GitHub 写 token 的进程运行项目检查。断言业务结果和边界；修复缺陷时用回归用例证明旧行为出错。测试失败则修复；未执行的检查如实记录，不能把计划命令写成通过结果。

## 登记命令与定位失败

修改 `project.json.commands` 时使用对象和参数数组，例如 `"e2e":{"cwd":".","argv":["npm","run","test:e2e"]}`；键名允许字母、数字、`_`、`.`、`-`，原生脚本中的冒号放在 argv。修改后立即运行 `aipipe config validate`，再用 `aipipe run NAME` 验证真实入口。`invalid configured command` 或 `commands[...]` 错误先修项目配置，不请求刷新 App；只有凭据到期/认证证据才转 Owner。具体修复方式见配置执行入口。

读取里程碑用 `aipipe api --role developer milestones/N`；不要把 `gh api` 放进 github 子命令，也不存在 `gh milestone view`。业务自检失败应继续修复本 Issue；远端凭据阻塞不妨碍本地修复。需要留下未完成的交接时使用 Draft PR 并说明失败，不能称为开发完成。

## 提交与连续推进

用 `aipipe commit --identity FILE --issue N --message-file FILE` 提交，再带身份 push，随后读取 [PR 模板](../../templates/pr.md)，直接填写 `Closes #N`，记录本次自检的 SHA、命令与结果。使用正文文件提交，避免 shell 转义改变 Markdown；未完成则保持 Draft。

创建后查看实际 PR 的目标分支、正文和检查，交给独立验收上下文。返修仍使用同一 Issue、分支和 PR，遵循 GitHub 上的返修轮次，不通过新 PR 重置次数。

本次若仅授权一个 Issue，交付后结束。若授权连续批次，则在原生会话能力内等待验收与 CI；确认 PR 已合并、开发分支已删除、实际目标分支的必要回归与收尾完成，再领取下一片。验收者尚未启动时提供其启动提示并等待用户启动，不自行调用开发工具，也不以自己的 Review 代替独立批准。

## 实际执行身份

发生写入前读取 [身份记录](../../references/identity.md)，创建本会话身份（工作角色 / 凭据角色：developer / developer），实际模型不可确认时写 unknown。提交代码时用 `aipipe commit`；相关角色写命令传 `--identity FILE`。不沿用其他工具的 Agent ID，不把人类宿主名当代码作者；恢复操作保留前任作者与交接记录。只读操作不强制创建身份。

## 阶段与元数据

读取 [元数据约定](../../references/metadata.md)。尽早推送任务分支或 Draft PR；创建 PR 后执行 `aipipe metadata --pr N --role developer`，核对唯一 Closes #Issue、阶段标签、Issue 有 milestone 且 PR 的 milestone 为空。异步同步未完成或失败时交接给 Delivery/Owner，不索取其凭据。
