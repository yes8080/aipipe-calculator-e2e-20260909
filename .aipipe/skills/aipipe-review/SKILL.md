---
name: aipipe-review
description: 在独立上下文验收已有 GitHub PR，核对 Issue、实现、有效测试和当前提交；通过后使用 Delivery 身份批准并按授权请求原生合并，失败则退回原 PR。
---

# 独立验收

读取 [公共入口](../../AGENTS.md)、[status 只读交接状态](../../references/status.md) 和 [配置执行入口](../../references/configuration.md)。可以直接验收现有 PR，无需重新运行规划或初始化。开发者的自检是待核实证据，不是你的验收结论。只读本地评审或测试可用 `aipipe doctor --for review --offline`，无需凭据；提交远端 Review 或请求合并前，再用 `aipipe doctor --for review` 核实本宿主 Delivery 身份和远端门禁；它只检查交接条件，仍需逐个验收当前 PR。

1. 读取 PR、对应 Issue、设计契约、完整改动和当前 head SHA；优先用 `aipipe status --pr N --role delivery --json` 建立只读交接事实。确认验收上下文独立，GitHub 身份是 Delivery，作者是不同身份；同一身份不得冒充独立验收。
2. 在干净检出中检查实现是否满足验收条件、是否越界，测试是否覆盖关键行为、边界和错误。运行项目原生检查及必要的独立验证；执行代码和测试的进程不持有 Delivery 写凭据或 App 私钥。
3. 存在问题则对原 PR 提交 REQUEST_CHANGES，给出可复现行为与明确完成条件；已有 auto-merge 请求先取消，返修次数写回原 PR。不要替开发者改完代码再自称独立验收。
4. 通过后先再次读取 PR head。若代码已变化，重新验证变更，不将旧证据批准到新提交。原生 Review 明确记录验收 SHA、场景和实际结果。
5. 仅在用户授权交付合并、原生独立审批和必需 CI 规则有效时，使用带 reviewer 身份的即时 `pr merge --squash --match-head-commit SHA`；CLI 汇总原提交作者与合并处理人。带身份的入口不使用 auto；先等待 CI 与审批，按当前 SHA 合并后回读。失败则记录并停止，不升级为绕过权限。检查以仓库实际配置为准，新模板默认规划 `ci`，已有项目沿用现有门禁；不写自建合并服务，不用 `--admin`。
6. 合并后核对合并记录、目标分支检查和开发分支删除，Delivery 更新任务收尾。不能仅凭 auto-merge 请求成功就报告已经合并。

若 GitHub App、CI 或规则尚未具备，仍可完成只读评审和测试，并准确指出尚不能执行的批准或合并动作。按需调用 `aipipe-init` 补缺，不能把整次验收退回从头初始化。

正式使用 aipipe 接入传统项目时先补相关初始化；已接入项目直接验收。配置的测试使用 `aipipe run NAME`，GitHub 读写使用 `aipipe github --role delivery -- ...`。验收工具与模型由用户选择，执行器不会启动它们。

doctor 的 ready 仅针对 ready_for 指定的用途。business_acceptance.evaluated 始终为 false：它不运行业务 CI、不证明测试有效或已独立批准。空项目可通过开发前置检查，同时显示原生命令尚未登记；正式验收仍按当前 PR 的实现、测试与原生 GitHub 门禁判断。

## 实际执行身份

发生写入前读取 [身份记录](../../references/identity.md)，创建本会话身份（工作角色 / 凭据角色：reviewer / delivery），实际模型不可确认时写 unknown。提交代码时用 `aipipe commit`；相关角色写命令传 `--identity FILE`。不沿用其他工具的 Agent ID，不把人类宿主名当代码作者；恢复操作保留前任作者与交接记录。只读操作不强制创建身份。

提交 Review 使用 `--match-head-commit SHA`（aipipe 扩展）及 `--body-file FILE`，通过 REST commit_id 绑定已验收的 SHA；发现问题提交 REQUEST_CHANGES。不要一边代写业务修复、一边批准自己的修改。

## 阶段与元数据

读取 [元数据约定](../../references/metadata.md)。原生 Review/merge 成功后 CLI 自动同步；合并前和收尾核对 `aipipe metadata --pr N --role delivery`，有差异带本上下文身份加 `--apply`。同步失败只修 metadata，不重复已成功的 Review/merge，不把手工关闭当完成。
